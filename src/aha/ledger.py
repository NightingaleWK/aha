"""Row facts, conservative reconciliation and rebuildable local projections."""

from __future__ import annotations

import sqlite3
from calendar import monthrange
from collections.abc import Iterable
from datetime import datetime
from typing import TYPE_CHECKING, Any

from . import claims
from .domain import BEIJING, AppError, content_hash, fresh_input, record_key, row_fingerprint

if TYPE_CHECKING:
    from .storage import Store

METRICS = (
    "request_count",
    "fresh_input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_creation_tokens",
    "total_tokens",
)


def record_projection(row: dict[str, Any], kind: str) -> dict[str, Any]:
    day = (
        row["date"]
        if kind == "rollup"
        else datetime.fromtimestamp(row["created_at"], BEIJING).date().isoformat()
    )
    event_time = (
        int(datetime.fromisoformat(day).replace(tzinfo=BEIJING).timestamp())
        if kind == "rollup"
        else int(row["created_at"])
    )
    enriched = {**row, "date": day}
    member = claims.member_from_row(enriched, kind)
    fresh = fresh_input(row)
    return {
        "record_key": record_key(row, kind),
        "kind": kind,
        "content_hash": row_fingerprint(row, kind),
        "day": day,
        "event_time": event_time,
        "scope_key": claims.scope_key(member),
        "semantic_key": claims.semantic_key(member),
        "coverage_key": content_hash(
            [
                day,
                row["app_type"],
                row["provider_id"],
                row["model"],
                row.get("request_model") or "",
                row.get("pricing_model") or "",
            ]
        ),
        "model": row["model"],
        "pricing_model": row.get("pricing_model") or row["model"],
        "session_id": row.get("session_id"),
        "request_count": str(row.get("request_count", 1)),
        "fresh_input_tokens": str(fresh),
        "output_tokens": str(row["output_tokens"]),
        "cache_read_tokens": str(row["cache_read_tokens"]),
        "cache_creation_tokens": str(row["cache_creation_tokens"]),
        "total_tokens": str(
            fresh + row["output_tokens"] + row["cache_read_tokens"] + row["cache_creation_tokens"]
        ),
        "total_cost_usd": row["total_cost_usd"],
    }


def canonical_record_key(connection: sqlite3.Connection, key: str) -> str:
    """Resolve only explicitly confirmed aliases; raw source identities stay immutable."""
    seen: set[str] = set()
    while key not in seen:
        seen.add(key)
        alias = connection.execute(
            "SELECT canonical_key FROM record_aliases WHERE alias_key=?", (key,)
        ).fetchone()
        if alias is None:
            return key
        key = str(alias[0])
        if len(seen) >= 100:
            break
    raise AppError("storage_damaged", "本地消费身份关系损坏，无法继续。", 409)


def set_current(
    connection: sqlite3.Connection, version_id: int, *, logical_key: str | None = None
) -> tuple[str, str | None]:
    version = connection.execute(
        "SELECT * FROM usage_versions WHERE id=?", (version_id,)
    ).fetchone()
    if version is None:
        raise AppError("invalid_candidate", "核对候选不存在。", 409)
    import json

    projection = record_projection(
        json.loads(version["payload_json"]), version["record_key"].split(":", 1)[0]
    )
    canonical = canonical_record_key(connection, projection["record_key"])
    if logical_key is not None and canonical != logical_key:
        raise AppError("invalid_candidate", "事实候选不属于该消费身份。", 409)
    projection["record_key"] = canonical
    previous = connection.execute(
        "SELECT scope_key FROM usage_records WHERE record_key=?", (projection["record_key"],)
    ).fetchone()
    fields = tuple(projection)
    columns = ",".join(fields)
    placeholders = ",".join("?" for _ in fields)
    updates = ",".join(f"{field}=excluded.{field}" for field in fields if field != "record_key")
    connection.execute(
        f"INSERT INTO usage_records({columns},version_id) VALUES({placeholders},?) "
        f"ON CONFLICT(record_key) DO UPDATE SET {updates},version_id=excluded.version_id",
        (*projection.values(), version_id),
    )
    connection.execute(
        (
            "INSERT INTO coverage_groups(id,scope_key,day,model) VALUES(?,?,?"
            ",?) ON CONFLICT(id) DO NOTHING"
        ),
        (
            projection["coverage_key"],
            projection["scope_key"],
            projection["day"],
            projection["model"],
        ),
    )
    return projection["scope_key"], previous[0] if previous else None


