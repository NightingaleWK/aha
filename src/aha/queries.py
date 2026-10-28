"""Indexed ledger queries, exact cached summaries and revision-bound keyset pages."""

from __future__ import annotations

import base64
import json
import sqlite3
from calendar import monthrange
from collections.abc import Iterator
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any

from .domain import BEIJING, AppError, canonical_bytes, content_hash, parse_date

if TYPE_CHECKING:
    from .storage import Store

TOKENS = (
    "fresh_input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_creation_tokens",
    "total_tokens",
)


def validate_analysis(
    store: Store,
    analysis: dict[str, Any],
    connection: sqlite3.Connection | None = None,
    *,
    check_claims: bool = True,
) -> None:
    if connection is None:
        with store.read_connection() as reader:
            validate_analysis(store, analysis, reader, check_claims=check_claims)
            return
    actual = store.revisions(connection)
    for field in ("data_revision", "classification_revision", "claim_revision"):
        if field == "claim_revision" and not check_claims:
            continue
        if analysis.get(field) != actual[field]:
            code = "availability_changed" if field == "claim_revision" else "analysis_expired"
            raise AppError(code, "用量或归属已变化，请更新预览后重试。", 409)


def _filters(
    analysis: dict[str, Any], alias: str = "r", *, rows: bool = True,
    period_column: str = "day",
) -> tuple[str, list[Any]]:
    if rows:
        start = datetime.combine(parse_date(analysis["start_date"]), time.min, BEIJING)
        try:
            end = datetime.combine(
                parse_date(analysis["end_date"]) + timedelta(days=1), time.min, BEIJING
            )
        except OverflowError as exc:
            raise AppError("invalid_date_range", "结束日期超出支持范围。") from exc
        where = f"{alias}.event_time>=? AND {alias}.event_time<?"
        parameters: list[Any] = [int(start.timestamp()), int(end.timestamp())]
    else:
        where = f"{alias}.{period_column}>=? AND {alias}.{period_column}<=?"
        parameters = [analysis["start_date"], analysis["end_date"]]
    project = analysis.get("project_id", "all")
    if project != "all":
        where += f" AND {alias}.project_id=?"
        parameters.append("" if project == "unassigned" else project)
    if rows:
        where += f" AND {alias}.suppressed=0"
        if analysis.get("availability_mode") == "available":
            target = analysis.get("target_batch_id")
            if target:
                # Keep detail probes off peer detail claims even when dense-scope
                # ANALYZE estimates would prefer a full claim-table scan.
                where += f""" AND {alias}.usage_reason!='reconciliation'
                    AND NOT EXISTS(SELECT 1 FROM usage_claims c
                      WHERE c.record_key={alias}.record_key AND c.batch_id!=?)
                    AND NOT EXISTS(SELECT 1 FROM usage_claims c INDEXED BY usage_claim_scope
                      WHERE c.scope_key={alias}.scope_key AND c.kind='rollup' AND c.batch_id!=?)
                    AND ({alias}.kind!='rollup' OR NOT EXISTS(
                      SELECT 1 FROM usage_claims c INDEXED BY usage_claim_scope
                      WHERE c.scope_key={alias}.scope_key AND c.batch_id!=?))
                    AND ({alias}.semantic_key IS NULL OR NOT EXISTS(SELECT 1 FROM usage_claims c
                      WHERE c.semantic_key={alias}.semantic_key AND c.batch_id!=?))"""
                parameters.extend([target] * 4)
            else:
                where += f" AND {alias}.availability_state='available'"
    return where, parameters


