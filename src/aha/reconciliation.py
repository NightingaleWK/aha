"""Filtered review queues and atomic confirmation of matched historical usage."""

from __future__ import annotations

import json
import re
import sqlite3
from typing import TYPE_CHECKING, Any

from . import claims, ledger
from .codex_sessions import _timestamp
from .decimal_sql import DecimalSum
from .domain import AppError, content_hash, parse_date

if TYPE_CHECKING:
    from .storage import Store

FILTER_FIELDS = {"type", "source_id", "start_date", "end_date", "eligibility"}
_CASE_TYPES = {
    "revision", "directory", "identity", "native_overlap", "native_uncertain", "source",
}
_DATE = "COALESCE(NULLIF(json_extract(c.info_json,'$.date'),''),r.day)"
_DIGEST = re.compile(r"[0-9a-f]{64}")
_SAFE_CASE_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
_BATCH_POLICY = "prefer_verified_native_reference_cost_v1"
_SAME_COST = """(
    n.total_cost_usd=h.total_cost_usd OR
    CASE WHEN instr(n.total_cost_usd,'.') THEN rtrim(rtrim(n.total_cost_usd,'0'),'.')
         ELSE n.total_cost_usd END =
    CASE WHEN instr(h.total_cost_usd,'.') THEN rtrim(rtrim(h.total_cost_usd,'0'),'.')
         ELSE h.total_cost_usd END
)"""


_MATCH_FIELDS = (
    "session_id", "model", "request_count", "fresh_input_tokens", "output_tokens",
    "cache_read_tokens", "cache_creation_tokens",
)
_ARCHIVED_NATIVE_OVERLAP = claims.archived_claim_lookup(
    "n.day", "n.model", "n.pricing_model", "n.version_id"
)


def _match_fields(alias: str) -> str:
    return ",".join(f"{alias}.{field}" for field in _MATCH_FIELDS)


def _evidence_stamp(value: object) -> str | None:
    stamp = _timestamp(value)
    return stamp[1] if stamp else None