def create_case(
    connection: sqlite3.Connection,
    case_type: str,
    message: str,
    info: dict[str, Any],
    *,
    coverage_key: str | None = None,
    key: str | None = None,
    source_id: str | None = None,
    reopen: bool = False,
) -> str:
    case_id = content_hash([case_type, coverage_key, key, source_id, info.get("candidate_hash")])
    connection.execute(
        (
            "INSERT INTO reconciliation_cases(id,type,coverage_key,record_key"
            ",source_id,message,info_json) VALUES(?,?,?,?,?,?,?) ON CONFLICT("
            "id) DO NOTHING"
        ),
        (case_id, case_type, coverage_key, key, source_id, message, _encode(info)),
    )
    if reopen:
        connection.execute(
            (
                "UPDATE reconciliation_cases SET state='open',generation=generati"
                "on+1,info_json=? WHERE id=? AND state!='open'"
            ),
            (_encode(info), case_id),
        )
    connection.execute(
        """UPDATE reconciliation_cases SET info_json=?,generation=generation+1
        WHERE id=? AND state='open' AND info_json!=?""",
        (_encode(info), case_id, _encode(info)),
    )
    return case_id


def _encode(value: Any) -> str:
    from .domain import canonical_bytes

    return canonical_bytes(value).decode()


def update_coverage(connection: sqlite3.Connection, groups: Iterable[str]) -> set[str]:
    scopes: set[str] = set()
    for group_id in groups:
        group = connection.execute(
            "SELECT * FROM coverage_groups WHERE id=?", (group_id,)
        ).fetchone()
        if group is None:
            continue
        scopes.add(group["scope_key"])
        counts = {
            row["kind"]: row["n"]
            for row in connection.execute(
                (
                    "SELECT kind,COUNT(*) AS n FROM usage_records WHERE coverage_key="
                    "? AND record_key NOT IN (SELECT alias_key FROM record_aliases) G"
                    "ROUP BY kind"
                ),
                (group_id,),
            )
        }
        if counts.get("detail") and counts.get("rollup"):
            connection.execute(
                "UPDATE coverage_groups SET basis='unknown',generation=generation+1 WHERE id=?",
                (group_id,),
            )
            connection.execute(
                (
                    "UPDATE usage_records SET suppressed=0 WHERE coverage_key=? AND r"
                    "ecord_key NOT IN (SELECT alias_key FROM record_aliases)"
                ),
                (group_id,),
            )
            amounts = {
                row["kind"]: row["amount"]
                for row in connection.execute(
                    (
                        "SELECT kind,decimal_sum(total_cost_usd) AS amount FROM usage_rec"
                        "ords WHERE coverage_key=? GROUP BY kind"
                    ),
                    (group_id,),
                )
            }
            represented = connection.execute(
                (
                    "SELECT integer_sum(request_count) FROM usage_records WHERE cover"
                    "age_key=? AND kind='rollup'"
                ),
                (group_id,),
            ).fetchone()[0]
            create_case(
                connection,
                "coverage",
                "明细与来源日汇总的成员覆盖尚未确认，两份依据不可相加。",
                {
                    "date": group["day"],
                    "model": group["model"],
                    "detail_count": counts["detail"],
                    "rollup_count": counts["rollup"],
                    "rollup_record_count": int(represented or 0),
                    "detail_cost_usd": amounts.get("detail", "0"),
                    "rollup_cost_usd": amounts.get("rollup", "0"),
                },
                coverage_key=group_id,
                reopen=True,
            )
    return scopes