def _summary(connection: sqlite3.Connection, analysis: dict[str, Any], mode: str) -> dict[str, Any]:
    source, parameters = _statistics_source(analysis)
    where = (
        "s.state='available'"
        if mode == "available"
        else "s.state!='pending'"
        if mode == "verified"
        else "s.state='claimed'"
    )
    token_columns = ",".join(f"integer_sum(s.{key}) AS {key}" for key in TOKENS)
    row = connection.execute(
        f"""SELECT integer_sum(record_count) AS record_count,
        SUM(CASE WHEN kind='detail' THEN row_count ELSE 0 END) AS detail_count,
        integer_sum(CASE WHEN kind='rollup' THEN record_count ELSE '0' END) AS rollup_record_count,
        SUM(CASE WHEN kind='rollup' THEN row_count ELSE 0 END) AS rollup_count,
        decimal_sum(total_cost_usd) AS total_cost_usd,
        decimal_sum(CASE WHEN kind='detail' THEN total_cost_usd ELSE '0' END) AS detail_cost_usd,
        decimal_sum(CASE WHEN kind='rollup' THEN total_cost_usd ELSE '0' END) AS rollup_cost_usd,
        {token_columns} FROM {source} WHERE {where}""",
        parameters,
    ).fetchone()
    return _finish_summary(dict(row))


def _statistics_source(analysis: dict[str, Any]) -> tuple[str, list[Any]]:
    """Partition the inclusive interval into full months and at most two day edges."""
    start, end = parse_date(analysis["start_date"]), parse_date(analysis["end_date"])
    ranges: list[tuple[str, str, date, date]] = []
    if start.day != 1:
        edge_end = min(end, date(start.year, start.month, monthrange(start.year, start.month)[1]))
        ranges.append(("daily_usage_stats", "day", start, edge_end))
        if edge_end == end:
            return _statistics_ranges(analysis, ranges)
        start = edge_end + timedelta(days=1)
    full_end: date | None
    if end.day == monthrange(end.year, end.month)[1]:
        full_end = end
    else:
        end_month_start = end.replace(day=1)
        full_end = end_month_start - timedelta(days=1) if end_month_start != date.min else None
    if full_end is not None and start <= full_end:
        ranges.append(("monthly_usage_stats", "month", start, full_end))
    if full_end != end:
        ranges.append(("daily_usage_stats", "day", max(start, end.replace(day=1)), end))
    return _statistics_ranges(analysis, ranges)


def _statistics_ranges(
    analysis: dict[str, Any], ranges: list[tuple[str, str, date, date]]
) -> tuple[str, list[Any]]:
    from .decimal_sql import USAGE_TOTAL_FIELDS

    columns = ",".join(("project_id", "model", "kind", "state", "row_count", *USAGE_TOTAL_FIELDS))
    pieces = []
    parameters: list[Any] = []
    for table, period, first, last in ranges:
        bounds = {
            **analysis,
            "start_date": first.isoformat()[:7] if period == "month" else first.isoformat(),
            "end_date": last.isoformat()[:7] if period == "month" else last.isoformat(),
        }
        where, values = _filters(bounds, "s", rows=False, period_column=period)
        pieces.append(f"SELECT {columns} FROM {table} s WHERE {where}")
        parameters.extend(values)
    return "(" + " UNION ALL ".join(pieces) + ") s", parameters


def _finish_summary(values: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        key: int(values.get(key) or 0)
        for key in ("record_count", "detail_count", "rollup_record_count", "rollup_count", *TOKENS)
    }
    result.update(
        {
            key: values.get(key) or "0"
            for key in ("total_cost_usd", "detail_cost_usd", "rollup_cost_usd")
        }
    )
    result["unpriced_count"] = int(values.get("unpriced_count") or 0)
    detail, rollup = result["detail_count"] > 0, result["rollup_count"] > 0
    result["source_grain"] = (
        "mixed"
        if detail and rollup
        else "detail"
        if detail
        else "daily_rollup"
        if rollup
        else "empty"
    )
    return result


def _summary_groups(
    connection: sqlite3.Connection, analysis: dict[str, Any]
) -> list[dict[str, Any]]:
    from .decimal_sql import USAGE_TOTAL_FIELDS

    source, parameters = _statistics_source(analysis)
    sql = f"""SELECT usage_groups(state,kind,row_count,{','.join(USAGE_TOTAL_FIELDS)})
        FROM {source}"""
    encoded = connection.execute(sql, parameters).fetchone()[0]
    return list(json.loads(encoded)) if encoded is not None else []


