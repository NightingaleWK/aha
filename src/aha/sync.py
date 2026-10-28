"""Finite explicit source runs: stage allowed rows, then atomically publish differences."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from time import monotonic, perf_counter
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from . import ledger, session_meta, sources
from .domain import (
    MAX_ROWS,
    AppError,
    content_hash,
    normalize_row,
    record_key,
    row_fingerprint,
    source_name,
)

if TYPE_CHECKING:
    from .storage import Store


def sync_status(store: Store, run_id: str | None = None) -> dict[str, Any] | None:
    with store.read_connection() as connection:
        row = connection.execute(
            (
                "SELECT r.*,s.kind,s.name FROM sync_runs r LEFT JOIN source_profi"
                "les s ON s.id=r.source_id "
            )
            + ("WHERE r.id=?" if run_id else "ORDER BY r.rowid DESC LIMIT 1"),
            (run_id,) if run_id else (),
        ).fetchone()
        return _descriptor(store, row) if row else None


def _descriptor(store: Store, row: sqlite3.Row) -> dict[str, Any]:
    return {
        **store._decode(row["result_json"]),
        "id": row["id"],
        "run_id": row["id"],
        "state": row["state"],
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
        "source_id": row["source_id"],
        "source": {"kind": row["kind"], "name": row["name"]},
        "error_code": row["error_code"],
        "error_message": row["error_message"],
        "data_revision": row["data_revision"],
    }


def _begin(
    store: Store,
    source: dict[str, Any],
    trust: str,
    source_id: str | None,
    trigger: str,
    startup_id: str | None,
) -> tuple[str, str, dict[str, Any] | None]:
    if trust not in {"live", "backup", "history"} or trigger not in {
        "startup",
        "manual",
        "import",
        "history",
    }:
        raise AppError("invalid_sync", "同步来源或触发方式无效。")
    identity = source_id or content_hash(
        [source.get("kind", "history"), source.get("location") or source.get("name", "历史用量")]
    )
    with store._transaction():
        connection = store._db
        if startup_id:
            prior = connection.execute(
                (
                    "SELECT r.*,s.kind,s.name FROM sync_runs r JOIN source_profiles s"
                    " ON s.id=r.source_id WHERE startup_id=?"
                ),
                (startup_id,),
            ).fetchone()
            if prior:
                return prior["id"], identity, _descriptor(store, prior)
        # A crashed process never grants a second writer until the finite lease expires.
        connection.execute(
            (
                "UPDATE sync_runs SET state='failed',completed_at=?,error_code='s"
                "ync_interrupted',error_message='上次同步中断，未发布暂存资料。' WHERE state='ru"
                "nning' AND julianday(heartbeat_at)<julianday('now')-120.0/86400"
            ),
            (store._now(),),
        )
        active = connection.execute("SELECT id FROM sync_runs WHERE state='running'").fetchone()
        if active:
            raise AppError("sync_in_progress", "另一个窗口正在同步，请等待当前同步完成。", 409)
        connection.execute(
            (
                "INSERT INTO source_profiles(id,kind,name,location,trust,created_"
                "at) VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING"
            ),
            (
                identity,
                source.get("kind", "history"),
                source_name(str(source.get("name", "历史用量"))),
                source.get("location"),
                trust,
                store._now(),
            ),
        )
        source_profile = connection.execute(
            "SELECT * FROM source_profiles WHERE id=?", (identity,)
        ).fetchone()
        if source_profile["kind"] != source.get("kind", "history"):
            raise AppError("source_conflict", "来源身份与所选来源不一致，请重新选择。", 409)
        run_id = str(uuid4())
        connection.execute(
            (
                "INSERT INTO sync_runs(id,source_id,state,trigger,startup_id,star"
                "ted_at,heartbeat_at) VALUES(?,?,'running',?,?,?,?)"
            ),
            (run_id, identity, trigger, startup_id, store._now(), store._now()),
        )
        return run_id, identity, None


class _Stager:
    def __init__(self, store: Store, run_id: str, cancel: threading.Event | None) -> None:
        self.store, self.run_id, self.cancel = store, run_id, cancel
        self.rows: list[tuple[str, str, str, str, str]] = []
        self.prices: list[tuple[str, str, str]] = []
        self.counts = {"detail": 0, "rollup": 0, "pricing": 0}
        self.timings: dict[str, float] = {}
        self.source_deadline: float | None = None

    def check(self) -> None:
        if self.store._sync_cancel.is_set() or (self.cancel and self.cancel.is_set()):
            raise AppError("sync_cancelled", "同步已取消。", 409)
        if self.source_deadline is not None and monotonic() > self.source_deadline:
            raise AppError("source_busy", "来源读取超过时限，请稍后重试。", 409)

    def add(self, table: str, row: dict[str, Any]) -> None:
        self.check()
        kind = {
            "proxy_request_logs": "detail",
            "usage_daily_rollups": "rollup",
            "model_pricing": "pricing",
        }[table]
        if kind != "pricing":
            if (
                row.get("app_type") != "codex"
                or (kind == "detail" and row.get("data_source") != "codex_session")
                or (kind == "rollup" and row.get("provider_id") != "_codex_session")
            ):
                return
            normalized = normalize_row(row, kind)
            self.rows.append(
                (
                    self.run_id,
                    record_key(normalized, kind),
                    kind,
                    row_fingerprint(normalized, kind),
                    self.store._encode(normalized),
                )
            )
        else:
            from .domain import normalize_price
            price = normalize_price(row)
            self.prices.append((self.run_id, price["model_id"], self.store._encode(price)))
        self.counts[kind] += 1
        if self.counts[kind] > MAX_ROWS:
            raise AppError("source_too_large", "单次来源记录超过上限。", 413)
        if len(self.rows) + len(self.prices) >= 512:
            self.flush()

    def flush(self) -> None:
        self.check()
        if not self.rows and not self.prices:
            return
        try:
            with self.store._staging_transaction(self.check, self.source_deadline):
                self.store._db.executemany("INSERT INTO sync_stage VALUES(?,?,?,?,?)", self.rows)
                self.store._db.executemany("INSERT INTO sync_pricing VALUES(?,?,?)", self.prices)
                self.store._db.execute(
                    "UPDATE sync_runs SET heartbeat_at=? WHERE id=? AND state='running'",
                    (self.store._now(), self.run_id),
                )
        except AppError as exc:
            if isinstance(exc.__cause__, sqlite3.IntegrityError):
                raise AppError("duplicate_key", "来源存在重复用量或价格主键，未导入。") from exc
            raise
        self.rows.clear()
        self.prices.clear()


def _failed(store: Store, run_id: str, error: AppError) -> None:
    with suppress(AppError, sqlite3.Error):
        with store._transaction():
            store._db.execute("DELETE FROM sync_stage WHERE run_id=?", (run_id,))
            store._db.execute("DELETE FROM sync_pricing WHERE run_id=?", (run_id,))
            store._db.execute(
                (
                    "UPDATE sync_runs SET state='failed',completed_at=?,error_code=?,"
                    "error_message=? WHERE id=? AND state='running'"
                ),
                (store._now(), error.code, error.message, run_id),
            )


def _metadata(store: Store, run_id: str, roots: list[Path] | None) -> dict[str, Any]:
    if roots is None:
        return {"sessions": {}}
    with store.read_connection() as connection:
        wanted = {
            row[0]
            for row in connection.execute(
                (
                    "SELECT DISTINCT json_extract(t.payload_json,'$.session_id') FROM"
                    " sync_stage t LEFT JOIN sessions s ON s.id=json_extract(t.payloa"
                    "d_json,'$.session_id') WHERE t.run_id=? AND t.kind='detail' AND "
                    "json_extract(t.payload_json,'$.session_id') IS NOT NULL AND (s.i"
                    "d IS NULL OR s.status!='matched') LIMIT ?"
                ),
                (run_id, session_meta.MAX_SESSIONS + 1),
            )
        }
    limited = len(wanted) > session_meta.MAX_SESSIONS
    wanted = set(sorted(wanted)[: session_meta.MAX_SESSIONS])
    result = session_meta.scan_metadata(wanted, roots, cancel=store._sync_cancel)
    if limited:
        result["errors"].append({"code": "metadata_selection_limit", "count": 1})
    return result


def _save_metadata(store: Store, metadata: dict[str, Any], trust: str) -> set[str]:
    connection = store._db
    changed: set[str] = set()
    for session_id, entry in metadata.get("sessions", {}).items():
        status = entry.get("status", "missing")
        cwd = entry.get("cwd") if status == "matched" else None
        if status not in {"matched", "missing", "conflict"} or (
            cwd is not None and (not isinstance(cwd, str) or len(cwd) > 8192)
        ):
            raise AppError("invalid_metadata", "目录依据结构无效。")
        safe = {"cwd": cwd, "status": status, "parent_id": entry.get("parent_id")}
        old = connection.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        if old and old["cwd"] and cwd and old["cwd"] != cwd and trust != "live":
            safe = {"cwd": None, "status": "conflict", "parent_id": None}
        fingerprint = content_hash(safe)
        if old:
            connection.execute(
                "UPDATE sessions SET last_checked=? WHERE id=?", (store._now(), session_id)
            )
        if old and old["content_hash"] == fingerprint:
            continue
        connection.execute(
            (
                "INSERT INTO session_metadata_versions(session_id,content_hash,pa"
                "yload_json,created_at) VALUES(?,?,?,?) ON CONFLICT(session_id,co"
                "ntent_hash) DO NOTHING"
            ),
            (session_id, fingerprint, store._encode(safe), store._now()),
        )
        connection.execute(
            (
                "INSERT INTO sessions(id,cwd,status,parent_id,content_hash) VALUE"
                "S(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET cwd=excluded.cwd,stat"
                "us=excluded.status,parent_id=excluded.parent_id,content_hash=exc"
                "luded.content_hash"
            ),
            (session_id, safe["cwd"], safe["status"], safe["parent_id"], fingerprint),
        )
        changed.add(session_id)
    return changed


def _publish(
    store: Store,
    run_id: str,
    source_id: str,
    trust: str,
    stager: _Stager,
    metadata: dict[str, Any],
    source: dict[str, Any],
) -> dict[str, Any]:
    stager.flush()
    publishing_started = perf_counter()
    counts = {"new_count": 0, "revised_count": 0, "unchanged_count": 0, "pending_count": 0}
    with store._transaction():
        connection = store._db
        stager.check()
        scopes: set[str] = set()
        groups: set[str] = set()
        cases_changed = False
        pricing_changed = False
        active_run = connection.execute(
            "SELECT state FROM sync_runs WHERE id=?", (run_id,)
        ).fetchone()
        if active_run is None or active_run[0] != "running":
            raise AppError("sync_interrupted", "同步租约已失效，未发布暂存数据。", 409)
        previous = connection.execute(
            """SELECT r.result_json FROM sync_runs r WHERE r.source_id=? AND
            (r.state='completed' OR EXISTS(SELECT 1 FROM source_epochs e
            WHERE e.id=r.id AND e.state='confirmed')) ORDER BY r.rowid DESC LIMIT 1""",
            (source_id,),
        ).fetchone()
        prior = store._decode(previous[0]).get("observed", {}) if previous else {}
        detail_shrinking = bool(
            prior
            and stager.counts["detail"] * 2 < prior.get("detail", 0)
            and stager.counts["rollup"] <= prior.get("rollup", 0)
        )
        rollup_shrinking = bool(prior and stager.counts["rollup"] < prior.get("rollup", 0))
        represented_shrinking = connection.execute(
            """SELECT 1 FROM sync_stage t
            LEFT JOIN source_rollup_observations b ON b.source_id=? AND b.record_key=t.record_key
            LEFT JOIN usage_records r ON r.record_key=t.record_key
            LEFT JOIN usage_versions v ON v.id=r.version_id
            WHERE t.run_id=? AND t.kind='rollup' AND
            CAST(json_extract(t.payload_json,'$.request_count') AS INTEGER)<
            CAST(COALESCE(b.request_count,CASE WHEN v.source_id=? THEN r.request_count END)
            AS INTEGER) LIMIT 1""",
            (source_id, run_id, source_id),
        ).fetchone() is not None
        shrinking = detail_shrinking or rollup_shrinking or represented_shrinking
        if shrinking:
            before_cases = connection.total_changes
            ledger.create_case(
                connection,
                "source",
                "来源可能正在分批重建或已被替换；本地历史保留，请核对来源。",
                {"observed": stager.counts, "previous": prior,
                 "rollup_request_count_regressed": represented_shrinking},
                source_id=source_id,
                reopen=True,
            )
            counts["pending_count"] += 1
            cases_changed |= connection.total_changes != before_cases
            scopes.update(
                r[0]
                for r in connection.execute(
                    (
                        "SELECT DISTINCT r.scope_key FROM usage_records r JOIN usage_vers"
                        "ions v ON v.id=r.version_id WHERE v.source_id=?"
                    ),
                    (source_id,),
                )
            )
        for price in connection.execute("SELECT * FROM sync_pricing WHERE run_id=?", (run_id,)):
            previous_price = connection.execute(
                "SELECT payload_json FROM pricing WHERE model_id=?", (price["model_id"],)
            ).fetchone()
            if previous_price is None or (
                trust == "live" and previous_price[0] != price["payload_json"]
            ):
                pricing_changed = True
                connection.execute(
                    (
                        "INSERT INTO pricing(model_id,payload_json) VALUES(?,?) ON CONFLI"
                        "CT(model_id) DO UPDATE SET payload_json=excluded.payload_json"
                    ),
                    (price["model_id"], price["payload_json"]),
                )
                scopes.update(
                    r[0]
                    for r in connection.execute(
                        "SELECT DISTINCT scope_key FROM usage_records WHERE pricing_model=?",
                        (price["model_id"],),
                    )
                )
        cursor = connection.execute(
            "SELECT * FROM sync_stage WHERE run_id=? ORDER BY record_key", (run_id,)
        )
        has_aliases = (
            connection.execute("SELECT 1 FROM record_aliases LIMIT 1").fetchone() is not None
        )
        while rows := cursor.fetchmany(512):
            stager.check()
            for row in rows:
                logical_key = (
                    ledger.canonical_record_key(connection, row["record_key"])
                    if has_aliases
                    else row["record_key"]
                )
                current = connection.execute(
                    (
                        "SELECT r.*,s.trust AS current_trust,v.source_id AS current_sourc"
                        "e FROM usage_records r JOIN usage_versions v ON v.id=r.version_i"
                        "d JOIN source_profiles s ON s.id=v.source_id WHERE r.record_key="
                        "?"
                    ),
                    (logical_key,),
                ).fetchone()
                if current and current["content_hash"] == row["content_hash"]:
                    connection.execute(
                        "INSERT INTO record_evidence VALUES(?,?,?) ON CONFLICT DO NOTHING",
                        (current["version_id"], source_id, run_id),
                    )
                    counts["unchanged_count"] += 1
                    continue
                connection.execute(
                    (
                        "INSERT INTO usage_versions(record_key,content_hash,payload_json,"
                        "created_at,source_id) VALUES(?,?,?,?,?) ON CONFLICT(record_key,c"
                        "ontent_hash) DO NOTHING"
                    ),
                    (
                        row["record_key"],
                        row["content_hash"],
                        row["payload_json"],
                        store._now(),
                        source_id,
                    ),
                )
                version = connection.execute(
                    "SELECT id FROM usage_versions WHERE record_key=? AND content_hash=?",
                    (row["record_key"], row["content_hash"]),
                ).fetchone()[0]
                connection.execute(
                    (
                        "INSERT INTO record_evidence VALUES(?,?,?) ON CONFLICT(version_id"
                        ",source_id) DO NOTHING"
                    ),
                    (version, source_id, run_id),
                )
                if current and logical_key != row["record_key"]:
                    candidate = json.loads(row["payload_json"])
                    accepted = json.loads(connection.execute(
                        "SELECT payload_json FROM usage_versions WHERE id=?",
                        (current["version_id"],),
                    ).fetchone()[0])
                    candidate.pop("request_id", None)
                    accepted.pop("request_id", None)
                    if candidate == accepted:
                        counts["unchanged_count"] += 1
                        continue
                if current and (
                    trust != "live"
                    or shrinking
                    or (
                        current["current_trust"] == "live"
                        and current["current_source"] != source_id
                    )
                ):
                    candidate = json.loads(row["payload_json"])
                    before_cases = connection.total_changes
                    ledger.create_case(
                        connection,
                        "revision",
                        "来源记录有不同版本，无法仅按导入时间确定新旧。",
                        {
                            "candidate_version_id": version,
                            "candidate_hash": row["content_hash"],
                            "current_version_id": current["version_id"],
                            "date": current["day"],
                            "model": current["model"],
                            "current_cost_usd": current["total_cost_usd"],
                            "candidate_cost_usd": candidate["total_cost_usd"],
                        },
                        key=logical_key,
                        source_id=source_id,
                    )
                    scopes.add(current["scope_key"])
                    counts["pending_count"] += 1
                    cases_changed |= connection.total_changes != before_cases
                    continue
                new_scope, old_scope = ledger.set_current(
                    connection, version, logical_key=logical_key
                )
                scopes.add(new_scope)
                if old_scope:
                    scopes.add(old_scope)
                    groups.add(current["coverage_key"])
                payload = json.loads(row["payload_json"])
                if payload.get("session_id"):
                    missing = {"cwd": None, "status": "missing", "parent_id": None}
                    connection.execute(
                        (
                            "INSERT INTO sessions(id,cwd,status,parent_id,content_hash) VALUE"
                            "S(?,NULL,'missing',NULL,?) ON CONFLICT(id) DO NOTHING"
                        ),
                        (payload["session_id"], content_hash(missing)),
                    )
                projection = ledger.record_projection(json.loads(row["payload_json"]), row["kind"])
                groups.add(projection["coverage_key"])
                counts["revised_count" if current else "new_count"] += 1
                connection.execute(
                    (
                        "UPDATE reconciliation_cases SET state='verified',generation=gene"
                        "ration+1 WHERE type='revision' AND record_key=? AND state='open'"
                        " AND json_extract(info_json,'$.candidate_version_id')=?"
                    ),
                    (logical_key, version),
                )
                if not current and projection["semantic_key"]:
                    other = connection.execute(
                        (
                            "SELECT r.record_key,v.source_id FROM usage_records r JOIN usage_"
                            "versions v ON v.id=r.version_id WHERE r.semantic_key=? AND r.rec"
                            "ord_key!=? AND (v.source_id!=? OR NOT EXISTS(SELECT 1 FROM "
                            "sync_stage observed WHERE observed.run_id=? AND "
                            "observed.record_key=r.record_key)) AND NOT EXISTS(SELECT 1 FROM "
                            "record_aliases a WHERE a.alias_key=r.record_key) LIMIT 1"
                        ),
                        (projection["semantic_key"], row["record_key"], source_id, run_id),
                    ).fetchone()
                    if other:
                        before_cases = connection.total_changes
                        ledger.create_case(
                            connection,
                            "identity",
                            "不同来源标识的用量可能来自会话重建，请先核对。",
                            {
                                "date": projection["day"],
                                "model": projection["model"],
                                "other_record_key": other["record_key"],
                            },
                            key=row["record_key"],
                            source_id=source_id,
                        )
                        counts["pending_count"] += 1
                        cases_changed |= connection.total_changes != before_cases
        compared_at = perf_counter()
        stager.timings["compare_current_versions_ms"] = (compared_at - publishing_started) * 1000
        scopes |= ledger.update_coverage(connection, groups)
        changed_sessions = _save_metadata(store, metadata, trust)
        for session_id in changed_sessions:
            scopes.update(
                r[0]
                for r in connection.execute(
                    "SELECT DISTINCT scope_key FROM usage_records WHERE session_id=?", (session_id,)
                )
            )
        if scopes:
            ledger.reclassify(connection, scopes)
            ledger._scope_table(connection, scopes)
            connection.execute("""UPDATE usage_records AS r SET pricing_status=CASE WHEN EXISTS(
                SELECT 1 FROM pricing p WHERE p.model_id=r.pricing_model AND (
                    json_extract(p.payload_json,'$.input_cost_per_million')!='0' OR
                    json_extract(p.payload_json,'$.output_cost_per_million')!='0' OR
                    json_extract(p.payload_json,'$.cache_read_cost_per_million')!='0' OR
                    json_extract(p.payload_json,'$.cache_creation_cost_per_million')!='0'))
                THEN 'available' WHEN r.total_cost_usd='0' THEN 'unpriced' ELSE 'missing_basis' END
                WHERE scope_key IN (SELECT scope_key FROM temp.work_scopes)""")
            ledger.refresh_availability(connection, scopes)
        stager.timings["derived_refresh_ms"] = (perf_counter() - compared_at) * 1000
        if (
            counts["new_count"]
            or counts["revised_count"]
            or cases_changed
            or changed_sessions
            or pricing_changed
        ):
            connection.execute(
                "UPDATE settings SET value=CAST(value AS INTEGER)+1 WHERE key='data_revision'"
            )
        result = {
            **counts,
            "observed": dict(stager.counts),
            "source_fingerprint": source.get("fingerprint"),
            "metadata_errors": metadata.get("errors", []),
            "timings_ms": stager.timings,
        }
        stager.check()
        stager.timings["publish_before_commit_ms"] = (
            perf_counter() - publishing_started
        ) * 1000
        needs_review = connection.execute(
            """SELECT 1 FROM reconciliation_cases
            WHERE type='source' AND source_id=? AND state='open' LIMIT 1""",
            (source_id,),
        ).fetchone() is not None
        connection.execute(
            """INSERT INTO source_rollup_observations(source_id,record_key,request_count)
            SELECT ?,record_key,CAST(json_extract(payload_json,'$.request_count') AS TEXT)
            FROM sync_stage WHERE run_id=? AND kind='rollup'
            ON CONFLICT(source_id,record_key) DO UPDATE SET request_count=excluded.request_count
            WHERE source_rollup_observations.request_count!=excluded.request_count""",
            (source_id, run_id),
        )
        connection.execute(
            """UPDATE sync_runs SET state=?,completed_at=?,heartbeat_at=?,
            result_json=?,data_revision=? WHERE id=? AND state='running'""",
            (
                "needs_review" if needs_review else "completed",
                store._now(),
                store._now(),
                store._encode(result),
                store.revisions(connection)["data_revision"],
                run_id,
            ),
        )
        connection.execute(
            "UPDATE source_profiles SET last_run_id=? WHERE id=?", (run_id, source_id)
        )
        connection.execute("DELETE FROM sync_stage WHERE run_id=?", (run_id,))
        connection.execute("DELETE FROM sync_pricing WHERE run_id=?", (run_id,))
    completed = sync_status(store, run_id)
    assert completed is not None
    return completed


def _execute(
    store: Store,
    source: dict[str, Any],
    read: Callable[[_Stager], dict[str, Any]],
    metadata: dict[str, Any] | None,
    roots: list[Path] | None,
    *,
    source_id: str | None,
    trust: str,
    trigger: str,
    startup_id: str | None,
    cancel: threading.Event | None,
) -> dict[str, Any]:
    run_id, identity, existing = _begin(store, source, trust, source_id, trigger, startup_id)
    if existing:
        return existing
    stager = _Stager(store, run_id, cancel)
    try:
        projection_started = perf_counter()
        observed = read(stager)
        stager.flush()
        stager.timings["source_projection_and_staging_ms"] = (
            perf_counter() - projection_started
        ) * 1000
        metadata_started = perf_counter()
        meta = metadata if metadata is not None else _metadata(store, run_id, roots)
        stager.timings["metadata_ms"] = (perf_counter() - metadata_started) * 1000
        return _publish(store, run_id, identity, trust, stager, meta, observed)
    except AppError as exc:
        _failed(store, run_id, exc)
        raise
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        error = AppError("sync_failed", "同步未完成，原本地数据保持不变，请重试。", 500)
        _failed(store, run_id, error)
        raise error from exc


def sync_data(
    store: Store,
    data: dict[str, Any],
    metadata: dict[str, Any] | None = None,
    *,
    source_id: str | None = None,
    trust: str = "backup",
    trigger: str = "manual",
    startup_id: str | None = None,
    cancel: threading.Event | None = None,
) -> dict[str, Any]:
    if data.get("schema_version") != 23:
        raise AppError("unsupported_schema", "仅支持结构版本 23 的用量来源。")
    source = {"kind": "history", "name": "历史用量", **data.get("source", {})}

    def read(stager: _Stager) -> dict[str, Any]:
        for key, table in (
            ("details", "proxy_request_logs"),
            ("rollups", "usage_daily_rollups"),
            ("pricing", "model_pricing"),
        ):
            for row in data.get(key, []):
                stager.add(table, row)
        return source

    return _execute(
        store,
        source,
        read,
        metadata,
        None,
        source_id=source_id,
        trust=trust,
        trigger=trigger,
        startup_id=startup_id,
        cancel=cancel,
    )


def sync_sql(
    store: Store,
    data: bytes,
    name: str,
    metadata_roots: list[Path] | None = None,
    *,
    source_id: str | None = None,
    trigger: str = "import",
    cancel: threading.Event | None = None,
) -> dict[str, Any]:
    from .sql_dump import scan_sql_dump

    source = {"kind": "sql", "name": source_name(name)}
    return _execute(
        store,
        source,
        lambda stager: scan_sql_dump(data, name, stager.add),
        None,
        metadata_roots,
        source_id=source_id,
        trust="backup",
        trigger=trigger,
        startup_id=None,
        cancel=cancel,
    )


def sync_sqlite(
    store: Store,
    path: Path,
    metadata_roots: list[Path] | None = None,
    *,
    trigger: str = "manual",
    startup_id: str | None = None,
    cancel: threading.Event | None = None,
) -> dict[str, Any]:
    path = Path(path)
    source = {"kind": "sqlite", "name": source_name(str(path)), "location": str(path.resolve())}

    def read(stager: _Stager) -> dict[str, Any]:
        stager.source_deadline = monotonic() + sources.SNAPSHOT_TIMEOUT
        try:
            return sources.scan_sqlite(path, stager.add, cancel=cancel or store._sync_cancel)
        finally:
            stager.source_deadline = None

    return _execute(
        store,
        source,
        read,
        None,
        metadata_roots,
        source_id=None,
        trust="live",
        trigger=trigger,
        startup_id=startup_id,
        cancel=cancel,
    )


def refresh_metadata(store: Store, roots: list[Path]) -> dict[str, Any]:
    with store.read_connection() as connection:
        wanted = {
            row[0]
            for row in connection.execute(
                "SELECT id FROM sessions ORDER BY last_checked,id LIMIT ?",
                (session_meta.MAX_SESSIONS,),
            )
        }
    metadata = session_meta.scan_metadata(wanted, roots, cancel=store._sync_cancel)
    with store._transaction():
        changed = _save_metadata(store, metadata, "live")
        scopes: set[str] = set()
        for session_id in changed:
            scopes.update(
                row[0]
                for row in store._db.execute(
                    "SELECT DISTINCT scope_key FROM usage_records WHERE session_id=?", (session_id,)
                )
            )
        ledger.reclassify(store._db, scopes)
        ledger.refresh_availability(store._db, scopes)
        if changed:
            store._advance_revision()
    return store.ledger_status()
