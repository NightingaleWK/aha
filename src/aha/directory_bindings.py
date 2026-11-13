"""Explicit directory-wide project adoption, impact previews and atomic saves."""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from time import monotonic
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from . import associations, ledger, project_links, projects
from .decimal_sql import DecimalSum
from .domain import AppError, canonical_bytes, content_hash

if TYPE_CHECKING:
    from .storage import Store


def _draft(connection: sqlite3.Connection, value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) - {
        "project_id",
        "name",
        "description",
        "directories",
    }:
        raise AppError("invalid_project", "请检查项目名称和目录。")
    name, description = value.get("name"), value.get("description", "")
    directories = value.get("directories", [])
    project_id = value.get("project_id")
    if not isinstance(name, str) or not name.strip() or len(name) > 160:
        raise AppError("invalid_project", "项目名称不能为空，且最多为 160 个字符。")
    if not isinstance(description, str) or len(description) > 4000:
        raise AppError("invalid_project", "项目说明最多为 4000 个字符。")
    if not isinstance(directories, list) or len(directories) > 200:
        raise AppError("invalid_directory", "每个项目最多绑定 200 个目录。")
    normalized = {projects.canonical_path(d): d.strip() for d in directories}
    if project_id is not None and (
        not isinstance(project_id, str)
        or not project_id
        or not connection.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone()
    ):
        raise AppError("project_not_found", "项目不存在，请刷新。", 404)
    return {
        "id": project_id or str(uuid4()),
        "new": project_id is None,
        "name": name.strip(),
        "description": description.strip(),
        "directories": list(normalized.values()),
    }


def _configuration(
    store: Store, connection: sqlite3.Connection, draft: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, str]], set[str]]:
    config = projects.configuration(store, connection)["projects"]
    current = next((p for p in config if p["id"] == draft["id"]), None)
    if bool(current) == draft["new"]:
        raise AppError("project_binding_preview_expired", "项目已变化，请重新预览目录关联。", 409)
    wanted = {projects.canonical_path(d) for d in draft["directories"]}
    removed = {
        projects.canonical_path(d) for d in (current["directories"] if current else [])
    } - wanted
    future: list[dict[str, Any]] = []
    transfers: list[dict[str, str]] = []
    for project in config:
        if project["id"] == draft["id"]:
            continue
        retained = []
        for directory in project["directories"]:
            canonical = projects.canonical_path(directory)
            if canonical in wanted:
                transfers.append(
                    {
                        "path": directory,
                        "from_project_id": project["id"],
                        "from_project_name": project["name"],
                    }
                )
                continue
            if any(
                projects._contains(root, canonical) or projects._contains(canonical, root)
                for root in wanted
            ):
                raise AppError(
                    "directory_overlap_conflict",
                    "所选目录与其他项目的父级或子级目录重叠，请先调整目录范围。",
                    409,
                )
            retained.append(directory)
        future.append({**project, "directories": retained})
    future.append({k: draft[k] for k in ("id", "name", "description", "directories")})
    return future, transfers, removed


def _members(
    connection: sqlite3.Connection, session_ids: list[str], *, frozen: bool = False
) -> Iterator[sqlite3.Row]:
    selection = (
        "r.record_key IN (SELECT record_key FROM temp.project_binding_selection)"
        if frozen
        else "r.session_id IN (SELECT value FROM json_each(?))"
    )
    parameters: tuple[Any, ...] = () if frozen else (json.dumps(session_ids),)
    query = (
        "SELECT r.*,o.project_id AS override_id,o.content_hash AS override_hash,"
        "l.project_id AS link_id,l.basis AS link_basis,l.generation AS link_generation,"
        "l.basis_json AS link_evidence,b.project_id AS binding_id,b.basis AS binding_basis,"
        "b.generation AS binding_generation FROM usage_records r "
        "LEFT JOIN overrides o ON o.record_key=r.record_key "
        "LEFT JOIN record_project_links l ON l.record_key=r.record_key "
        "LEFT JOIN session_project_bindings b ON b.session_id=r.session_id "
        "WHERE r.kind='detail' AND r.suppressed=0 AND "
        + selection
        + " ORDER BY r.event_time,r.record_key LIMIT ?"
    )
    with closing(connection.execute(query, (*parameters, associations.MAX_RECORDS + 1))) as cursor:
        while chunk := cursor.fetchmany(512):
            yield from chunk