def _combine_groups(groups: list[dict[str, Any]], states: set[str]) -> dict[str, Any]:
    from .decimal_sql import DecimalSum

    totals: dict[str, Any] = {
        key: 0
        for key in (
            "record_count",
            "detail_count",
            "rollup_record_count",
            "rollup_count",
            "unpriced_count",
            *TOKENS,
        )
    }
    costs = {key: DecimalSum() for key in ("total_cost_usd", "detail_cost_usd", "rollup_cost_usd")}
    for row in groups:
        if row["state"] not in states:
            continue
        for key in ("record_count", "unpriced_count", *TOKENS):
            totals[key] += int(row[key] or 0)
        if row["kind"] == "detail":
            totals["detail_count"] += int(row["row_count"])
        else:
            totals["rollup_count"] += int(row["row_count"])
            totals["rollup_record_count"] += int(row["record_count"] or 0)
        costs["total_cost_usd"].step(row["total_cost_usd"])
        costs["detail_cost_usd" if row["kind"] == "detail" else "rollup_cost_usd"].step(
            row["total_cost_usd"]
        )
    totals.update({key: value.finalize() for key, value in costs.items()})
    return _finish_summary(totals)


def _combine_summaries(
    first: dict[str, Any], second: dict[str, Any], *, subtract: bool = False
) -> dict[str, Any]:
    from .decimal_sql import DecimalSum

    result: dict[str, Any] = {
        key: int(first[key]) + (-1 if subtract else 1) * int(second[key])
        for key in ("record_count", "detail_count", "rollup_record_count", "rollup_count",
                    "unpriced_count", *TOKENS)
    }
    for key in ("total_cost_usd", "detail_cost_usd", "rollup_cost_usd"):
        cost = DecimalSum()
        cost.step(first[key])
        cost.step(("-" if subtract else "") + second[key])
        result[key] = cost.finalize()
    return _finish_summary(result)


def _row_summary(
    connection: sqlite3.Connection, analysis: dict[str, Any], *, state: str | None = None
) -> dict[str, Any]:
    where, parameters = _filters(analysis)
    if state is not None:
        where += " AND r.availability_state=?"
        parameters.append(state)
    token_columns = ",".join(f"integer_sum(r.{key}) AS {key}" for key in TOKENS)
    row = connection.execute(
        f"""SELECT integer_sum(request_count) AS record_count,
        SUM(kind='detail') AS detail_count,
        integer_sum(CASE WHEN kind='rollup' THEN request_count ELSE '0' END)
          AS rollup_record_count,
        SUM(kind='rollup') AS rollup_count,
        integer_sum(CASE WHEN pricing_status='unpriced' THEN request_count ELSE '0' END)
          AS unpriced_count,decimal_sum(total_cost_usd) AS total_cost_usd,
        decimal_sum(CASE WHEN kind='detail' THEN total_cost_usd ELSE '0' END) AS detail_cost_usd,
        decimal_sum(CASE WHEN kind='rollup' THEN total_cost_usd ELSE '0' END) AS rollup_cost_usd,
        {token_columns} FROM usage_records r WHERE {where}""",
        parameters,
    ).fetchone()
    return _finish_summary(dict(row))