# History stores second-resolution usage without a native response ID. Its clock
# may match either the native event or the exact snapshot paired by the parser.
# Resolve all matching current facts together, including independently accepted
# native events and alternate clocks observed outside the active case filters.
_MATCH_CASES = f"""
, competing_history AS MATERIALIZED (
    SELECT json_extract(info_json,'$.other_record_key') AS record_key
    FROM reconciliation_cases
    WHERE state='open' AND type='identity'
      AND json_extract(info_json,'$.other_record_key') IS NOT NULL
    GROUP BY record_key HAVING COUNT(*)>1
), blocking_sources AS MATERIALIZED (
    SELECT DISTINCT source_id FROM reconciliation_cases
    WHERE type='source' AND state='open' AND source_id IS NOT NULL
), aliased AS MATERIALIZED (
    SELECT alias_key AS record_key FROM record_aliases
    UNION SELECT canonical_key FROM record_aliases
), potential AS MATERIALIZED (
    SELECT c.id,n.record_key,h.record_key AS history_key,n.version_id AS candidate_version,
           h.version_id AS history_version,n.event_time AS native_second,n.day AS native_day,
           h.event_time AS history_second,h.day AS history_day,{_match_fields("n")},
           json_extract(nv.payload_json,'$.request_id') AS event_id,
           json_extract(hv.payload_json,'$.app_type') AS app_type,
           json_extract(hv.payload_json,'$.provider_id') AS provider_id,
           NOT {_SAME_COST} AS adopt_candidate,
           h.total_cost_usd AS current_cost_usd,n.total_cost_usd AS candidate_cost_usd
    FROM open_cases c
    CROSS JOIN usage_records n ON n.record_key=c.record_key
    CROSS JOIN usage_records h ON h.record_key=c.history_key
    JOIN usage_versions nv ON nv.id=n.version_id AND nv.record_key=n.record_key
    JOIN usage_versions hv ON hv.id=h.version_id AND hv.record_key=h.record_key
    WHERE c.type='identity' AND n.kind='detail' AND h.kind='detail'
      AND n.suppressed=0 AND h.suppressed=0
      AND n.semantic_key IS NULL AND h.semantic_key IS NOT NULL AND n.session_id!=''
      AND ({_match_fields("n")})=({_match_fields("h")})
      AND ({_SAME_COST} OR (
          h.availability_state='available'
          AND NOT EXISTS (SELECT 1 FROM usage_claims u WHERE u.record_key=h.record_key)
          AND NOT EXISTS (SELECT 1 FROM usage_claims u WHERE u.semantic_key=h.semantic_key)
          AND NOT EXISTS ({_ARCHIVED_NATIVE_OVERLAP})
          AND NOT EXISTS (
              SELECT 1 FROM reconciliation_cases other
              WHERE other.coverage_key IN (h.coverage_key,n.coverage_key) AND other.state='open'
          )
          AND nv.source_id NOT IN (SELECT source_id FROM blocking_sources)
      ))
      AND json_extract(nv.payload_json,'$.data_source')='codex_native'
      AND json_extract(hv.payload_json,'$.data_source')='codex_session'
      AND json_extract(nv.payload_json,'$.app_type')=json_extract(hv.payload_json,'$.app_type')
      AND json_extract(nv.payload_json,'$.provider_id')=
          json_extract(hv.payload_json,'$.provider_id')
      AND (n.project_id='' OR n.project_id=h.project_id)
      AND n.record_key NOT IN (SELECT record_key FROM aliased)
      AND h.record_key NOT IN (SELECT record_key FROM aliased)
      AND h.record_key NOT IN (SELECT record_key FROM competing_history)
      AND NOT EXISTS (
          SELECT 1 FROM usage_records other
          WHERE other.semantic_key=h.semantic_key AND other.suppressed=0
            AND other.record_key!=h.record_key
      )
      AND NOT EXISTS (
          SELECT 1 FROM reconciliation_cases other
          WHERE other.record_key IN (n.record_key,h.record_key) AND other.state='open'
            AND other.id!=c.id AND other.type!='directory'
      )
      AND NOT EXISTS (SELECT 1 FROM usage_claims u WHERE u.record_key=n.record_key)
      AND EXISTS (
          SELECT 1 FROM codex_event_evidence event
          WHERE event.version_id=n.version_id
            AND event.pricing_basis IS NOT NULL AND event.pricing_basis!=''
            AND event.event_id=json_extract(nv.payload_json,'$.request_id')
            AND json_extract(event.evidence_json,'$.kind') IN ('response','snapshot')
            AND json_extract(event.evidence_json,'$.thread_id')=n.session_id
            AND json_extract(event.evidence_json,'$.pending_reason') IS NULL
      )
), signatures AS MATERIALIZED (
    SELECT DISTINCT {_match_fields("p")} FROM potential p
), sessions AS MATERIALIZED (
    SELECT DISTINCT session_id FROM signatures
), active_native AS MATERIALIZED (
    SELECT n.record_key,n.version_id,n.event_time,{_match_fields("n")}
    FROM sessions s
    CROSS JOIN usage_records n INDEXED BY usage_session ON n.session_id=s.session_id
    WHERE n.kind='detail' AND n.semantic_key IS NULL AND n.suppressed=0
), native_matches AS MATERIALIZED (
    SELECT n.* FROM active_native n
    CROSS JOIN signatures f ON ({_match_fields("f")})=({_match_fields("n")})
), pair_observations AS MATERIALIZED (
    SELECT n.record_key,json_extract(e.evidence_json,'$.response_id') AS response_id,
           json_extract(e.evidence_json,'$.snapshot_id') AS snapshot_id,
           COALESCE(e.pricing_basis,'')!='' AS priced,
           CASE WHEN e.event_id=json_extract(v.payload_json,'$.request_id')
                AND json_extract(e.evidence_json,'$.kind')='response'
                AND json_extract(e.evidence_json,'$.thread_id')=n.session_id
                AND json_extract(e.evidence_json,'$.pending_reason') IS NULL
                AND json_type(e.evidence_json,'$.response_id')='text'
                AND json_extract(e.evidence_json,'$.response_id')!=''
                AND json_type(e.evidence_json,'$.snapshot_id')='text'
                AND json_extract(e.evidence_json,'$.snapshot_id')!=''
                AND unixepoch(substr(codex_evidence_stamp(
                    json_extract(e.evidence_json,'$.timestamp')),1,19))=n.event_time
                THEN codex_evidence_stamp(json_extract(e.evidence_json,'$.snapshot_timestamp'))
           END AS snapshot_at
    FROM native_matches n
    CROSS JOIN codex_event_evidence e ON e.version_id=n.version_id
    JOIN usage_versions v ON v.id=n.version_id
    WHERE json_type(e.evidence_json,'$.snapshot_timestamp') IS NOT NULL
), pairing AS MATERIALIZED (
    SELECT record_key,MIN(snapshot_id) AS snapshot_id,MAX(priced) AS priced,
           CASE WHEN COUNT(*)=COUNT(snapshot_at)
                AND MIN(snapshot_at)=MAX(snapshot_at)
                AND MIN(snapshot_id)=MAX(snapshot_id) AND MIN(response_id)=MAX(response_id)
                THEN MIN(snapshot_at)
           END AS snapshot_at
    FROM pair_observations GROUP BY record_key
), matching AS MATERIALIZED (
    SELECT p.*,r.snapshot_id,r.snapshot_at,
           unixepoch(substr(r.snapshot_at,1,19)) AS snapshot_second,
           date(substr(r.snapshot_at,1,19),'+8 hours') AS snapshot_day
    FROM potential p LEFT JOIN pairing r ON r.record_key=p.record_key
    WHERE (r.record_key IS NULL OR r.snapshot_at IS NOT NULL)
      AND ((p.native_second=p.history_second AND p.native_day=p.history_day)
        OR (r.priced AND unixepoch(substr(r.snapshot_at,1,19))=p.history_second
           AND date(substr(r.snapshot_at,1,19),'+8 hours')=p.history_day))
), candidate_seconds AS MATERIALIZED (
    SELECT native_second AS second FROM matching
    UNION SELECT snapshot_second FROM matching WHERE snapshot_second IS NOT NULL
), native_clocks AS (
    SELECT n.record_key,n.event_time AS second,{_match_fields("n")} FROM native_matches n
    WHERE n.event_time IN (SELECT second FROM candidate_seconds)
    UNION
    SELECT n.record_key,unixepoch(substr(o.snapshot_at,1,19)) AS second,{_match_fields("n")}
    FROM pair_observations o JOIN native_matches n ON n.record_key=o.record_key
    WHERE unixepoch(substr(o.snapshot_at,1,19)) IN (SELECT second FROM candidate_seconds)
), competing_native AS MATERIALIZED (
    SELECT record_key FROM (
        SELECT n.record_key,
               COUNT(*) OVER (PARTITION BY n.second,{_match_fields("n")}) AS competitors
        FROM native_clocks n
    ) WHERE competitors>1
), eligible AS MATERIALIZED (
    SELECT p.id,p.candidate_version,p.history_version,p.snapshot_id,p.snapshot_at,
           p.adopt_candidate,p.current_cost_usd,p.candidate_cost_usd
    FROM matching p
    WHERE p.record_key NOT IN (SELECT record_key FROM competing_native)
      AND NOT EXISTS (
        SELECT 1 FROM usage_records other INDEXED BY codex_history_session_time
        JOIN usage_versions v ON v.id=other.version_id
        WHERE p.snapshot_second!=p.native_second AND other.kind='detail'
          AND other.semantic_key IS NOT NULL AND other.suppressed=0
          AND other.day=CASE WHEN p.history_second=p.native_second
                             THEN p.snapshot_day ELSE p.native_day END
          AND other.event_time=CASE WHEN p.history_second=p.native_second
                                    THEN p.snapshot_second ELSE p.native_second END
          AND ({_match_fields("other")})=({_match_fields("p")})
          AND json_extract(v.payload_json,'$.data_source')='codex_session'
          AND json_extract(v.payload_json,'$.app_type')=p.app_type
          AND json_extract(v.payload_json,'$.provider_id')=p.provider_id
          AND other.record_key!=p.history_key
    ) AND NOT EXISTS (
        SELECT 1 FROM codex_event_evidence other INDEXED BY codex_snapshot_identity
        CROSS JOIN active_native n ON n.version_id=other.version_id
        WHERE json_extract(other.evidence_json,'$.snapshot_id')=p.snapshot_id
          AND other.event_id!=p.event_id
          AND json_extract(other.evidence_json,'$.thread_id')=p.session_id
          AND json_extract(other.evidence_json,'$.kind') IN ('response','snapshot')
          AND json_extract(other.evidence_json,'$.pending_reason') IS NULL
    )
)
"""