def _evaluate(
    store: Store, connection: sqlite3.Connection, draft: dict[str, Any], *, freeze: bool = False
) -> dict[str, Any]:
    future, transfers, removed = _configuration(store, connection, draft)
    policy = project_links.managed_projects(connection)
    metadata, truncated = associations._metadata(connection)
    if truncated and draft["directories"]:
        raise AppError(
            "assignment_metadata_limit", "目录依据超过完整检查上限，本次未保存任何关联。", 409
        )
    roots = sorted(
        {projects.canonical_path(d): d for d in draft["directories"]}.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    )
    sessions: dict[str, str] = {}
    for sid, entry in metadata.items():
        if entry.get("cwd") and entry.get("reason") != "conflict":
            candidate = projects.canonical_path(entry["cwd"])
            root = next((raw for path, raw in roots if projects._contains(path, candidate)), None)
            if root:
                sessions[sid] = root
    if len(sessions) > associations.MAX_SESSIONS:
        raise AppError("assignment_too_large", "本次目录超过一千个会话，未保存任何关联。", 413)
    if freeze:
        connection.execute(
            "CREATE TEMP TABLE IF NOT EXISTS project_binding_selection(record_key TEXT PRIMARY KEY)"
        )
        connection.execute("DELETE FROM temp.project_binding_selection")
    names = {p["id"]: p["name"] for p in future}
    names.update({r["id"]: r["name"] for r in connection.execute("SELECT id,name FROM projects")})
    summary: dict[str, Any] = {
        "detail_count": 0,
        "session_count": len(sessions),
        "total_cost_usd": "0",
        "changed_count": 0,
        "already_assigned_count": 0,
        "claimed_count": 0,
        "pending_count": 0,
        "recovered_sessions": 0,
    }
    directory_groups: dict[str, dict[str, Any]] = {
        raw: {"path": raw, "detail_count": 0, "sessions": set(), "cost": DecimalSum()}
        for _, raw in roots
    }
    change_groups: dict[str, dict[str, Any]] = {}
    total = DecimalSum()
    digest = hashlib.sha256(
        canonical_bytes([draft, future, sorted(policy), store.revisions(connection)])
    )
    used_sessions: set[str] = set()
    for index, row in enumerate(_members(connection, list(sessions))):
        if index == associations.MAX_RECORDS:
            raise AppError("assignment_too_large", "本次目录超过十万条明细，未保存任何关联。", 413)
        entry = metadata[row["session_id"]]
        used_sessions.add(row["session_id"])
        previous = row["project_id"] or ""
        changed = (
            previous != draft["id"]
            or row["link_basis"] != "directory_binding"
            or row["override_id"] is not None
            or row["binding_id"] is not None
        )
        summary["detail_count"] += 1
        summary["changed_count"] += int(changed)
        summary["already_assigned_count"] += int(previous == draft["id"])
        summary["claimed_count"] += int(row["availability_state"] == "claimed")
        summary["pending_count"] += int(row["availability_state"] == "pending")
        total.step(row["total_cost_usd"])
        group = directory_groups[sessions[row["session_id"]]]
        group["detail_count"] += 1
        group["sessions"].add(row["session_id"])
        group["cost"].step(row["total_cost_usd"])
        change = change_groups.setdefault(
            previous,
            {
                "from_project_id": previous or None,
                "from_project_name": names.get(previous, "未归属"),
                "to_project_id": draft["id"],
                "to_project_name": draft["name"],
                "detail_count": 0,
                "cost": DecimalSum(),
            },
        )
        change["detail_count"] += 1
        change["cost"].step(row["total_cost_usd"])
        digest.update(
            canonical_bytes(
                [
                    row["record_key"],
                    row["content_hash"],
                    previous,
                    row["override_id"],
                    row["override_hash"],
                    row["link_id"],
                    row["link_basis"],
                    row["link_generation"],
                    row["link_evidence"],
                    row["binding_id"],
                    row["binding_basis"],
                    row["binding_generation"],
                    row["availability_state"],
                    entry.get("current_hash"),
                    entry.get("candidate_hash"),
                    entry.get("version_id"),
                ]
            )
        )
        if freeze:
            connection.execute(
                "INSERT INTO temp.project_binding_selection VALUES(?)", (row["record_key"],)
            )
    summary["session_count"] = len(used_sessions)
    summary["recovered_sessions"] = sum(
        metadata[sid]["status"] != "matched" for sid in used_sessions
    )
    summary["total_cost_usd"] = total.finalize()
    directories = [
        {
            "path": g["path"],
            "detail_count": g["detail_count"],
            "session_count": len(g["sessions"]),
            "total_cost_usd": g["cost"].finalize(),
        }
        for g in directory_groups.values()
    ]
    changes = [
        {k: v for k, v in g.items() if k != "cost"}
        | {
            "total_cost_usd": g["cost"].finalize(),
        }
        for g in change_groups.values()
    ]
    warnings = []
    if transfers:
        warnings.append("已绑定其他项目的同名目录将整体转移，原项目的对应记录和费用会调整。")
    if removed:
        warnings.append("移除的目录将停止后续自动识别，已确认的历史记录仍保留在原项目。")
    if summary["recovered_sessions"]:
        warnings.append("将采用已留存的唯一有效历史目录，旧电脑日志不存在也可恢复关联。")
    if summary["claimed_count"]:
        warnings.append("已占用记录的项目归属会调整，报销占用和已保存材料保持原样。")
    if summary["pending_count"]:
        warnings.append("待核对记录一并关联项目，其费用仍需完成原有核对。")
    if not roots:
        warnings.append("没有选择目录，将仅保存项目；不会猜测或分配用量记录。")
    warnings.append("只关联有明确目录依据的明细；无目录、冲突依据及历史日汇总不会被猜入项目。")
    return {
        "summary": summary,
        "directories": directories,
        "changes": changes,
        "transfers": transfers,
        "warnings": warnings,
        "digest": digest.hexdigest(),
        "metadata": metadata,
        "sessions": used_sessions,
        "future": future,
        "removed": removed,
    }