def _excluded_groups(
    connection: sqlite3.Connection, analysis: dict[str, Any]
) -> list[dict[str, Any]]:
    where, parameters = _filters(analysis, "s", rows=False)
    groups = []
    group_sql = f"""SELECT state,day,model,SUM(row_count) AS row_count,
        integer_sum(record_count) AS record_count FROM daily_usage_stats s
        WHERE {where} AND state!='available' GROUP BY day,model,state
        ORDER BY day,model,state LIMIT 100"""
    if analysis.get("target_batch_id"):
        all_where, all_parameters = _filters({**analysis, "availability_mode": "all"}, "r")
        eligible_where, eligible_parameters = _filters(
            {**analysis, "availability_mode": "available"}, "r"
        )
        group_sql = f"""SELECT r.availability_state AS state,r.day,r.model,
            COUNT(*) AS row_count,integer_sum(r.request_count) AS record_count
            FROM usage_records r WHERE {all_where} AND NOT ({eligible_where})
            GROUP BY r.day,r.model,r.availability_state
            ORDER BY r.day,r.model,r.availability_state LIMIT 100"""
        parameters = [*all_parameters, *eligible_parameters]
    for row in connection.execute(group_sql, parameters):
        groups.append(
            {
                "reason": "reconciliation" if row["state"] == "pending" else "identity",
                "message": "这部分用量待核对，依据不可相加。"
                if row["state"] == "pending"
                else "这部分用量已被报销记录占用。",
                "date": row["day"],
                "model": row["model"],
                "row_count": row["row_count"],
                "record_count": int(row["record_count"] or 0),
                "owners": [],
            }
        )
    return groups


def analyze(
    store: Store,
    start_date: str,
    end_date: str,
    project_id: str = "all",
    *,
    availability_mode: str = "available",
    target_batch_id: str | None = None,
    expected_generation: int | None = None,
    expected_active_version: int | None = None,
) -> dict[str, Any]:
    start, end = parse_date(start_date), parse_date(end_date)
    if start > end:
        raise AppError("invalid_date_range", "开始日期不能晚于结束日期。")
    if availability_mode not in {"available", "all"}:
        raise AppError("invalid_availability_mode", "请选择可用用量或全部用量。")
    with store.read_connection() as connection:
        project = connection.execute(
            "SELECT name FROM projects WHERE id=?", (project_id,)
        ).fetchone()
        if project_id not in {"all", "unassigned"} and project is None:
            raise AppError("project_not_found", "所选项目不存在。", 404)
        result: dict[str, Any] = {
            "start_date": start_date,
            "end_date": end_date,
            "project_id": project_id,
            "project_name": "全部项目"
            if project_id == "all"
            else "未归属"
            if project_id == "unassigned"
            else project[0],
            "availability_mode": availability_mode,
            "target_batch_id": target_batch_id,
            "expected_generation": expected_generation,
            "expected_active_version": expected_active_version,
            "timezone": "Asia/Shanghai",
            "schema_version": 23,
            "ledger_schema_version": 3,
            "source": {"kind": "ledger", "name": "本地台账"},
            **store.revisions(connection),
        }
        grouped = _summary_groups(connection, result)
        matched = _combine_groups(grouped, {"available", "claimed"})
        available = (
            _row_summary(connection, {**result, "availability_mode": "available"})
            if target_batch_id
            else _combine_groups(grouped, {"available"})
        )
        if target_batch_id and any(row["state"] == "pending" for row in grouped):
            # Own-claim exemption may make a globally ambiguous overlap usable
            # in this target context. Include exactly those eligible rows in its
            # matched basis too, so subtraction cannot invent negative exclusions.
            matched = _combine_summaries(
                matched, _row_summary(
                    connection, {**result, "availability_mode": "available"}, state="pending"
                )
            )
        excluded = (
            _combine_summaries(matched, available, subtract=True)
            if target_batch_id
            else _combine_groups(grouped, {"claimed"})
        )
        result["row_counts"] = {
            kind: sum(
                int(row["row_count"])
                for row in grouped
                if row["kind"] == kind
                and (availability_mode == "all" or row["state"] == "available")
            )
            for kind in ("detail", "rollup")
        }
        result["summary"] = available if availability_mode == "available" else matched
        if target_batch_id and availability_mode == "available":
            result["row_counts"] = {
                "detail": available["detail_count"],
                "rollup": available["rollup_count"],
            }
        statistics_source, statistics_parameters = _statistics_source(result)
        pending = connection.execute(
            f"SELECT COALESCE(SUM(row_count),0) FROM {statistics_source} WHERE state='pending'",
            statistics_parameters,
        ).fetchone()[0]
        result["pending_count"] = pending
        result["summary_complete"] = not pending
        result["availability"] = {
            "mode": availability_mode,
            "claim_revision": result["claim_revision"],
            "matched_summary": matched,
            "available_summary": available,
            "excluded_summary": excluded,
            "excluded_groups": _excluded_groups(connection, result),
        }
        unassigned = {**result, "project_id": "unassigned"}
        unassigned_source, unassigned_parameters = _statistics_source(unassigned)
        unassigned_where = (
            "s.state='available'"
            if availability_mode == "available"
            else "s.state!='pending'"
        )
        result["unassigned_count"] = int(connection.execute(
            f"SELECT integer_sum(record_count) FROM {unassigned_source} WHERE " + unassigned_where,
            unassigned_parameters,
        ).fetchone()[0] or 0)
        result["unassigned_record_count"] = result["unassigned_count"]
        result["warnings"] = ["参考成本沿用来源保存金额，申请报销金额另填。"]
        if pending:
            result["warnings"].append("部分用量待核对，合计仅含已核实部分；不同粒度依据不可相加。")
        if not result["summary"]["record_count"]:
            result["warnings"].append("当前条件没有可统计用量，无记录不能证明零消耗。")
        result["selection_hash"] = content_hash(
            {
                key: result[key]
                for key in (
                    "start_date",
                    "end_date",
                    "project_id",
                    "availability_mode",
                    "target_batch_id",
                    "data_revision",
                    "classification_revision",
                    "claim_revision",
                )
            }
        )
        result["counts"] = {
            "detail_count": result["summary"]["detail_count"],
            "rollup_count": result["summary"]["rollup_count"],
        }
        return result