def _filters(value: dict[str, Any]) -> dict[str, str]:
    if set(value) - FILTER_FIELDS:
        raise AppError("invalid_reconciliation_filter", "核对筛选格式不正确。")
    filters: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(item, str) or len(item) > 128 or "\x00" in item:
            raise AppError("invalid_reconciliation_filter", "核对筛选格式不正确。")
        if item.strip():
            filters[key] = item.strip()
    if "type" in filters and filters["type"] not in _CASE_TYPES:
        raise AppError("invalid_reconciliation_filter", "请选择有效的核对类型。")
    filters.setdefault("eligibility", "all")
    if filters["eligibility"] not in {"all", "batch", "manual"}:
        raise AppError("invalid_reconciliation_filter", "请选择有效的核对状态。")
    for boundary in ("start_date", "end_date"):
        if boundary in filters:
            filters[boundary] = parse_date(filters[boundary]).isoformat()
    if filters.get("start_date", "") > filters.get("end_date", "9999-12-31"):
        raise AppError("invalid_reconciliation_filter", "开始日期应早于或等于结束日期。")
    return filters


def _query(
    connection: sqlite3.Connection, filters: dict[str, str], ids: list[str] | None = None
) -> tuple[str, list[Any]]:
    # SQLite can round the final milliseconds. The parser truncates the exact UTC stamp.
    connection.create_function("codex_evidence_stamp", 1, _evidence_stamp, deterministic=True)
    clauses = ["c.state='open'"]
    params: list[Any] = []
    for key, clause in (
        ("type", "c.type=?"), ("source_id", "c.source_id=?"),
        ("start_date", f"{_DATE}>=?"), ("end_date", f"{_DATE}<=?"),
    ):
        if key in filters:
            clauses.append(clause)
            params.append(filters[key])
    if ids is not None:
        clauses.append("c.id IN (SELECT value FROM json_each(?))")
        params.append(json.dumps(ids))
    eligibility = {
        "all": "", "batch": "WHERE e.id IS NOT NULL", "manual": "WHERE e.id IS NULL",
    }[filters["eligibility"]]
    return f"""
    WITH open_cases AS MATERIALIZED (
        SELECT c.rowid AS position,c.id,c.type,c.source_id,c.record_key,c.generation,c.message,
               {_DATE} AS date,
               COALESCE(NULLIF(json_extract(c.info_json,'$.model'),''),r.model) AS model,
               json_extract(c.info_json,'$.other_record_key') AS history_key
        FROM reconciliation_cases c LEFT JOIN usage_records r ON r.record_key=c.record_key
        WHERE {" AND ".join(clauses)}
    ) {_MATCH_CASES}
    , filtered_cases AS MATERIALIZED (
        SELECT c.*,e.candidate_version,e.history_version,e.snapshot_id,e.snapshot_at,
               e.adopt_candidate,e.current_cost_usd,e.candidate_cost_usd
        FROM open_cases c LEFT JOIN eligible e ON e.id=c.id {eligibility}
    )
    """, params


