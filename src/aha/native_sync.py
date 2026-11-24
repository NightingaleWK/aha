"""Stage confirmed native usage and commit source progress with the ledger facts."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import ExitStack, closing
from datetime import datetime, time
from time import monotonic, perf_counter
from typing import TYPE_CHECKING, Any

from . import ledger
from .codex_sessions import CodexSource, NativeUsage, _timestamp, scan_source
from .domain import (
    BEIJING,
    DETAIL_COST_FIELDS,
    AppError,
    content_hash,
    normalize_price,
    normalize_row,
    parse_date,
    record_key,
    row_fingerprint,
)
from .sync import LOCAL_STAGING_TIMEOUT, _CombinedCancel, _execute, _record_observation

if TYPE_CHECKING:
    from .storage import Store
    from .sync import _Stager

_PROVENANCE_FIELDS = (
    "kind", "timestamp", "thread_id", "turn_id", "response_id", "snapshot_id",
    "snapshot_timestamp", "model_basis", "reasoning_output_tokens", "pending_reason",
)
_SYNC_FIELDS = ("files", "bytes_read", "events", "coverage", "issues", "first_at", "last_at")
_PRICE_FIELDS = {*DETAIL_COST_FIELDS, "pricing_model"}


class NativeBatch:
    def __init__(
        self, store: Store, source_id: str, resources: ExitStack, since: str | None
    ) -> None:
        self.store, self.source_id, self.resources = store, source_id, resources
        self.since = since
        self.since_at = (
            int(datetime.combine(parse_date(since), time.min, BEIJING).timestamp())
            if since is not None else None
        )
        self.first_at: int | None = None
        self.last_at: int | None = None
        self.events = 0
        self.spool: sqlite3.Connection

    def _open_spool(self) -> None:
        spool = self.resources.enter_context(closing(sqlite3.connect("")))
        spool.row_factory = sqlite3.Row
        spool.executescript("""
            CREATE TABLE observed(
                record_key TEXT NOT NULL,content_hash TEXT NOT NULL,payload_json TEXT NOT NULL,
                session_id TEXT,session_json TEXT NOT NULL,event_id TEXT NOT NULL,
                evidence_hash TEXT NOT NULL,pricing_basis TEXT,evidence_json TEXT NOT NULL,
                pending_reason TEXT,
                PRIMARY KEY(record_key,content_hash,evidence_hash));
            CREATE TABLE cursors(path_key TEXT PRIMARY KEY,cursor_json TEXT NOT NULL);
        """)
        self.spool = spool

    def observe(self, event: NativeUsage) -> None:
        row = normalize_row(event.row, "detail")
        timestamp = int(row["created_at"])
        if self.since_at is not None and timestamp < self.since_at:
            return
        if (row["app_type"], row["provider_id"], row["data_source"], row["request_id"]) != (
            "codex", "_codex_session", "codex_native", event.event_id,
        ) or row["session_id"] != event.session.get("session_id"):
            raise AppError("invalid_codex_usage", "原生用量身份不一致，未入账。")
        session = {key: event.session.get(key) for key in ("cwd", "status", "parent_id")}
        evidence = {key: event.evidence[key] for key in _PROVENANCE_FIELDS if key in event.evidence}
        evidence["file_key"] = content_hash(event.relative_path)
        self.events += 1
        if "pending_reason" not in evidence:
            self.first_at = timestamp if self.first_at is None else min(self.first_at, timestamp)
            self.last_at = timestamp if self.last_at is None else max(self.last_at, timestamp)
        if event.price is not None:
            evidence["price"] = normalize_price(event.price)
        evidence_hash = content_hash([evidence, event.pricing_basis])
        self.spool.execute(
            "INSERT INTO observed VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
            (record_key(row), row_fingerprint(row), self.store._encode(row), row["session_id"],
             self.store._encode(session), event.event_id, evidence_hash,
             event.pricing_basis, self.store._encode(evidence), evidence.get("pending_reason")),
        )

    def remember_cursor(self, relative_path: str, cursor: dict[str, Any]) -> None:
        self.spool.execute(
            """INSERT INTO cursors VALUES(?,?) ON CONFLICT(path_key)
            DO UPDATE SET cursor_json=excluded.cursor_json""",
            (content_hash([self.since, relative_path]), self.store._encode(cursor)),
        )

    def read(self, source: CodexSource, stager: _Stager) -> dict[str, Any]:
        self._open_spool()
        started = perf_counter()
        with self.store.read_connection() as reader:
            def load_cursor(relative_path: str) -> dict[str, Any] | None:
                saved = reader.execute(
                    "SELECT cursor_json FROM codex_file_progress WHERE source_id=? AND path_key=?",
                    (self.source_id, content_hash([self.since, relative_path])),
                ).fetchone()
                if saved is None:
                    return None
                decoded = self.store._decode(saved[0])
                if not isinstance(decoded, dict):
                    raise AppError("storage_damaged", "原生读取进度无法读取。", 409)
                return decoded

            result = scan_source(
                source, load_cursor, self.observe, self.remember_cursor,
                cancel=_CombinedCancel(self.store._sync_cancel, stager.cancel),
            )
        stager.timings["source_scan_ms"] = (perf_counter() - started) * 1000
        started = perf_counter()
        stager.processing_deadline = monotonic() + LOCAL_STAGING_TIMEOUT
        for row in self.spool.execute("""
            SELECT payload_json FROM observed WHERE rowid IN
            (SELECT COALESCE(MIN(rowid) FILTER(WHERE pending_reason IS NULL),MIN(rowid))
             FROM observed GROUP BY record_key)
        """):
            stager.add_usage("detail", self.store._decode(row[0]))
        stager.flush()
        stager.check()
        stager.timings["local_staging_ms"] = (perf_counter() - started) * 1000
        stager.processing_deadline = None
        return {**result, "first_at": self.first_at, "last_at": self.last_at, "events": self.events}

    def sessions(self) -> Iterator[tuple[str, dict[str, Any]]]:
        for session_id, payload in self.spool.execute("""
            SELECT session_id,session_json FROM observed WHERE session_id IS NOT NULL
            GROUP BY session_id,session_json ORDER BY MIN(rowid)
        """):
            yield session_id, self.store._decode(payload)

    def coverage(self, observed: dict[str, Any]) -> dict[str, Any]:
        result = {key: observed[key] for key in _SYNC_FIELDS}
        result["since"] = self.since
        prior = self.store._db.execute(
            """SELECT result_json FROM sync_runs WHERE source_id=?
            AND state IN ('completed','needs_review') ORDER BY rowid DESC LIMIT 1""",
            (self.source_id,),
        ).fetchone()
        if prior:
            previous = self.store._decode(prior[0])
            if previous.get("since") == self.since:
                for key, boundary in (("first_at", min), ("last_at", max)):
                    values = [v for v in (previous.get(key), result[key]) if type(v) is int]
                    result[key] = boundary(values) if values else None
        return result

    def check_history(self, payload: dict[str, Any], projection: dict[str, Any]) -> bool:
        db = self.store._db
        key = projection["record_key"]
        info = {
            "date": projection["day"], "model": projection["model"],
            "candidate_summary": ledger.reconciliation_usage_summary(payload),
        }
        observed = self.spool.execute("""
            SELECT pending_reason,evidence_json FROM observed WHERE record_key=?
            ORDER BY pending_reason IS NOT NULL,rowid LIMIT 1
        """, (key,)).fetchone()
        if observed and observed[0] is not None:
            ledger.create_case(
                db, "native_uncertain", "原生日志缺少可核实的用量依据，暂未计入合计。",
                {**info, "pending_reason": observed[0]}, key=key, source_id=self.source_id,
            )
            return True
        legacy = ledger.record_projection({**payload, "data_source": "codex_session"}, "detail")
        alternate = legacy
        if observed:
            evidence = self.store._decode(observed[1])
            snapshot = _timestamp(evidence.get("snapshot_timestamp"))
            if evidence.get("kind") == "response" and snapshot is not None:
                # The paired token_count can straddle a second or local midnight.
                alternate = ledger.record_projection(
                    {**payload, "data_source": "codex_session", "created_at": snapshot[0]}, "detail"
                )
        details = db.execute("""
            SELECT record_key FROM usage_records WHERE semantic_key IN (?,?) AND suppressed=0
            ORDER BY record_key LIMIT 2
        """, (legacy["semantic_key"], alternate["semantic_key"])).fetchall()
        rollup = db.execute("""
            SELECT 1 FROM usage_records WHERE day IN (?,?) AND kind='rollup' AND suppressed=0
            AND (model=? OR pricing_model=?) LIMIT 1
        """, (legacy["day"], alternate["day"], projection["model"],
              projection["pricing_model"])).fetchone()
        # A known legacy session and model can cover earlier events of this day
        # with a different timestamp or provider representation.
        session = db.execute("""
            SELECT 1 FROM usage_records WHERE kind='detail' AND semantic_key IS NOT NULL
            AND session_id=? AND day=? AND model=? AND event_time>=? AND suppressed=0 LIMIT 1
        """, (projection["session_id"], projection["day"], projection["model"],
              projection["event_time"])).fetchone()
        if len(details) == 1 and rollup is None:
            ledger.create_case(
                db, "identity", "原生明细可能与已入账历史重复，请核对消费身份。",
                {**info, "other_record_key": details[0][0]}, key=key, source_id=self.source_id,
            )
        elif details or rollup or session:
            ledger.create_case(
                db, "native_overlap", "原生明细可能属于已入账历史，确认独立消费后才会计入合计。",
                {**info, "pending_reason": "historical_rollup" if rollup else "historical_session"},
                key=key, source_id=self.source_id,
            )
        else:
            return False
        return True

    def check_snapshot_pair(self, row: sqlite3.Row, accepted: sqlite3.Row, run_id: str) -> bool:
        evidence = self.store._decode(row["evidence_json"])
        snapshot = evidence.get("snapshot_id")
        counterpart = {"response": "snapshot", "snapshot": "response"}.get(evidence.get("kind"))
        if not snapshot or counterpart is None:
            return False
        db = self.store._db
        identity = row["record_key"]
        if db.execute("""
            SELECT 1 FROM reconciliation_cases WHERE type IN ('identity','native_overlap')
            AND record_key=? AND state IN ('open','resolved')
            UNION ALL
            SELECT 1 FROM usage_versions v JOIN codex_event_evidence e ON e.version_id=v.id
            WHERE v.record_key=? AND e.run_id!=?
            AND json_extract(e.evidence_json,'$.pending_reason') IS NULL LIMIT 1
        """, (identity, identity, run_id)).fetchone():
            return False
        versions = db.execute("""
            SELECT DISTINCT v.record_key,v.id FROM codex_event_evidence e
            JOIN usage_versions v ON v.id=e.version_id
            WHERE json_extract(e.evidence_json,'$.snapshot_id')=? AND e.event_id!=?
              AND json_extract(e.evidence_json,'$.kind')=?
              AND json_extract(e.evidence_json,'$.pending_reason') IS NULL
        """, (snapshot, row["event_id"], counterpart))
        matches: list[str] = []
        for raw_key, version in versions:
            logical_key = ledger.canonical_record_key(db, raw_key)
            if db.execute("""
                SELECT 1 FROM usage_records r
                WHERE r.record_key=? AND r.version_id=? AND r.session_id=? AND r.suppressed=0
                  AND NOT EXISTS(SELECT 1 FROM reconciliation_cases c
                      WHERE c.record_key=r.record_key AND c.state='open')
            """, (logical_key, version, accepted["session_id"])).fetchone():
                matches.append(logical_key)
                if len(matches) == 2:
                    break
        info = {"date": accepted["day"], "model": accepted["model"]}
        if len(matches) == 1:
            ledger.create_case(
                db, "identity", "不同日志格式可能记录了同一次模型调用，请核对。",
                {**info, "other_record_key": matches[0], "native_snapshot_pair": True},
                key=identity, source_id=self.source_id,
            )
        elif matches:
            ledger.create_case(
                db, "native_overlap", "这条原生日志存在多个用量候选，请核对。",
                {**info, "pending_reason": "ambiguous_snapshot", "candidate_summary":
                 ledger.reconciliation_usage_summary(self.store._decode(row["payload_json"]))},
                key=identity, source_id=self.source_id,
            )
        else:
            return False
        return True

    def publish(self, stager: _Stager, scopes: set[str], counts: dict[str, int]) -> bool:
        db = self.store._db
        has_aliases = db.execute("SELECT 1 FROM record_aliases LIMIT 1").fetchone() is not None
        changed_cases = False
        for row in self.spool.execute("""
            SELECT * FROM observed ORDER BY record_key,pending_reason IS NOT NULL,rowid
        """):
            stager.check()
            version = _record_observation(self.store, stager.run_id, self.source_id, row)
            db.execute(
                "INSERT INTO codex_event_evidence VALUES(?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
                (version, self.source_id, row["evidence_hash"], row["event_id"],
                 stager.run_id, row["pricing_basis"], row["evidence_json"]),
            )
            raw_key = row["record_key"]
            key = ledger.canonical_record_key(db, raw_key) if has_aliases else raw_key
            # A suppressed alias participates in native revision checks only when
            # its native event is the accepted fact at the logical history key.
            accepted = db.execute("""
                SELECT r.*,v.payload_json FROM usage_records r
                JOIN usage_versions v ON v.id=r.version_id WHERE r.record_key=? AND r.suppressed=0
                AND (r.record_key=? OR v.record_key=?)
            """, (key, raw_key, raw_key)).fetchone()
            if accepted is None or row["pending_reason"] is not None:
                continue
            uncertain = db.execute("""
                UPDATE reconciliation_cases SET state='verified',generation=generation+1
                WHERE type='native_uncertain' AND record_key=? AND state='open'
            """, (key,)).rowcount
            if uncertain:
                scope, old_scope = ledger.set_current(db, version, logical_key=key)
                scopes.update(value for value in (scope, old_scope) if value)
                projected = self.store._decode(row["payload_json"])
                if self.check_history(projected, ledger.record_projection(projected, "detail")):
                    counts["pending_count"] += 1
                elif self.check_snapshot_pair(row, accepted, stager.run_id):
                    counts["pending_count"] += 1
                counts["revised_count"] += 1
                changed_cases = True
                continue
            if accepted["content_hash"] == row["content_hash"]:
                if self.check_snapshot_pair(row, accepted, stager.run_id):
                    counts["pending_count"] += 1
                    changed_cases = True
                    scopes.add(accepted["scope_key"])
                continue
            original = self.store._decode(accepted["payload_json"])
            candidate = self.store._decode(row["payload_json"])
            if all(original.get(field) == value for field, value in candidate.items()
                   if field not in _PRICE_FIELDS):
                continue
            existing = db.execute("""
                SELECT state FROM reconciliation_cases WHERE type='revision' AND record_key=?
                AND json_extract(info_json,'$.candidate_hash')=? LIMIT 1
            """, (key, row["content_hash"])).fetchone()
            if existing is None:
                ledger.create_case(
                    db, "revision", "同一原生事件包含不同用量依据，请核对后采用。",
                    {"candidate_version_id": version, "candidate_hash": row["content_hash"],
                     "current_version_id": accepted["version_id"], "date": accepted["day"],
                     "model": accepted["model"], "current_cost_usd": accepted["total_cost_usd"],
                     "candidate_cost_usd": candidate["total_cost_usd"]},
                    key=key, source_id=self.source_id,
                )
                changed_cases = True
                scopes.add(accepted["scope_key"])
            if existing is None or existing[0] == "open":
                counts["pending_count"] += 1
        db.executemany(
            """INSERT INTO codex_file_progress VALUES(?,?,?) ON CONFLICT(source_id,path_key)
            DO UPDATE SET cursor_json=excluded.cursor_json
            WHERE cursor_json!=excluded.cursor_json""",
            ((self.source_id, path_key, cursor) for path_key, cursor in self.spool.execute(
                "SELECT path_key,cursor_json FROM cursors"
            )),
        )
        return changed_cases


def sync_codex(
    store: Store,
    source: CodexSource,
    source_id: str,
    *,
    trigger: str,
    startup_id: str | None,
    cancel: threading.Event | None,
    since: str | None,
) -> dict[str, Any]:
    name = "Windows Codex" if source.kind == "windows" else "WSL Codex"
    descriptor = {"kind": "codex_" + source.kind, "name": name}
    with ExitStack() as resources:
        batch = NativeBatch(store, source_id, resources, since)
        return _execute(
            store, descriptor, lambda stager: batch.read(source, stager), None,
            source_id=source_id, trust="live", trigger=trigger, startup_id=startup_id,
            cancel=cancel, native=batch,
        )