def _enrich_row(
    store: Store, connection: sqlite3.Connection, row: sqlite3.Row, *, owners: bool = False
) -> dict[str, Any]:
    result = dict(store._decode(row["payload_json"]))
    result.update(
        {
            "kind": row["kind"],
            "record_key": row["record_key"],
            "version_id": row["version_id"],
            "content_fingerprint": row["content_hash"],
            "date": row["day"],
            "time": datetime.fromtimestamp(row["event_time"], BEIJING).isoformat(),
            "project_id": row["project_id"] or None,
            "project_name": row["project_name"] or "未归属",
            "assignment_origin": row["assignment_origin"],
            "cwd": row["cwd"],
            "fresh_input_tokens": int(row["fresh_input_tokens"]),
            "total_tokens": int(row["total_tokens"]),
            "pricing_status": row["pricing_status"],
            "usage_state": row["availability_state"],
            "usage_reason": row["usage_reason"],
            "usage_owners": [],
            "scope_key": row["scope_key"],
            "semantic_key": row["semantic_key"],
        }
    )
    if owners and row["availability_state"] != "available":
        # UNION ALL keeps every relationship on its exact range; the outer DISTINCT
        # retains the same bounded owner set without a dynamic-kind scope scan.
        branches = ["SELECT batch_id,owner_version FROM usage_claims WHERE record_key=?"]
        parameters = [row["record_key"], row["scope_key"]]
        branches.append(
            "SELECT batch_id,owner_version FROM usage_claims INDEXED BY usage_claim_scope "
            "WHERE scope_key=?"
            + ("" if row["kind"] == "rollup" else " AND kind='rollup'")
        )
        if row["semantic_key"] is not None:
            branches.append(
                "SELECT batch_id,owner_version FROM usage_claims WHERE semantic_key=?"
            )
            parameters.append(row["semantic_key"])
        result["usage_owners"] = [
            {"batch_id": r["batch_id"], "version": r["owner_version"]}
            for r in connection.execute(
                "SELECT DISTINCT batch_id,owner_version FROM ("
                + " UNION ALL ".join(branches) + ") LIMIT 20",
                parameters,
            )
        ]
    return result