def _open_count(connection: sqlite3.Connection) -> int:
    row = connection.execute(
        "SELECT COUNT(*) FROM reconciliation_cases WHERE state='open'"
    ).fetchone()
    return int(row[0])


def reconciliation_summary(store: Store) -> dict[str, int]:
    with store.read_connection() as connection:
        return {"total": _open_count(connection)}


def _after(cursor: str | None, query_hash: str) -> int:
    if cursor is None:
        return 0
    match = re.fullmatch(r"([0-9a-f]{64})-([1-9][0-9]{0,18})", cursor)
    if match is None or match[1] != query_hash or int(match[2]) > 2**63 - 1:
        raise AppError("invalid_cursor", "核对事项的分页依据已变化，请重新查询。", 409)
    return int(match[2])


def reconciliation_page(
    store: Store, filters: dict[str, Any], *, cursor: str | None = None, size: int = 50
) -> dict[str, Any]:
    if type(size) is not int or not 1 <= size <= 200:
        raise AppError("invalid_page", "每页可查看 1 至 200 项。")
    normalized = _filters(filters)
    with store.read_connection() as connection:
        query, params = _query(connection, normalized)
        version = content_hash(store.revisions(connection))
        query_hash = content_hash([normalized, version])
        position = _after(cursor, query_hash)
        rows = connection.execute(query + """
        , totals AS (
            SELECT COUNT(*) AS total,COUNT(candidate_version) AS eligible_count FROM filtered_cases
        ), page AS (
            SELECT * FROM filtered_cases WHERE position>? ORDER BY position LIMIT ?
        )
        SELECT page.*,totals.*,s.name AS source_name
        FROM totals LEFT JOIN page ON 1 LEFT JOIN source_profiles s ON s.id=page.source_id
        ORDER BY page.position
        """, [*params, position, size + 1]).fetchall()
        sources = [
            dict(row) for row in connection.execute("""
            SELECT c.source_id AS id,COALESCE(s.name,c.source_id) AS name
            FROM reconciliation_cases c LEFT JOIN source_profiles s ON s.id=c.source_id
            WHERE c.state='open' AND c.source_id IS NOT NULL
            GROUP BY c.source_id,s.name ORDER BY name,id
            """)
        ]
    return {
        "cases": [
            {
                **{field: row[field] for field in (
                    "id", "generation", "type", "message", "source_name", "date", "model",
                )},
                "batch_eligible": row["candidate_version"] is not None,
            }
            for row in rows[:size] if row["id"] is not None
        ],
        "total": rows[0]["total"],
        "eligible_count": rows[0]["eligible_count"],
        "next_cursor": f"{query_hash}-{rows[size - 1]['position']}" if len(rows) > size else None,
        "version": version,
        "sources": sources,
    }