def preview_project_binding(store: Store, draft: Any) -> dict[str, Any]:
    with store.read_connection() as connection:
        normalized = _draft(connection, draft)
        revisions = store.revisions(connection)
        evaluated = _evaluate(store, connection, normalized)
    preview_id = secrets.token_urlsafe(24)
    project = {k: normalized[k] for k in ("id", "name", "description", "directories")}
    public = {
        "preview_id": preview_id,
        "project": {**project, "directory_managed": True},
        **revisions,
        **{k: evaluated[k] for k in ("summary", "directories", "changes", "transfers", "warnings")},
    }
    with store._association_preview_lock:
        store._association_previews[preview_id] = {
            "kind": "project_binding",
            "draft": normalized,
            "revisions": revisions,
            "digest": evaluated["digest"],
            "deadline": monotonic() + 600,
            "public": public,
        }
        while len(store._association_previews) > 24:
            store._association_previews.popitem(last=False)
    return public


def apply_project_binding(store: Store, preview_id: str, idempotency_key: str) -> dict[str, Any]:
    if (
        not isinstance(preview_id, str)
        or not preview_id
        or len(preview_id) > 128
        or not isinstance(idempotency_key, str)
        or not 16 <= len(idempotency_key) <= 128
    ):
        raise AppError("project_binding_preview_required", "请先预览目录关联影响再确认。", 409)
    signature = content_hash(["project_binding", preview_id])
    operation = "project_binding:" + idempotency_key
    with store._association_preview_lock:
        cached = store._association_previews.get(preview_id)
    with store._transaction():
        connection = store._db
        prior = connection.execute(
            "SELECT * FROM reconciliation_idempotency WHERE key=?", (operation,)
        ).fetchone()
        if prior:
            if prior["payload_hash"] != signature:
                raise AppError("idempotency_conflict", "同一重试标识对应不同内容。", 409)
            return dict(store._decode(prior["result_json"]))
        if cached is None or cached.get("kind") != "project_binding":
            raise AppError("project_binding_preview_required", "请先预览目录关联影响再确认。", 409)
        if cached["deadline"] < monotonic() or cached["revisions"] != store.revisions(connection):
            raise AppError("project_binding_preview_expired", "台账或目录已变化，请重新预览。", 409)
        draft = cached["draft"]
        evaluated = _evaluate(store, connection, draft, freeze=True)
        if evaluated["digest"] != cached["digest"]:
            raise AppError("project_binding_preview_expired", "关联依据已变化，请重新预览。", 409)
        managed = project_links.managed_projects(connection) | {draft["id"]}
        for project in evaluated["future"]:
            connection.execute(
                "INSERT INTO projects VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                "name=excluded.name,description=excluded.description,"
                "directories_json=excluded.directories_json",
                (
                    project["id"],
                    project["name"],
                    project["description"],
                    store._encode(project["directories"]),
                ),
            )
        connection.execute(
            "INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (project_links.POLICY_KEY, store._encode({"version": 1, "projects": sorted(managed)})),
        )
        reason = "确认目录整体绑定，统一已有与后续用量归属"
        metadata = evaluated["metadata"]
        prior_defaults = {
            r[0]
            for r in connection.execute(
                "SELECT session_id FROM session_project_bindings WHERE session_id "
                "IN (SELECT value FROM json_each(?))",
                (json.dumps(sorted(evaluated["sessions"])),),
            )
        }
        for sid in evaluated["sessions"]:
            if metadata[sid]["status"] != "matched":
                associations._restore_session(store, connection, metadata[sid], reason)
            connection.execute("DELETE FROM session_project_bindings WHERE session_id=?", (sid,))
        # Retired directories must not retain a session default for new consumption.
        for sid, entry in metadata.items():
            if entry.get("cwd") and any(
                projects._contains(root, projects.canonical_path(entry["cwd"]))
                for root in evaluated["removed"]
            ):
                connection.execute(
                    "DELETE FROM session_project_bindings WHERE session_id=?", (sid,)
                )
        scopes: set[str] = set()
        for row in _members(connection, [], frozen=True):
            scopes.add(row["scope_key"])
            connection.execute("DELETE FROM overrides WHERE record_key=?", (row["record_key"],))
            project_links.link_record(
                connection,
                row["record_key"],
                draft["id"],
                "directory_binding",
                {"cwd": metadata[row["session_id"]]["cwd"], "preview_id": preview_id},
                operation=operation,
                reason=reason,
                now=store._now(),
                replace_basis=True,
                force=row["override_id"] is not None or row["session_id"] in prior_defaults,
            )
        ledger.reclassify(connection, scopes)
        ledger.refresh_availability(connection, scopes)
        store._advance_revision()
        configuration = projects.configuration(store, connection)
        project = next(p for p in configuration["projects"] if p["id"] == draft["id"])
        result = {
            **configuration,
            **store.revisions(connection),
            "applied": True,
            "project": project,
            "summary": evaluated["summary"],
            "changed_count": evaluated["summary"]["changed_count"],
        }
        connection.execute(
            "INSERT INTO reconciliation_idempotency VALUES(?,?,?)",
            (operation, signature, store._encode(result)),
        )
        connection.execute("DELETE FROM temp.project_binding_selection")
        return result