def iter_analysis_rows(
    store: Store, analysis: dict[str, Any], connection: sqlite3.Connection | None = None
) -> Iterator[dict[str, Any]]:
    if connection is None:
        with store.read_connection() as reader:
            yield from iter_analysis_rows(store, analysis, reader)
        return
    validate_analysis(store, analysis, connection)
    where, parameters = _filters(analysis)
    cursor = connection.execute(
        (
            "SELECT r.*,v.payload_json,p.name AS project_name FROM usage_reco"
            "rds r JOIN usage_versions v ON v.id=r.version_id LEFT JOIN proje"
            "cts p ON p.id=r.project_id WHERE "
        )
        + where
        + " ORDER BY r.event_time,r.record_key",
        parameters,
    )
    while rows := cursor.fetchmany(512):
        for row in rows:
            result = _enrich_row(store, connection, row)
            if analysis["availability_mode"] == "available":
                result.update(usage_state="available", usage_reason="", usage_owners=[])
            yield result


def _cursor_decode(value: str | None, analysis: dict[str, Any], kind: str) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(base64.urlsafe_b64decode(value.encode()).decode())
        if parsed["selection"] != analysis["selection_hash"] or parsed["kind"] != kind:
            raise ValueError
        return dict(parsed)
    except (ValueError, KeyError, TypeError, UnicodeError) as exc:
        raise AppError("invalid_cursor", "分页依据无效，请更新预览。", 409) from exc


def _cursor_encode(analysis: dict[str, Any], kind: str, values: list[Any], direction: str) -> str:
    return base64.urlsafe_b64encode(
        canonical_bytes(
            {
                "selection": analysis["selection_hash"],
                "kind": kind,
                "values": values,
                "direction": direction,
            }
        )
    ).decode()


def analysis_details(
    store: Store,
    analysis: dict[str, Any],
    *,
    cursor: str | None = None,
    size: int = 50,
    kind: str = "detail",
) -> dict[str, Any]:
    if (
        isinstance(size, bool)
        or not isinstance(size, int)
        or not 1 <= size <= 200
        or kind not in {"detail", "rollup", "daily", "models"}
    ):
        raise AppError("invalid_page", "分页参数无效。")
    state = _cursor_decode(cursor, analysis, kind)
    with store.read_connection() as connection:
        validate_analysis(store, analysis, connection)
        if kind in {"daily", "models"}:
            return _aggregate_page(store, connection, analysis, state, size, kind)
        where, parameters = _filters(analysis)
        where += " AND r.kind=?"
        parameters.append(kind)
        backwards = state.get("direction") == "previous"
        if state:
            values = state["values"]
            if (
                not isinstance(values, list)
                or len(values) != 2
                or not isinstance(values[0], int)
                or not isinstance(values[1], str)
            ):
                raise AppError("invalid_cursor", "分页依据无效。", 409)
            # SQLite may choose the scalar date bound as its index seek and then
            # test the tuple for every earlier row. Tighten that existing bound
            # to the cursor second; the tuple still orders keys within a second.
            if backwards:
                parameters[1] = min(parameters[1], values[0] + 1)
            else:
                parameters[0] = max(parameters[0], values[0])
            where += " AND (r.event_time,r.record_key)" + ("<" if backwards else ">") + "(?,?)"
            parameters.extend(values)
        order = "DESC" if backwards else "ASC"
        raw = connection.execute(
            f"""SELECT r.*,v.payload_json,p.name AS project_name FROM usage_records r
            JOIN usage_versions v ON v.id=r.version_id
            LEFT JOIN projects p ON p.id=r.project_id WHERE {where}
            ORDER BY r.event_time {order},r.record_key {order} LIMIT ?""",
            [*parameters, size + 1],
        ).fetchall()
        more = len(raw) > size
        raw = raw[:size]
        if backwards:
            raw.reverse()
        rows = [_enrich_row(store, connection, row, owners=True) for row in raw]
        if analysis["availability_mode"] == "available":
            for row in rows:
                row.update(usage_state="available", usage_reason="", usage_owners=[])
        has_previous, has_next = (more, bool(state)) if backwards else (bool(state), more)
        next_cursor = (
            _cursor_encode(analysis, kind, [raw[-1]["event_time"], raw[-1]["record_key"]], "next")
            if raw and has_next
            else None
        )
        previous_cursor = (
            _cursor_encode(analysis, kind, [raw[0]["event_time"], raw[0]["record_key"]], "previous")
            if raw and has_previous
            else None
        )
        total = analysis.get("row_counts", {}).get(kind, 0)
        return {
            "rows": rows,
            "total": total,
            "next_cursor": next_cursor,
            "previous_cursor": previous_cursor,
        }