def _selection(
    request: dict[str, Any], allowed: set[str]
) -> tuple[dict[str, str], list[str] | None]:
    if set(request) - allowed - {"filters", "ids"} or not isinstance(request.get("filters"), dict):
        raise AppError("invalid_reconciliation_filter", "核对筛选格式不正确。")
    ids = None
    if "ids" in request:
        raw = request["ids"]
        if not isinstance(raw, list) or not raw or any(
            not isinstance(case_id, str) or not _SAFE_CASE_ID.fullmatch(case_id) for case_id in raw
        ):
            raise AppError("invalid_reconciliation_selection", "所选核对事项无效，请重新选择。")
        ids = sorted(set(raw))
    return _filters(request["filters"]), ids


def _stale_batch() -> AppError:
    return AppError("stale_reconciliation_batch", "核对事项或依据已变化，请重新查询并预览。", 409)


def _selected_rows(
    connection: sqlite3.Connection, filters: dict[str, str], ids: list[str] | None
) -> list[sqlite3.Row]:
    query, params = _query(connection, filters, ids)
    return connection.execute(query + """
    SELECT id,record_key,source_id,generation,history_key,candidate_version,history_version,
           snapshot_id,snapshot_at,adopt_candidate,current_cost_usd,candidate_cost_usd
    FROM filtered_cases WHERE candidate_version IS NOT NULL ORDER BY id
    """, params).fetchall()