def reclassify(connection: sqlite3.Connection, scopes: set[str] | None = None) -> None:
    import json

    from .projects import _contains, canonical_path

    rules = []
    for project in connection.execute("SELECT id,directories_json FROM projects"):
        for directory in json.loads(project["directories_json"]):
            rules.append((len(canonical_path(directory)), canonical_path(directory), project["id"]))
    rules.sort(reverse=True)
    if scopes is not None:
        _scope_table(connection, scopes)
    where = (
        "" if scopes is None else " WHERE r.scope_key IN (SELECT scope_key FROM temp.work_scopes)"
    )
    if scopes is not None and not scopes:
        return
    parameters: tuple[Any, ...] = ()
    cursor = connection.execute(
        (
            "SELECT r.record_key,r.content_hash,r.session_id,s.cwd,s.status,o"
            ".project_id AS override_id,o.content_hash AS override_hash FROM "
            "usage_records r LEFT JOIN sessions s ON s.id=r.session_id LEFT J"
            "OIN overrides o ON o.record_key=r.record_key"
        )
        + where,
        parameters,
    )
    while rows := cursor.fetchmany(512):
        updates = []
        for row in rows:
            project_id, origin = "", "unassigned"
            cwd = row["cwd"] if row["status"] == "matched" else None
            if row["override_id"] and row["override_hash"] == row["content_hash"]:
                project_id, origin = row["override_id"], "manual"
            elif cwd:
                try:
                    candidate = canonical_path(cwd)
                except AppError:
                    candidate = ""
                for _, directory, target in rules:
                    if candidate and _contains(directory, candidate):
                        project_id, origin = target, "directory_rule"
                        break
            updates.append((project_id, origin, cwd, row["record_key"]))
        connection.executemany(
            "UPDATE usage_records SET project_id=?,assignment_origin=?,cwd=? WHERE record_key=?",
            updates,
        )


def refresh_availability(connection: sqlite3.Connection, scopes: set[str] | None = None) -> None:
    if scopes is not None and not scopes:
        return
    if scopes is not None:
        _scope_table(connection, scopes)
    clause = (
        "" if scopes is None else " AND r.scope_key IN (SELECT scope_key FROM temp.work_scopes)"
    )
    parameters: tuple[Any, ...] = ()
    # Separate the indexed record/coverage probes from the small source-case set.
    # A correlated OR can otherwise scan unrelated revision cases for every fact.
    pending = """(
        EXISTS(SELECT 1 FROM reconciliation_cases x
          WHERE x.coverage_key=r.coverage_key AND x.state='open') OR
        EXISTS(SELECT 1 FROM reconciliation_cases x
          WHERE x.record_key=r.record_key AND x.state='open') OR
        (EXISTS(SELECT 1 FROM reconciliation_cases WHERE type='source' AND state='open') AND
         (SELECT v.source_id FROM usage_versions v WHERE v.id=r.version_id) IN
          (SELECT source_id FROM reconciliation_cases WHERE type='source' AND state='open'))
        )"""
    identity = "EXISTS(SELECT 1 FROM usage_claims c WHERE c.record_key=r.record_key)"
    # Require the owned scope index for these fixed ranges: ANALYZE on an all-detail
    # scope can misestimate the absent rollup kind and choose a pairwise table scan.
    overlap = """(
        EXISTS(SELECT 1 FROM usage_claims c INDEXED BY usage_claim_scope
          WHERE c.scope_key=r.scope_key
          AND c.kind='rollup' AND c.record_key!=r.record_key) OR
        (r.kind='rollup' AND EXISTS(SELECT 1 FROM usage_claims c INDEXED BY usage_claim_scope
          WHERE c.scope_key=r.scope_key AND c.record_key!=r.record_key)) OR
        (r.semantic_key IS NOT NULL AND EXISTS(SELECT 1 FROM usage_claims c
          WHERE c.semantic_key=r.semantic_key AND c.record_key!=r.record_key))
        )"""
    connection.execute(
        f"""UPDATE usage_records AS r SET
        availability_state=CASE WHEN {pending} THEN 'pending' WHEN {identity} THEN 'claimed'
        WHEN {overlap} THEN 'pending' ELSE 'available' END,
        usage_reason=CASE WHEN {pending} THEN 'reconciliation' WHEN {identity} THEN 'identity'
        WHEN {overlap} THEN 'overlap' ELSE '' END WHERE 1=1 {clause}""",
        parameters,
    )
    refresh_daily(connection, scopes)


def _scope_table(connection: sqlite3.Connection, scopes: set[str]) -> None:
    connection.execute("CREATE TEMP TABLE IF NOT EXISTS work_scopes(scope_key TEXT PRIMARY KEY)")
    connection.execute("DELETE FROM temp.work_scopes")
    connection.executemany("INSERT INTO temp.work_scopes VALUES(?)", ((scope,) for scope in scopes))