def _aggregate_sql(
    analysis: dict[str, Any], kind: str, state: dict[str, Any] | None = None
) -> tuple[str, list[Any], list[str]]:
    raw = bool(analysis.get("target_batch_id"))
    if not raw and kind == "models":
        source, parameters = _statistics_source(analysis)
        where = "state='available'" if analysis["availability_mode"] == "available" else (
            "state!='pending'"
        )
    else:
        where, parameters = _filters(analysis, "s", rows=raw)
        if not raw:
            where += (" AND state='available'" if analysis["availability_mode"] == "available"
                      else " AND state!='pending'")
        source = ("usage_records" if raw else "daily_usage_stats") + " s"
    represented = "request_count" if raw else "record_count"
    count = "1" if raw else "row_count"
    columns = ["day", "project_id", "model"] if kind == "daily" else ["model"]
    fields = ",".join(columns)
    if state:
        values = state.get("values")
        if (not isinstance(values, list) or len(values) != len(columns)
                or not all(isinstance(v, str) for v in values)):
            raise AppError("invalid_cursor", "分页依据无效。", 409)
        operator = "<" if state.get("direction") == "previous" else ">"
        where += (f" AND ({fields}){operator}(" + ",".join("?" for _ in columns) + ")")
        parameters.extend(values)
    aggregates = ",".join(f"integer_sum({key}) AS {key}" for key in TOKENS)
    sql = f"""SELECT {fields},integer_sum({represented}) AS record_count,
        SUM(CASE WHEN kind='detail' THEN {count} ELSE 0 END) AS detail_count,
        integer_sum(CASE WHEN kind='rollup' THEN {represented} ELSE '0' END)
          AS rollup_record_count,
        SUM(CASE WHEN kind='rollup' THEN {count} ELSE 0 END) AS rollup_count,
        decimal_sum(CASE WHEN kind='detail' THEN total_cost_usd ELSE '0' END)
          AS detail_cost_usd,
        decimal_sum(CASE WHEN kind='rollup' THEN total_cost_usd ELSE '0' END)
          AS rollup_cost_usd,
        decimal_sum(total_cost_usd) AS total_cost_usd,{aggregates}
        FROM {source} WHERE {where} GROUP BY {fields} ORDER BY """
    order = " DESC" if state and state.get("direction") == "previous" else " ASC"
    sql += ",".join(column + order for column in columns)
    return sql, parameters, columns


def _aggregate_row(row: sqlite3.Row, names: dict[str, str], kind: str) -> dict[str, Any]:
    return {**dict(row), **_finish_summary(dict(row)),
            "date": row["day"] if kind == "daily" else None,
            "project_name": names.get(row["project_id"], "未归属") if kind == "daily" else None}