def _preview_hash(
    filters: dict[str, str], ids: list[str] | None, version: str, rows: list[sqlite3.Row]
) -> str:
    return content_hash([
        _BATCH_POLICY, filters, ids, version,
        [tuple(row[field] for field in (
            "id", "generation", "candidate_version", "history_version",
            "snapshot_id", "snapshot_at", "adopt_candidate",
            "current_cost_usd", "candidate_cost_usd",
        )) for row in rows],
    ])


def preview_reconciliation_batch(store: Store, request: dict[str, Any]) -> dict[str, Any]:
    filters, ids = _selection(request, {"version"})
    with store.read_connection() as connection:
        version = content_hash(store.revisions(connection))
        if version != request.get("version"):
            raise _stale_batch()
        rows = _selected_rows(connection, filters, ids)
        if ids is not None and len(rows) != len(ids):
            raise _stale_batch()
        if not rows:
            raise AppError("empty_reconciliation_batch", "当前筛选没有可批量确认的事项。", 409)
        current_cost, candidate_cost = DecimalSum(), DecimalSum()
        candidate_count = 0
        for row in rows:
            if row["adopt_candidate"]:
                candidate_count += 1
                current_cost.step(row["current_cost_usd"])
                candidate_cost.step(row["candidate_cost_usd"])
        return {
            "count": len(rows),
            "candidate_count": candidate_count,
            "current_cost_usd": current_cost.finalize(),
            "candidate_cost_usd": candidate_cost.finalize(),
            "preview_hash": _preview_hash(filters, ids, version, rows),
        }


def apply_reconciliation_batch(store: Store, request: dict[str, Any]) -> dict[str, Any]:
    filters, ids = _selection(request, {"preview_hash", "reason", "idempotency_key"})
    preview = request.get("preview_hash")
    if not isinstance(preview, str) or not _DIGEST.fullmatch(preview):
        raise _stale_batch()
    reason = request.get("reason")
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 4000 or "\x00" in reason:
        raise AppError("reason_required", "请填写核对依据。")
    reason = reason.strip()
    key = request.get("idempotency_key")
    if not isinstance(key, str) or not 16 <= len(key.strip()) <= 128 or "\x00" in key:
        raise AppError("idempotency_required", "操作信息不完整，请刷新后重试。")
    key = key.strip()
    signature = content_hash(["batch_same", filters, ids, preview, reason])
    with store._transaction():
        connection = store._db
        prior = ledger._replay_resolution(store, connection, key, signature)
        if prior is not None:
            return prior
        version = content_hash(store.revisions(connection))
        rows = _selected_rows(connection, filters, ids)
        if not rows or _preview_hash(filters, ids, version, rows) != preview:
            raise _stale_batch()
        scopes: set[str] = set()
        for row in rows:
            adopted_version = row["candidate_version"] if row["adopt_candidate"] else None
            scopes.update(ledger._confirm_same_identity(
                store, connection, row, {"other_record_key": row["history_key"]}, reason,
                adopted_version=adopted_version,
            ))
            choice = ledger.SAME_CANDIDATE if adopted_version is not None else "same"
            ledger._record_resolution(store, connection, row["id"], choice, reason)
        # Eligibility excludes confirmations that transfer a project to the history record.
        ledger._refresh_resolved_scopes(connection, scopes, update_projects=False)
        result = {
            "resolved_count": len(rows),
            "open_count": _open_count(connection),
            **store.revisions(connection),
        }
        connection.execute(
            "INSERT INTO reconciliation_idempotency VALUES(?,?,?)",
            (key, signature, store._encode(result)),
        )
        return result