def refresh_daily(connection: sqlite3.Connection, scopes: set[str] | None = None) -> None:
    if scopes is not None and not scopes:
        return
    if scopes is None:
        connection.execute("DELETE FROM daily_usage_stats")
        _insert_stats(connection, "", ())
        refresh_monthly(connection)
        return
    _scope_table(connection, scopes)
    groups = connection.execute(
        "SELECT DISTINCT day,model FROM coverage_groups WHERE scope_key I"
        "N (SELECT scope_key FROM temp.work_scopes)"
    ).fetchall()
    for day, model in groups:
        connection.execute("DELETE FROM daily_usage_stats WHERE day=? AND model=?", (day, model))
        _insert_stats(connection, " AND day=? AND model=?", (day, model))
    refresh_monthly(connection, {day[:7] for day, _ in groups})


def refresh_monthly(connection: sqlite3.Connection, months: set[str] | None = None) -> None:
    """Rebuild only affected months from exact daily projections, in the same transaction."""
    if months is not None and not months:
        return
    aggregates = ",".join(
        f"integer_sum({metric})"
        for metric in ("record_count", *METRICS[1:], "unpriced_count")
    )

    def insert(where: str, parameters: tuple[Any, ...]) -> None:
        connection.execute(
            """INSERT INTO monthly_usage_stats(month,project_id,model,kind,state,row_count,
            record_count,fresh_input_tokens,output_tokens,cache_read_tokens,
            cache_creation_tokens,total_tokens,unpriced_count,total_cost_usd)
            SELECT substr(day,1,7),project_id,model,kind,state,SUM(row_count),"""
            + aggregates + ",decimal_sum(total_cost_usd) FROM daily_usage_stats " + where
            + " GROUP BY substr(day,1,7),project_id,model,kind,state",
            parameters,
        )

    if months is None:
        connection.execute("DELETE FROM monthly_usage_stats")
        insert("", ())
        return
    for month in sorted(months):
        year, number = map(int, month.split("-"))
        last = f"{month}-{monthrange(year, number)[1]:02d}"
        connection.execute("DELETE FROM monthly_usage_stats WHERE month=?", (month,))
        insert("WHERE day>=? AND day<=?", (month + "-01", last))


def _insert_stats(connection: sqlite3.Connection, where: str, parameters: tuple[Any, ...]) -> None:
    aggregates = ",".join(f"integer_sum({metric})" for metric in METRICS)
    connection.execute(
        """INSERT INTO daily_usage_stats(day,project_id,model,kind,state,row_count,
        record_count,fresh_input_tokens,output_tokens,cache_read_tokens,cache_creation_tokens,total_tokens,total_cost_usd,unpriced_count)
        SELECT day,project_id,model,kind,availability_state,COUNT(*),"""
        + aggregates
        + (
            ",decimal_sum(total_cost_usd),integer_sum(CASE WHEN pricing_statu"
            "s='unpriced' THEN request_count ELSE '0' END) FROM usage_records"
            " WHERE suppressed=0"
        )
        + where
        + " GROUP BY day,project_id,model,kind,availability_state",
        parameters,
    )