def _aggregate_page(store: Store, connection: sqlite3.Connection, analysis: dict[str, Any],
                    state: dict[str, Any], size: int, kind: str) -> dict[str, Any]:
    sql, parameters, columns = _aggregate_sql(analysis, kind, state)
    raw = connection.execute(sql + " LIMIT ?", [*parameters, size + 1]).fetchall()
    more, raw = len(raw) > size, raw[:size]
    backwards = state.get("direction") == "previous"
    if backwards:
        raw.reverse()
    names = {row["id"]: row["name"] for row in connection.execute("SELECT id,name FROM projects")}
    rows = [_aggregate_row(row, names, kind) for row in raw]
    has_previous, has_next = (more, bool(state)) if backwards else (bool(state), more)
    return {
        "rows": rows,
        "total": None,
        "next_cursor": (
            _cursor_encode(analysis, kind, [raw[-1][c] for c in columns], "next")
            if raw and has_next else None
        ),
        "previous_cursor": (
            _cursor_encode(analysis, kind, [raw[0][c] for c in columns], "previous")
            if raw and has_previous else None
        ),
    }


def iter_analysis_daily(store: Store, analysis: dict[str, Any],
                        connection: sqlite3.Connection | None = None) -> Iterator[dict[str, Any]]:
    if connection is None:
        with store.read_connection() as reader:
            yield from iter_analysis_daily(store, analysis, reader)
        return
    validate_analysis(store, analysis, connection)
    sql, parameters, _ = _aggregate_sql(analysis, "daily")
    names = {row["id"]: row["name"] for row in connection.execute("SELECT id,name FROM projects")}
    cursor = connection.execute(sql, parameters)
    while rows := cursor.fetchmany(512):
        for row in rows:
            yield _aggregate_row(row, names, "daily")


def ledger_status(store: Store) -> dict[str, Any]:
    with store.read_connection() as connection:
        counts: dict[str, int] = {}
        pending = total = 0
        for row in connection.execute(
            """SELECT kind,SUM(row_count) AS n,
            SUM(CASE WHEN state='pending' THEN row_count ELSE 0 END) AS pending,
            integer_sum(CASE WHEN state!='pending' THEN record_count ELSE '0' END) AS represented
            FROM monthly_usage_stats GROUP BY kind"""
        ):
            counts[row["kind"]] = row["n"]
            pending += row["pending"]
            total += int(row["represented"] or 0)
        first_day = connection.execute(
            "SELECT day FROM daily_usage_stats ORDER BY day LIMIT 1"
        ).fetchone()
        last_day = connection.execute(
            "SELECT day FROM daily_usage_stats ORDER BY day DESC LIMIT 1"
        ).fetchone()
        latest_success = connection.execute(
            "SELECT * FROM sync_runs WHERE state='completed' ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        latest_attempt = connection.execute(
            "SELECT * FROM sync_runs ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        directories = [
            dict(row)
            for row in connection.execute(
                "SELECT cwd AS path,COUNT(*) AS session_count FROM sessions WHERE"
                " status='matched' AND cwd IS NOT NULL GROUP BY cwd ORDER BY cwd "
                "LIMIT 1000"
            )
        ]
        metadata = connection.execute(
            "SELECT COUNT(*),COALESCE(SUM(status='matched'),0) FROM sessions"
        ).fetchone()

        def run(row: sqlite3.Row | None) -> dict[str, Any] | None:
            return (
                None
                if row is None
                else {
                    "id": row["id"],
                    "state": row["state"],
                    "started_at": row["started_at"],
                    "completed_at": row["completed_at"],
                    "error_code": row["error_code"],
                    "error_message": row["error_message"],
                    **store._decode(row["result_json"]),
                }
            )

        return {
            **store.revisions(connection),
            "counts": {
                "detail_count": counts.get("detail", 0),
                "rollup_count": counts.get("rollup", 0),
                "record_count": int(total or 0),
                "pending_count": pending,
            },
            "pending_count": pending,
            "coverage": {"start_date": first_day[0] if first_day else None,
                         "end_date": last_day[0] if last_day else None},
            "last_sync": run(latest_success),
            "last_attempt": run(latest_attempt),
            "last_successful_sync_at": latest_success["completed_at"] if latest_success else None,
            "directories": directories,
            "metadata_coverage": {
                "total_sessions": metadata[0],
                "matched_sessions": metadata[1],
                "error_count": 0,
            },
        }
