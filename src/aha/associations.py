"""Bounded association worklists, impact previews and atomic accepted assignments."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import secrets
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from datetime import date, datetime, time, timedelta
from time import monotonic
from typing import TYPE_CHECKING, Any

from . import ledger, project_links, projects
from .decimal_sql import DecimalSum
from .domain import BEIJING, AppError, canonical_bytes, content_hash

if TYPE_CHECKING:
    from .storage import Store

MAX_RECORDS = 100_000
MAX_SESSIONS = 1_000
MAX_METADATA = 20_000
FILTER_FIELDS = {"project_id", "directory", "session_id", "reason", "start_date", "end_date"}
REASONS = {"all", "recoverable", "directory_unbound", "missing", "conflict"}


def _metadata(
    connection: sqlite3.Connection,
    requested_sessions: list[str] | None = None,
) -> tuple[dict[str, dict[str, Any]], bool]:
    """Only the bounded session domain is materialised, never the consumption table."""
    rules = project_links.directory_rules(connection)
    results: dict[str, dict[str, Any]] = {}
    truncated = False
    query = "SELECT * FROM sessions"
    parameters: list[Any] = []
    if requested_sessions is not None:
        query += " WHERE id IN (SELECT value FROM json_each(?))"
        parameters.append(json.dumps(requested_sessions))
    query += " ORDER BY id LIMIT ?"
    parameters.append(MAX_METADATA + 1)
    with closing(connection.execute(query, parameters)) as cursor:
        for index, row in enumerate(cursor):
            if index == MAX_METADATA:
                truncated = True
                break
            entry: dict[str, Any] = {
                "session_id": row["id"],
                "current_hash": row["content_hash"],
                "status": row["status"],
                "cwd": None,
                "reason": "missing",
                "version_id": None,
                "project_id": None,
            }
            if row["status"] == "matched" and row["cwd"]:
                try:
                    canonical_path = projects.canonical_path(row["cwd"])
                except AppError:
                    entry["reason"] = "conflict"
                else:
                    entry.update(cwd=row["cwd"], canonical_path=canonical_path)
            else:
                candidates: dict[str, dict[str, Any]] = {}
                invalid = False
                versions = connection.execute(
                    "SELECT * FROM session_metadata_versions WHERE session_id=? "
                    "ORDER BY id LIMIT 129",
                    (row["id"],),
                )
                with closing(versions):
                    for position, version in enumerate(versions):
                        if position == 128:
                            invalid = True
                            break
                        try:
                            payload = json.loads(version["payload_json"])
                            if not isinstance(payload, dict) or payload.get("status") != "matched":
                                continue
                            cwd = payload.get("cwd")
                            if not isinstance(cwd, str):
                                invalid = True
                                continue
                            path = projects.canonical_path(cwd)
                            if content_hash(payload) != version["content_hash"]:
                                invalid = True
                                continue
                            candidates[path] = {
                                "cwd": cwd,
                                "canonical_path": path,
                                "version_id": version["id"],
                                "candidate_hash": version["content_hash"],
                                "payload": payload,
                            }
                        except (ValueError, TypeError, AppError):
                            invalid = True
                cases = connection.execute(
                    "SELECT id,state,info_json FROM reconciliation_cases WHERE type='directory' "
                    "AND record_key=?",
                    ("session:" + row["id"],),
                )
                with closing(cases):
                    for case in cases:
                        info = json.loads(case["info_json"])
                        resolved_choice = info.get("resolved_choice")
                        if case["state"] == "resolved" and resolved_choice is None:
                            prior = connection.execute(
                                "SELECT choice FROM reconciliation_events WHERE case_id=? "
                                "ORDER BY id DESC LIMIT 1",
                                (case["id"],),
                            ).fetchone()
                            resolved_choice = prior[0] if prior else None
                        if case["state"] == "open" or (
                            case["state"] == "resolved"
                            and resolved_choice == "current"
                            and any(
                                candidate["version_id"] == info.get("candidate_metadata_version_id")
                                for candidate in candidates.values()
                            )
                        ):
                            invalid = True
                if invalid or len(candidates) > 1 or row["status"] == "conflict":
                    entry["reason"] = "conflict"
                elif candidates:
                    entry.update(next(iter(candidates.values())))
            if entry["cwd"]:
                entry["project_id"] = project_links.match_directory(entry["cwd"], rules)
                entry["reason"] = (
                    "recoverable"
                    if entry["project_id"] and entry["status"] != "matched"
                    else "directory_unbound"
                )
            results[row["id"]] = entry
    return results, truncated


def _filters(value: Any, *, default_project: str = "unassigned") -> dict[str, str]:
    if value is None:
        value = {}
    if not isinstance(value, dict) or set(value) - FILTER_FIELDS:
        raise AppError("invalid_assignment_filter", "项目关联筛选格式不正确。")
    result = {"project_id": default_project, "reason": "all"}
    for field, raw in value.items():
        if (
            not isinstance(raw, str)
            or len(raw) > (8192 if field == "directory" else 256)
            or "\0" in raw
        ):
            raise AppError("invalid_assignment_filter", "项目关联筛选包含无效内容。")
        if raw.strip():
            result[field] = raw.strip()
    if result["reason"] not in REASONS:
        raise AppError("invalid_assignment_filter", "请选择有效的归属原因。")
    try:
        for field in ("start_date", "end_date"):
            if result.get(field):
                parsed = date.fromisoformat(result[field])
                if parsed.isoformat() != result[field]:
                    raise ValueError
        if result.get("start_date") and result.get("end_date"):
            if result["start_date"] > result["end_date"]:
                raise ValueError
        if result.get("directory"):
            projects.canonical_path(result["directory"])
    except (ValueError, AppError):
        raise AppError("invalid_assignment_filter", "请检查目录和起止日期。") from None
    return result


def _require_complete_metadata(
    truncated: bool, filters: dict[str, str], *, action: str | None = None
) -> None:
    if truncated and (
        action in {"recover", "reclassify"}
        or filters.get("reason", "all") != "all"
        or filters.get("directory")
    ):
        raise AppError(
            "assignment_metadata_limit",
            "本次目录依据超过检查上限，请按具体会话缩小范围后重新查询或预览。",
            409,
        )


def _where(
    filters: dict[str, str],
    metadata: dict[str, dict[str, Any]],
    *,
    keys: list[str] | None = None,
    session_ids: list[str] | None = None,
) -> tuple[str, list[Any]]:
    conditions = ["r.suppressed=0"]
    parameters: list[Any] = []
    project = filters["project_id"]
    if project != "all":
        conditions.append("r.project_id=?")
        parameters.append("" if project == "unassigned" else project)
    for field, operator in (("start_date", ">="), ("end_date", "<=")):
        if filters.get(field):
            conditions.append(f"r.day{operator}?")
            parameters.append(filters[field])
    if filters.get("start_date"):
        conditions.append("r.event_time>=?")
        parameters.append(
            int(
                datetime.combine(
                    date.fromisoformat(filters["start_date"]), time(), BEIJING
                ).timestamp()
            )
        )
    if filters.get("end_date") and filters["end_date"] != "9999-12-31":
        conditions.append("r.event_time<?")
        parameters.append(
            int(
                datetime.combine(
                    date.fromisoformat(filters["end_date"]) + timedelta(days=1), time(), BEIJING
                ).timestamp()
            )
        )
    if filters.get("session_id"):
        conditions.append("r.session_id=?")
        parameters.append(filters["session_id"])
    reason, directory = filters.get("reason", "all"), filters.get("directory")
    if reason != "all" or directory:
        normalized = projects.canonical_path(directory) if directory else None
        ids = [
            sid
            for sid, entry in metadata.items()
            if (reason == "all" or entry["reason"] == reason)
            and (normalized is None or entry.get("canonical_path") == normalized)
        ]
        if reason == "missing" and not directory:
            conditions.append(
                "(r.session_id IS NULL OR r.session_id IN (SELECT value FROM json_each(?)) "
                "OR r.session_id NOT IN (SELECT value FROM json_each(?)))"
            )
            parameters.extend([json.dumps(ids), json.dumps(list(metadata))])
        else:
            conditions.append("r.session_id IN (SELECT value FROM json_each(?))")
            parameters.append(json.dumps(ids))
    for column, values in (("record_key", keys), ("session_id", session_ids)):
        if values is not None:
            conditions.append(f"r.{column} IN (SELECT value FROM json_each(?))")
            parameters.append(json.dumps(values))
    return " AND ".join(conditions), parameters


def _rows(
    connection: sqlite3.Connection,
    where: str,
    parameters: list[Any],
    *,
    limit: int | None = None,
) -> Iterator[sqlite3.Row]:
    query = (
        "SELECT r.*,p.name AS project_name,o.content_hash AS override_hash "
        "FROM usage_records r LEFT JOIN projects p ON p.id=r.project_id "
        "LEFT JOIN overrides o ON o.record_key=r.record_key WHERE "
        + where
        + " ORDER BY r.event_time,r.record_key"
    )
    if limit is not None:
        query += " LIMIT ?"
        parameters = [*parameters, limit]
    with closing(connection.execute(query, parameters)) as cursor:
        while chunk := cursor.fetchmany(512):
            yield from chunk


def _stats(connection: sqlite3.Connection) -> dict[str, Any]:
    def count(sql: str, parameters: tuple[Any, ...] = ()) -> int:
        return int(connection.execute(sql, parameters).fetchone()[0] or 0)

    summary: dict[str, Any] = {
        "detail_count": count(
            "SELECT SUM(row_count) FROM monthly_usage_stats "
            "WHERE kind='detail' AND state!='pending'"
        ),
        "rollup_count": count(
            "SELECT SUM(row_count) FROM monthly_usage_stats "
            "WHERE kind='rollup' AND state!='pending'"
        ),
        "record_count": count(
            "SELECT integer_sum(record_count) FROM monthly_usage_stats WHERE state!='pending'"
        ),
        "unassigned_detail_count": count(
            "SELECT SUM(row_count) FROM monthly_usage_stats "
            "WHERE project_id='' AND kind='detail' AND state!='pending'"
        ),
        "unassigned_rollup_count": count(
            "SELECT SUM(row_count) FROM monthly_usage_stats "
            "WHERE project_id='' AND kind='rollup' AND state!='pending'"
        ),
        "unassigned_record_count": count(
            "SELECT integer_sum(record_count) FROM monthly_usage_stats "
            "WHERE project_id='' AND state!='pending'"
        ),
        "unassigned_cost_usd": connection.execute(
            "SELECT decimal_sum(total_cost_usd) FROM monthly_usage_stats "
            "WHERE project_id='' AND state!='pending'"
        ).fetchone()[0]
        or "0",
        "pending_count": count(
            "SELECT SUM(row_count) FROM monthly_usage_stats WHERE state='pending'"
        ),
    }
    summary["assigned_detail_count"] = summary["detail_count"] - summary["unassigned_detail_count"]
    return summary


def _status(store: Store, connection: sqlite3.Connection) -> dict[str, Any]:
    metadata, truncated = _metadata(connection)
    summary = _stats(connection)
    project_rows = []
    for project in connection.execute("SELECT id,name FROM projects ORDER BY name,id"):
        aggregate = connection.execute(
            """SELECT SUM(CASE WHEN kind='detail' AND state!='pending' THEN row_count ELSE 0 END),
            SUM(CASE WHEN kind='rollup' AND state!='pending' THEN row_count ELSE 0 END),
            integer_sum(CASE WHEN state!='pending' THEN record_count ELSE '0' END),
            decimal_sum(CASE WHEN state!='pending' THEN total_cost_usd ELSE '0' END),
            decimal_sum(CASE WHEN state='available' THEN total_cost_usd ELSE '0' END),
            decimal_sum(CASE WHEN state='claimed' THEN total_cost_usd ELSE '0' END),
            SUM(CASE WHEN state='pending' THEN row_count ELSE 0 END)
            FROM monthly_usage_stats WHERE project_id=?""",
            (project["id"],),
        ).fetchone()
        bounds = connection.execute(
            "SELECT MIN(day),MAX(day) FROM daily_usage_stats WHERE project_id=?", (project["id"],)
        ).fetchone()
        project_rows.append(
            {
                "id": project["id"],
                "name": project["name"],
                "detail_count": int(aggregate[0] or 0),
                "rollup_count": int(aggregate[1] or 0),
                "record_count": int(aggregate[2] or 0),
                "total_cost_usd": aggregate[3] or "0",
                "available_cost_usd": aggregate[4] or "0",
                "claimed_cost_usd": aggregate[5] or "0",
                "pending_count": int(aggregate[6] or 0),
                "start_date": bounds[0],
                "end_date": bounds[1],
            }
        )
    groups: dict[tuple[str, str | None], dict[str, Any]] = {}
    recoverable, directory_only, ambiguous = set(), set(), set()
    recoverable_rows = directory_rows = 0
    query = """SELECT session_id,kind,COUNT(*) AS n,integer_sum(request_count) AS represented,
        decimal_sum(CASE WHEN availability_state!='pending'
            THEN total_cost_usd ELSE '0' END) AS cost,
        SUM(availability_state='pending') AS pending,MIN(day) AS first_day,MAX(day) AS last_day
        FROM usage_records WHERE project_id='' AND suppressed=0 GROUP BY session_id,kind"""
    with closing(connection.execute(query)) as cursor:
        for row in cursor:
            if truncated and row["session_id"] and row["session_id"] not in metadata:
                continue  # Unchecked sessions are not evidence of missing directories.
            entry = metadata.get(row["session_id"], {})
            reason = entry.get("reason", "missing")
            cwd = entry.get("cwd")
            group = groups.setdefault(
                (reason, cwd),
                {
                    "reason": reason,
                    "directory": cwd,
                    "session_count": 0,
                    "detail_count": 0,
                    "rollup_count": 0,
                    "record_count": 0,
                    "total_cost_usd": DecimalSum(),
                    "pending_count": 0,
                    "start_date": row["first_day"],
                    "end_date": row["last_day"],
                },
            )
            group["session_count"] += int(row["session_id"] is not None)
            group["detail_count" if row["kind"] == "detail" else "rollup_count"] += row["n"]
            group["record_count"] += int(row["represented"] or 0)
            group["total_cost_usd"].step(row["cost"])
            group["pending_count"] += int(row["pending"] or 0)
            group["start_date"] = min(group["start_date"], row["first_day"])
            group["end_date"] = max(group["end_date"], row["last_day"])
            if row["session_id"]:
                if reason == "recoverable":
                    recoverable.add(row["session_id"])
                    recoverable_rows += row["n"]
                elif reason == "directory_unbound" and entry.get("version_id") is not None:
                    directory_only.add(row["session_id"])
                    directory_rows += row["n"]
                elif reason == "conflict":
                    ambiguous.add(row["session_id"])
    for group in groups.values():
        group["total_cost_usd"] = group["total_cost_usd"].finalize()
    summary.update(
        recoverable_sessions=len(recoverable),
        recoverable_detail_count=recoverable_rows,
        directory_only_sessions=len(directory_only),
        directory_only_detail_count=directory_rows,
        ambiguous_sessions=len(ambiguous),
    )
    return {
        **store.revisions(connection),
        "summary": summary,
        "projects": project_rows,
        "groups": sorted(groups.values(), key=lambda g: (-g["record_count"], g["reason"]))[:1000],
        "groups_truncated": len(groups) > 1000 or truncated,
        "metadata_scan_truncated": truncated,
    }


def association_status(store: Store) -> dict[str, Any]:
    with store.read_connection() as connection:
        return _status(store, connection)


def association_records(
    store: Store,
    filters: dict[str, Any],
    *,
    cursor: str | None = None,
    size: int = 50,
) -> dict[str, Any]:
    if isinstance(size, bool) or not isinstance(size, int) or not 1 <= size <= 200:
        raise AppError("invalid_page", "每页可查看 1 至 200 条记录。")
    normalized = _filters(filters)
    with store.read_connection() as connection:
        revisions = store.revisions(connection)
        metadata, truncated = _metadata(
            connection,
            [normalized["session_id"]] if normalized.get("session_id") else None,
        )
        _require_complete_metadata(truncated, normalized)
        where, parameters = _where(normalized, metadata)
        signature = content_hash([normalized, revisions])
        if cursor:
            try:
                decoded = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")))
                if (
                    not isinstance(decoded, list)
                    or len(decoded) != 3
                    or decoded[0] != signature
                    or type(decoded[1]) is not int
                    or not isinstance(decoded[2], str)
                ):
                    raise ValueError
                where += " AND r.event_time>=? AND (r.event_time,r.record_key)>(?,?)"
                parameters.extend([decoded[1], decoded[1], decoded[2]])
            except (ValueError, TypeError, IndexError, UnicodeError, binascii.Error):
                raise AppError("invalid_cursor", "分页依据已变化，请重新查询。", 409) from None
        page = list(_rows(connection, where, parameters, limit=size + 1))
        has_more = len(page) > size
        unchecked = list(dict.fromkeys(
            row["session_id"] for row in page[:size]
            if row["session_id"] and row["session_id"] not in metadata
        ))
        if unchecked:
            focused, focused_truncated = _metadata(connection, unchecked)
            metadata.update(focused)
            truncated = truncated or focused_truncated
        rows = []
        for row in page[:size]:
            entry = metadata.get(row["session_id"], {})
            rows.append(
                {
                    "record_key": row["record_key"],
                    "kind": row["kind"],
                    "session_id": row["session_id"],
                    "cwd": row["cwd"] or entry.get("cwd"),
                    "project_id": row["project_id"] or None,
                    "project_name": row["project_name"] or "未归属",
                    "assignment_origin": row["assignment_origin"],
                    "date": row["day"],
                    "model": row["model"],
                    "record_count": int(row["request_count"]),
                    "total_cost_usd": row["total_cost_usd"],
                    "reason": (
                        entry.get("reason", "" if truncated and row["session_id"] else "missing")
                        if not row["project_id"] else ""
                    ),
                    "availability_state": row["availability_state"],
                }
            )
        next_cursor = None
        if has_more:
            last = page[size - 1]
            next_cursor = base64.urlsafe_b64encode(
                canonical_bytes([signature, last["event_time"], last["record_key"]])
            ).decode("ascii")
        return {
            **revisions,
            "rows": rows,
            "next_cursor": next_cursor,
            "has_more": has_more,
            "metadata_scan_truncated": truncated,
        }


def _request(connection: sqlite3.Connection, request: Any) -> dict[str, Any]:
    if not isinstance(request, dict) or request.get("action") not in {
        "assign",
        "recover",
        "reclassify",
    }:
        raise AppError("invalid_assignment", "请选择分配、历史恢复或历史重新归属。")
    result = {
        "action": request["action"],
        "keys": [],
        "session_ids": [],
        "bind_sessions": request.get("bind_sessions", False),
        "project_id": None,
    }
    if not isinstance(result["bind_sessions"], bool):
        raise AppError("invalid_assignment", "会话分配选项不正确。")
    if result["bind_sessions"] and result["action"] != "assign":
        raise AppError("invalid_assignment", "持续会话默认只适用于已明确目标项目的分配。")
    for field, limit in (("keys", 10000), ("session_ids", MAX_SESSIONS)):
        value = request.get(field, [])
        if (
            not isinstance(value, list)
            or len(value) > limit
            or any(
                not isinstance(item, str) or not item or len(item) > 4096 or "\0" in item
                for item in value
            )
        ):
            raise AppError("invalid_assignment", "请选择有效记录或会话，或缩小批量范围。")
        result[field] = list(dict.fromkeys(value))
    if result["keys"] and result["session_ids"]:
        raise AppError("invalid_assignment", "一次请按记录或会话选择。")
    default_project = "all" if result["keys"] or result["session_ids"] else "unassigned"
    result["filters"] = _filters(request.get("filters"), default_project=default_project)
    if result["action"] == "assign":
        project_id = request.get("project_id")
        if not isinstance(project_id, str) or not project_id:
            raise AppError("invalid_project", "请选择目标项目。")
        projects._validate_project(connection, project_id)
        result["project_id"] = project_id
    for key in result["keys"]:
        canonical = ledger.canonical_record_key(connection, key)
        if (
            connection.execute(
                "SELECT 1 FROM usage_records WHERE record_key=?", (canonical,)
            ).fetchone()
            is None
        ):
            raise AppError("record_not_found", "所选记录不存在，请刷新。", 404)
    result["keys"] = [ledger.canonical_record_key(connection, key) for key in result["keys"]]
    return result


def _selection(
    connection: sqlite3.Connection,
    request: dict[str, Any],
    metadata: dict[str, dict[str, Any]],
) -> Iterator[sqlite3.Row]:
    where, parameters = _where(
        request["filters"],
        metadata,
        keys=request["keys"] or None,
        session_ids=request["session_ids"] or None,
    )
    if request["action"] == "recover":
        candidates = [
            sid
            for sid, entry in metadata.items()
            if entry.get("status") != "matched"
            and entry.get("version_id") is not None
            and entry.get("reason") in {"recoverable", "directory_unbound"}
        ]
        where += " AND r.session_id IN (SELECT value FROM json_each(?))"
        parameters.append(json.dumps(candidates))
    if request["action"] != "recover" and not request["bind_sessions"]:
        yield from _rows(connection, where, parameters, limit=MAX_RECORDS + 1)
        return
    sessions: set[str] = set()
    for position, row in enumerate(_rows(connection, where, parameters, limit=MAX_RECORDS + 1)):
        if position == MAX_RECORDS:
            raise AppError(
                "assignment_too_large", "一次最多处理十万条记录，请按目录或日期分批。", 413
            )
        entry = metadata.get(row["session_id"], {})
        if request["action"] == "recover" and entry.get("reason") not in {
            "recoverable",
            "directory_unbound",
        }:
            continue
        if request["action"] == "recover" and (
            entry.get("status") == "matched" or entry.get("version_id") is None
        ):
            continue
        if not row["session_id"]:
            if request["bind_sessions"]:
                raise AppError("invalid_assignment", "日汇总没有会话，请与会话明细分开分配。")
            continue
        sessions.add(row["session_id"])
        if len(sessions) > MAX_SESSIONS:
            raise AppError("assignment_too_large", "一次最多处理一千个会话，请分批。", 413)
    expanded = {
        "project_id": "unassigned" if request["action"] == "recover" else "all",
        "reason": "all",
    }
    where, parameters = _where(expanded, metadata, session_ids=sorted(sessions))
    yield from _rows(connection, where, parameters, limit=MAX_RECORDS + 1)


def _target(
    row: sqlite3.Row,
    request: dict[str, Any],
    metadata: dict[str, dict[str, Any]],
    rules: list[tuple[int, str, str]],
) -> str | None:
    manual = row["override_hash"] == row["content_hash"]
    if manual and (request["action"] != "assign" or request["bind_sessions"]):
        return str(row["project_id"]) or None
    if request["action"] == "assign":
        return str(request["project_id"])
    entry = metadata.get(row["session_id"], {})
    if request["action"] == "recover":
        return entry.get("project_id")
    cwd = entry.get("cwd") if entry.get("status") == "matched" else None
    return project_links.match_directory(cwd, rules)


def _evaluate(
    store: Store,
    connection: sqlite3.Connection,
    request: dict[str, Any],
    *,
    freeze: bool = False,
) -> dict[str, Any]:
    focus = request["session_ids"] or (
        [request["filters"]["session_id"]] if request["filters"].get("session_id") else None
    )
    if focus is None and request["keys"]:
        # Bounded distinct session domain, not a materialised consumption selection.
        focus = [
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT session_id FROM usage_records WHERE record_key IN "
                "(SELECT value FROM json_each(?)) AND session_id IS NOT NULL LIMIT ?",
                (json.dumps(request["keys"]), MAX_METADATA + 1),
            )
        ]
    metadata, truncated = _metadata(connection, focus)
    _require_complete_metadata(truncated, request["filters"], action=request["action"])
    rules = project_links.directory_rules(connection)
    summary: dict[str, Any] = {
        "selected_detail_count": 0,
        "selected_rollup_count": 0,
        "selected_record_count": 0,
        "changed_count": 0,
        "session_count": 0,
        "recovered_sessions": 0,
        "directory_only_sessions": 0,
        "manual_exceptions": 0,
    }
    total = DecimalSum()
    digest = hashlib.sha256()
    sessions: set[str] = set()
    target_groups: dict[str, dict[str, Any]] = {}
    project_names = {r["id"]: r["name"] for r in connection.execute("SELECT id,name FROM projects")}
    if freeze:
        connection.execute(
            "CREATE TEMP TABLE IF NOT EXISTS association_selection(record_key TEXT PRIMARY KEY)"
        )
        connection.execute("DELETE FROM temp.association_selection")
    for index, row in enumerate(_selection(connection, request, metadata)):
        if index == MAX_RECORDS:
            raise AppError(
                "assignment_too_large", "一次最多处理十万条记录，请缩小筛选或分批。", 413
            )
        target = _target(row, request, metadata, rules)
        project_links.require_directory_target(connection, row["session_id"], target)
        entry = metadata.get(row["session_id"], {})
        summary[
            "selected_detail_count" if row["kind"] == "detail" else "selected_rollup_count"
        ] += 1
        summary["selected_record_count"] += int(row["request_count"])
        summary["changed_count"] += int(target != (row["project_id"] or None))
        summary["manual_exceptions"] += int(
            row["override_hash"] == row["content_hash"]
            and (request["action"] != "assign" or request["bind_sessions"])
        )
        total.step(row["total_cost_usd"])
        if row["session_id"]:
            sessions.add(row["session_id"])
        key = target or ""
        group = target_groups.setdefault(
            key,
            {
                "id": target,
                "name": project_names.get(key, "未归属"),
                "detail_count": 0,
                "rollup_count": 0,
                "record_count": 0,
                "total_cost_usd": DecimalSum(),
            },
        )
        group["detail_count" if row["kind"] == "detail" else "rollup_count"] += 1
        group["record_count"] += int(row["request_count"])
        group["total_cost_usd"].step(row["total_cost_usd"])
        digest.update(
            canonical_bytes(
                [
                    row["record_key"],
                    row["content_hash"],
                    row["project_id"],
                    entry.get("current_hash"),
                    entry.get("candidate_hash"),
                    target,
                ]
            )
        )
        if freeze:
            connection.execute(
                "INSERT INTO temp.association_selection VALUES(?)", (row["record_key"],)
            )
    if not summary["selected_detail_count"] and not summary["selected_rollup_count"]:
        raise AppError(
            "empty_assignment", "当前筛选没有可处理记录，请调整筛选或查看待归属原因。", 409
        )
    summary["session_count"] = len(sessions)
    if request["action"] == "recover":
        summary["recovered_sessions"] = sum(
            metadata[sid]["status"] != "matched" for sid in sessions
        )
        summary["directory_only_sessions"] = sum(
            not metadata[sid]["project_id"] for sid in sessions
        )
    summary["total_cost_usd"] = total.finalize()
    warnings = []
    if request["action"] == "recover":
        warnings.append(
            "按已保存目录依据和当前项目规则重建；无项目规则的部分仅恢复目录并保留待归属。"
        )
    if request["bind_sessions"]:
        warnings.append("已展开这些会话的全部现存明细；后续新增明细也继承项目默认。")
    if summary["manual_exceptions"]:
        warnings.append(f"保留 {summary['manual_exceptions']} 条有效的逐条人工归属例外。")
    if truncated:
        warnings.append("会话依据数量超过单次检查上限，请按会话或目录分批检查。")
    for group in target_groups.values():
        group["total_cost_usd"] = group["total_cost_usd"].finalize()
    return {
        "summary": summary,
        "projects": list(target_groups.values()),
        "warnings": warnings,
        "digest": digest.hexdigest(),
        "metadata": metadata,
    }


def preview_associations(store: Store, request: dict[str, Any]) -> dict[str, Any]:
    with store.read_connection() as connection:
        normalized = _request(connection, request)
        revisions = store.revisions(connection)
        evaluated = _evaluate(store, connection, normalized)
    preview_id = secrets.token_urlsafe(24)
    public = {
        "preview_id": preview_id,
        "action": normalized["action"],
        **revisions,
        **{key: evaluated[key] for key in ("summary", "projects", "warnings")},
    }
    with store._association_preview_lock:
        store._association_previews[preview_id] = {
            "request": normalized,
            "revisions": revisions,
            "digest": evaluated["digest"],
            "deadline": monotonic() + 600,
            "public": public,
        }
        while len(store._association_previews) > 24:
            store._association_previews.popitem(last=False)
    return public


def _restore_session(
    store: Store,
    connection: sqlite3.Connection,
    entry: dict[str, Any],
    reason: str,
) -> None:
    if entry["status"] == "matched":
        return
    payload = entry["payload"]
    case_id = ledger.create_case(
        connection,
        "directory",
        "采用留存历史目录恢复项目关联。",
        {
            "session_id": entry["session_id"],
            "current_metadata_hash": entry["current_hash"],
            "candidate_metadata_version_id": entry["version_id"],
            "candidate_cwd": entry["cwd"],
            "candidate_hash": content_hash([entry["current_hash"], entry["candidate_hash"]]),
            "resolved_choice": "candidate",
            "context": "history_recovery",
        },
        key="session:" + entry["session_id"],
    )
    connection.execute(
        "UPDATE sessions SET cwd=?,status='matched',parent_id=?,content_hash=? WHERE id=?",
        (entry["cwd"], payload.get("parent_id"), entry["candidate_hash"], entry["session_id"]),
    )
    connection.execute(
        "UPDATE reconciliation_cases SET state='resolved',generation=generation+1 WHERE id=?",
        (case_id,),
    )
    connection.execute(
        "INSERT INTO reconciliation_events(case_id,choice,reason,created_at) VALUES(?,?,?,?)",
        (case_id, "candidate", reason, store._now()),
    )


def apply_associations(
    store: Store,
    preview_id: str,
    reason: str,
    idempotency_key: str,
) -> dict[str, Any]:
    if (
        not isinstance(reason, str)
        or not reason.strip()
        or len(reason) > 4000
        or not isinstance(idempotency_key, str)
        or not 16 <= len(idempotency_key) <= 128
        or not isinstance(preview_id, str)
        or len(preview_id) > 128
    ):
        raise AppError("reason_required", "请填写调整依据并重新确认预览。")
    signature = content_hash(["association", preview_id, reason.strip()])
    with store._association_preview_lock:
        cached = store._association_previews.get(preview_id)
    with store._transaction():
        connection = store._db
        prior = connection.execute(
            "SELECT * FROM reconciliation_idempotency WHERE key=?",
            ("association:" + idempotency_key,),
        ).fetchone()
        if prior:
            if prior["payload_hash"] != signature:
                raise AppError("idempotency_conflict", "同一重试标识对应不同内容。", 409)
            return dict(store._decode(prior["result_json"]))
        if cached is None or "request" not in cached:
            raise AppError("association_preview_required", "请先预览本次项目关联调整。", 409)
        if cached["deadline"] < monotonic() or cached["revisions"] != store.revisions(connection):
            raise AppError("association_preview_expired", "台账或归属依据已变化，请重新预览。", 409)
        request = cached["request"]
        evaluated = _evaluate(store, connection, request, freeze=True)
        if evaluated["digest"] != cached["digest"]:
            raise AppError("association_preview_expired", "记录或目录依据已变化，请重新预览。", 409)
        metadata = evaluated["metadata"]
        rules = project_links.directory_rules(connection)
        operation = "association:" + idempotency_key
        scopes: set[str] = set()
        handled: set[str] = set()
        for row in _rows(
            connection, "r.record_key IN (SELECT record_key FROM temp.association_selection)", []
        ):
            entry = metadata.get(row["session_id"], {})
            target = _target(row, request, metadata, rules)
            if request["action"] == "recover" and row["session_id"] not in handled:
                _restore_session(store, connection, entry, reason.strip())
                handled.add(row["session_id"])
            if request["bind_sessions"] and row["session_id"] not in handled:
                project_links.bind_session(
                    connection, row["session_id"], request["project_id"], "manual", {}, replace=True
                )
                handled.add(row["session_id"])
            if request["action"] == "assign" and not request["bind_sessions"]:
                projects._override(connection, row["record_key"], row["content_hash"], target)
                connection.execute(
                    """INSERT INTO project_assignment_events(operation_id,record_key,session_id,
                    old_project_id,project_id,basis,reason,created_at) VALUES(?,?,?,?,?,?,?,?)""",
                    (
                        operation,
                        row["record_key"],
                        row["session_id"],
                        row["project_id"] or None,
                        target,
                        "manual",
                        reason.strip(),
                        store._now(),
                    ),
                )
            elif row["override_hash"] != row["content_hash"]:
                basis = (
                    "session_binding"
                    if request["bind_sessions"]
                    else ("history_restore" if request["action"] == "recover" else "directory_rule")
                )
                project_links.link_record(
                    connection,
                    row["record_key"],
                    target,
                    basis,
                    {"cwd": entry.get("cwd"), "preview_id": preview_id},
                    operation=operation,
                    reason=reason.strip(),
                )
            scopes.add(row["scope_key"])
        store._advance_revision()
        ledger.reclassify(connection, scopes)
        ledger.refresh_availability(connection, scopes)
        result = {
            "applied": True,
            "action": request["action"],
            "changed_count": evaluated["summary"]["changed_count"],
            "recovered_sessions": evaluated["summary"]["recovered_sessions"],
            "summary": _stats(connection),
            **store.revisions(connection),
        }
        connection.execute(
            "INSERT INTO reconciliation_idempotency VALUES(?,?,?)",
            (operation, signature, store._encode(result)),
        )
        connection.execute("DELETE FROM temp.association_selection")
        return result