def list_reconciliations(store: Store) -> list[dict[str, Any]]:
    with store.read_connection() as connection:
        results = []
        for row in connection.execute(
            "SELECT c.*,s.name AS source_name FROM reconciliation_cases c LEF"
            "T JOIN source_profiles s ON s.id=c.source_id WHERE c.state='open"
            "' ORDER BY c.rowid LIMIT 1000"
        ):
            info = store._decode(row["info_json"])
            choices = (
                ["detail", "rollup"]
                if row["type"] == "coverage"
                else ["current", "candidate"]
                if row["type"] == "revision"
                else ["same", "independent"]
                if row["type"] == "identity"
                else ["current"]
            )
            if row["type"] in {"identity", "revision"}:
                for label, key in (
                    (
                        "current",
                        info.get("other_record_key")
                        if row["type"] == "identity"
                        else row["record_key"],
                    ),
                    ("candidate", row["record_key"]),
                ):
                    version_id = (
                        info.get("candidate_version_id")
                        if label == "candidate" and row["type"] == "revision"
                        else None
                    )
                    fact = connection.execute(
                        (
                            "SELECT r.*,v.payload_json FROM usage_records r JOIN usage_versio"
                            "ns v ON v.id=r.version_id WHERE r.record_key=?"
                        ),
                        (key,),
                    ).fetchone()
                    if fact:
                        payload = store._decode(fact["payload_json"])
                        if version_id:
                            candidate = connection.execute(
                                "SELECT payload_json FROM usage_versions WHERE id=?", (version_id,)
                            ).fetchone()
                            payload = store._decode(candidate[0]) if candidate else payload
                        info[label + "_summary"] = {
                            k: payload.get(k)
                            for k in (
                                "model",
                                "session_id",
                                "created_at",
                                "input_tokens",
                                "output_tokens",
                                "cache_read_tokens",
                                "cache_creation_tokens",
                                "total_cost_usd",
                            )
                        }
            results.append(
                {
                    **info,
                    "id": row["id"],
                    "type": row["type"],
                    "generation": row["generation"],
                    "message": row["message"],
                    "source_name": row["source_name"],
                    "choices": choices,
                }
            )
        return results


def resolve_reconciliation(
    store: Store,
    case_id: str,
    choice: str,
    reason: str,
    expected_generation: int | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    if not reason.strip() or len(reason) > 4000:
        raise AppError("reason_required", "请填写核对依据。")
    signature = content_hash([case_id, choice, reason, expected_generation])
    with store._transaction():
        connection = store._db
        if idempotency_key:
            prior = connection.execute(
                "SELECT * FROM reconciliation_idempotency WHERE key=?", (idempotency_key,)
            ).fetchone()
            if prior:
                if prior["payload_hash"] != signature:
                    raise AppError("idempotency_conflict", "同一重试标识对应不同内容。", 409)
                return dict(store._decode(prior["result_json"]))
        case = connection.execute(
            "SELECT * FROM reconciliation_cases WHERE id=?", (case_id,)
        ).fetchone()
        if case is None:
            raise AppError("case_not_found", "未找到核对事项。", 404)
        if case["state"] != "open" or (
            expected_generation is not None and case["generation"] != expected_generation
        ):
            raise AppError("stale_case", "核对事项已变化，请刷新。", 409)
        info = store._decode(case["info_json"])
        scopes: set[str] = set()
        if case["type"] == "coverage":
            if choice not in {"detail", "rollup"}:
                raise AppError("invalid_choice", "请选择合法的核算基准。")
            group = connection.execute(
                "SELECT * FROM coverage_groups WHERE id=?", (case["coverage_key"],)
            ).fetchone()
            scope = group["scope_key"]
            conflict = connection.execute(
                "SELECT 1 FROM usage_claims WHERE scope_key=? AND kind!=? LIMIT 1", (scope, choice)
            ).fetchone()
            if conflict:
                raise AppError(
                    "usage_claimed", "该核对与已有报销占用冲突，请先按正常流程纠错。", 409
                )
            connection.execute(
                "UPDATE coverage_groups SET basis=?,generation=generation+1 WHERE id=?",
                (choice, case["coverage_key"]),
            )
            connection.execute(
                (
                    "UPDATE usage_records SET suppressed=CASE WHEN record_key IN (SEL"
                    "ECT alias_key FROM record_aliases) THEN 1 WHEN kind=? THEN 0 ELS"
                    "E 1 END WHERE coverage_key=?"
                ),
                (choice, case["coverage_key"]),
            )
            scopes.add(scope)
        elif case["type"] == "revision":
            if choice not in {"current", "candidate"}:
                raise AppError("invalid_choice", "请选择合法的事实候选。")
            if choice == "candidate":
                new_scope, old_scope = set_current(
                    connection, int(info["candidate_version_id"]), logical_key=case["record_key"]
                )
                updated = connection.execute(
                    "SELECT coverage_key FROM usage_records WHERE record_key=?",
                    (case["record_key"],),
                ).fetchone()
                scopes |= update_coverage(connection, [updated[0]])
                scopes.add(new_scope)
                if old_scope:
                    scopes.add(old_scope)
            else:
                row = connection.execute(
                    "SELECT scope_key FROM usage_records WHERE record_key=?", (case["record_key"],)
                ).fetchone()
                if row:
                    scopes.add(row[0])
        elif case["type"] == "identity":
            if choice not in {"same", "independent"}:
                raise AppError("invalid_choice", "请确认同一消费或独立消费。")
            row = connection.execute(
                "SELECT scope_key FROM usage_records WHERE record_key=?", (case["record_key"],)
            ).fetchone()
            if row:
                scopes.add(row[0])
            if choice == "same":
                if connection.execute(
                    "SELECT 1 FROM usage_claims WHERE record_key=?", (case["record_key"],)
                ).fetchone():
                    raise AppError("usage_claimed", "该候选已占用，请先处理原报销。", 409)
                canonical = canonical_record_key(connection, info["other_record_key"])
                if canonical == case["record_key"]:
                    raise AppError("invalid_candidate", "消费身份关系已变化，请刷新。", 409)
                original = connection.execute(
                    "SELECT r.*,v.payload_json FROM usage_records r JOIN usage_versions v "
                    "ON v.id=r.version_id WHERE r.record_key=?", (canonical,)
                ).fetchone()
                candidate = connection.execute(
                    "SELECT r.*,v.payload_json FROM usage_records r JOIN usage_versions v "
                    "ON v.id=r.version_id WHERE r.record_key=?", (case["record_key"],)
                ).fetchone()
                if original is None or candidate is None:
                    raise AppError("invalid_candidate", "消费事实已变化，请刷新。", 409)
                scopes.add(original["scope_key"])
                connection.execute(
                    "UPDATE usage_records SET suppressed=1 WHERE record_key=?",
                    (case["record_key"],),
                )
                connection.execute(
                    (
                        "INSERT INTO record_aliases VALUES(?,?,?) ON CONFLICT(alias_key) "
                        "DO UPDATE SET canonical_key=excluded.canonical_key,reason=exclud"
                        "ed.reason"
                    ),
                    (case["record_key"], canonical, reason),
                )
                accepted = store._decode(original["payload_json"])
                proposed = store._decode(candidate["payload_json"])
                accepted.pop("request_id", None)
                proposed.pop("request_id", None)
                if accepted != proposed:
                    create_case(
                        connection, "revision", "已确认同一消费，但事实值不同，请核对版本。",
                        {
                            "candidate_version_id": candidate["version_id"],
                            "candidate_hash": candidate["content_hash"],
                            "current_version_id": original["version_id"],
                            "date": original["day"], "model": original["model"],
                            "current_cost_usd": original["total_cost_usd"],
                            "candidate_cost_usd": candidate["total_cost_usd"],
                        }, key=canonical, source_id=case["source_id"],
                    )
        else:
            if choice != "current":
                raise AppError("invalid_choice", "请选择保留本地事实并确认该来源。")
            observed = connection.execute(
                """SELECT id FROM sync_runs WHERE source_id=? AND state='needs_review'
                ORDER BY rowid DESC LIMIT 1""",
                (case["source_id"],),
            ).fetchone()
            if observed:
                connection.execute(
                    """INSERT INTO source_epochs(id,source_id,state,created_at)
                    VALUES(?,?,'confirmed',?) ON CONFLICT(id) DO NOTHING""",
                    (observed[0], case["source_id"], store._now()),
                )
        connection.execute(
            "UPDATE reconciliation_cases SET state='resolved',generation=generation+1 WHERE id=?",
            (case_id,),
        )
        connection.execute(
            "INSERT INTO reconciliation_events(case_id,choice,reason,created_at) VALUES(?,?,?,?)",
            (case_id, choice, reason.strip(), store._now()),
        )
        connection.execute(
            "UPDATE settings SET value=CAST(value AS INTEGER)+1 WHERE key='data_revision'"
        )
        reclassify(connection, scopes if scopes else None)
        refresh_availability(connection, scopes if scopes else None)
        result = {
            "id": case_id,
            "state": "resolved",
            "choice": choice,
            **store.revisions(connection),
        }
        if idempotency_key:
            connection.execute(
                "INSERT INTO reconciliation_idempotency VALUES(?,?,?)",
                (idempotency_key, signature, store._encode(result)),
            )
        return result
