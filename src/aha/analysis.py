"""One set of date, project, token and saved-cost calculations for all consumers."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from decimal import Decimal, localcontext
from typing import Any

from .domain import (
    BEIJING,
    SCHEMA_VERSION,
    AppError,
    content_hash,
    decimal_text,
    decimal_value,
    fresh_input,
    parse_date,
    record_key,
    row_fingerprint,
)
from .projects import classify

_TOKEN_METRICS = (
    "fresh_input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_creation_tokens",
    "total_tokens",
)
_COUNT_METRICS = ("record_count", "detail_count", "rollup_record_count", "unpriced_count")
_COST_METRICS = ("total_cost_usd", "detail_cost_usd", "rollup_cost_usd")


def _empty_totals() -> dict[str, Any]:
    return {
        **{key: 0 for key in (*_COUNT_METRICS, *_TOKEN_METRICS)},
        **{key: Decimal(0) for key in _COST_METRICS},
        "_grains": set(),
    }


def _accumulate(target: dict[str, Any], row: dict[str, Any], grain: str) -> None:
    count = 1 if grain == "detail" else row["request_count"]
    target["record_count"] += count
    target["detail_count"] += int(grain == "detail")
    target["rollup_record_count"] += count if grain == "rollup" else 0
    target["unpriced_count"] += count if row["pricing_status"] == "unpriced" else 0
    for key in _TOKEN_METRICS:
        target[key] += row[key]
    cost = decimal_value(row["total_cost_usd"], nonnegative=True)
    target["total_cost_usd"] += cost
    target["detail_cost_usd" if grain == "detail" else "rollup_cost_usd"] += cost
    target["_grains"].add(grain)


def _finish_totals(target: dict[str, Any]) -> dict[str, Any]:
    grains = target.pop("_grains")
    target["source_grain"] = (
        "mixed"
        if len(grains) > 1
        else "detail"
        if grains == {"detail"}
        else "daily_rollup"
        if grains
        else "empty"
    )
    for key in _COST_METRICS:
        target[key] = decimal_text(target[key])
    return target


def _pricing_status(row: dict[str, Any], pricing: dict[str, dict[str, Any]]) -> str:
    model = row.get("pricing_model") or row["model"]
    price = pricing.get(model)
    usable = price is not None and any(
        decimal_value(price[key], nonnegative=True) > 0
        for key in (
            "input_cost_per_million",
            "output_cost_per_million",
            "cache_read_cost_per_million",
            "cache_creation_cost_per_million",
        )
    )
    if usable:
        return "available"
    return "unpriced" if decimal_value(row["total_cost_usd"]) == 0 else "missing_basis"


def _enrich(
    original: dict[str, Any],
    metadata: dict[str, Any],
    config: dict[str, Any],
    grain: str,
    pricing: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    row = dict(original)
    row.update(classify(original, metadata, config, grain))
    row["record_key"] = record_key(original, grain)
    row["content_fingerprint"] = row_fingerprint(original, grain)
    row["fresh_input_tokens"] = fresh_input(original)
    row["total_tokens"] = (
        row["fresh_input_tokens"]
        + row["output_tokens"]
        + row["cache_read_tokens"]
        + row["cache_creation_tokens"]
    )
    row["pricing_status"] = _pricing_status(original, pricing)
    subtraction = row["cache_read_tokens"] + (
        row["cache_creation_tokens"] if row["input_token_semantics"] == 1 else 0
    )
    row["token_anomaly"] = row["input_token_semantics"] != 2 and row["input_tokens"] < subtraction
    if grain == "detail":
        event_time = datetime.fromtimestamp(row["created_at"], BEIJING)
        row["date"] = event_time.date().isoformat()
        row["time"] = event_time.isoformat()
    return row


def _member(row: dict[str, Any], grain: str) -> dict[str, Any]:
    member = {
        "kind": grain,
        "key": row["record_key"],
        "content_hash": row["content_fingerprint"],
        "date": row["date"],
        "model": row["model"],
        "app_type": row["app_type"],
        "data_source": row["data_source"] if grain == "detail" else "codex_session",
        "provider_id": row["provider_id"],
        **{key: row[key] for key in _TOKEN_METRICS},
    }
    if grain == "detail":
        member.update({"session_id": row.get("session_id"), "created_at": row["created_at"]})
        member["semantic_key"] = content_hash(
            [
                member[key]
                for key in (
                    "app_type",
                    "data_source",
                    "session_id",
                    "created_at",
                    "model",
                    *_TOKEN_METRICS,
                )
            ]
        )
    else:
        member["request_count"] = row["request_count"]
        member["request_model"] = row["request_model"]
        member["pricing_model"] = row["pricing_model"]
    return member


def analyze(
    data: dict[str, Any],
    metadata: dict[str, Any],
    config: dict[str, Any],
    start_date: str,
    end_date: str,
    project_id: str = "all",
) -> dict[str, Any]:
    start, end = parse_date(start_date), parse_date(end_date)
    if start > end:
        raise AppError("invalid_date_range", "开始日期不能晚于结束日期。")
    try:
        lower = int(datetime.combine(start, time.min, BEIJING).timestamp())
        upper = int(datetime.combine(end + timedelta(days=1), time.min, BEIJING).timestamp())
    except (ValueError, OverflowError, OSError) as exc:
        raise AppError("invalid_date_range", "日期超出支持范围，请选择较早的结束日期。") from exc
    if data.get("schema_version") != SCHEMA_VERSION:
        raise AppError("unsupported_schema", "此留存的结构版本不受支持。")
    names = {project["id"]: project["name"] for project in config.get("projects", [])}
    if project_id not in {"all", "unassigned"} and project_id not in names:
        raise AppError("project_not_found", "所选项目不存在，请重新选择。", 404)
    project_name = (
        "全部项目"
        if project_id == "all"
        else "未归属"
        if project_id == "unassigned"
        else names[project_id]
    )
    pricing = {row["model_id"]: row for row in data.get("pricing", [])}
    details: list[dict[str, Any]] = []
    rollups: list[dict[str, Any]] = []
    members: list[dict[str, Any]] = []
    daily: dict[tuple[str, str, str], dict[str, Any]] = {}
    models: dict[str, dict[str, Any]] = {}
    summary = _empty_totals()
    unassigned = 0
    matched_details = 0
    missing_basis = 0
    anomalies = 0
    grain_days: dict[str, set[tuple[str, str]]] = {"detail": set(), "rollup": set()}
    with localcontext() as context:
        # Source magnitude/scale are bounded to 100; a million-row sum fits 256 digits.
        context.prec = 256
        for grain, originals, selected in (
            ("detail", data.get("details", []), details),
            ("rollup", data.get("rollups", []), rollups),
        ):
            for original in originals:
                if original.get("app_type") != "codex":
                    continue
                if grain == "detail":
                    if original.get("data_source") != "codex_session":
                        continue
                    if not lower <= original["created_at"] < upper:
                        continue
                elif (
                    original.get("provider_id") != "_codex_session"
                    or not start_date <= original["date"] <= end_date
                ):
                    continue
                row = _enrich(original, metadata, config, grain, pricing)
                assigned_id = row["project_id"]
                if project_id == "unassigned" and assigned_id is not None:
                    continue
                if project_id not in {"all", "unassigned"} and assigned_id != project_id:
                    continue
                selected.append(row)
                members.append(_member(row, grain))
                _accumulate(summary, row, grain)
                daily_key = (row["date"], assigned_id or "", row["model"])
                if daily_key not in daily:
                    daily[daily_key] = {
                        **_empty_totals(),
                        "date": row["date"],
                        "model": row["model"],
                        "project_id": assigned_id,
                        "project_name": row["project_name"],
                    }
                _accumulate(daily[daily_key], row, grain)
                if row["model"] not in models:
                    models[row["model"]] = {**_empty_totals(), "model": row["model"]}
                _accumulate(models[row["model"]], row, grain)
                count = 1 if grain == "detail" else row["request_count"]
                if assigned_id is None:
                    unassigned += count
                if grain == "detail" and row.get("cwd"):
                    matched_details += 1
                missing_basis += count if row["pricing_status"] == "missing_basis" else 0
                anomalies += int(row["token_anomaly"])
                grain_days[grain].add((row["date"], row["model"]))
        summary = _finish_totals(summary)
        daily_rows = [_finish_totals(daily[key]) for key in sorted(daily)]
        model_rows = [_finish_totals(models[key]) for key in sorted(models)]
    details.sort(key=lambda row: (row["created_at"], row["request_id"]))
    rollups.sort(key=lambda row: (row["date"], row["model"], row["record_key"]))
    members.sort(key=lambda row: (row["kind"], row["key"]))
    warnings = ["参考成本沿用 CC Switch 保存值，是估算使用价值，不能单独证明实际扣款。"]
    if rollups:
        warnings.append("历史日汇总没有逐次记录和原始时区；本次按北京时间整日纳入。")
    if grain_days["detail"] & grain_days["rollup"]:
        warnings.append("同日同模型存在明细与日汇总，已保留来源金额合计；可能重叠，请核查来源。")
    if summary["unpriced_count"]:
        warnings.append(f"有 {summary['unpriced_count']} 条代表记录未定价，零金额不表示免费。")
    if missing_basis:
        warnings.append(f"有 {missing_basis} 条代表记录缺少当前价格依据，仍保留历史保存金额。")
    if anomalies:
        warnings.append(f"有 {anomalies} 行输入小于待扣缓存，按原输入保留并标记异常。")
    if unassigned:
        warnings.append(f"有 {unassigned} 条代表记录未归属项目，可配置目录或人工指定。")
    if not summary["record_count"]:
        warnings.append("所选条件没有匹配记录；无记录日期不能据此认定为零消耗。")
    return {
        "start_date": start_date,
        "end_date": end_date,
        "project_id": project_id,
        "project_name": project_name,
        "classification_revision": config.get("revision", 0),
        "timezone": "Asia/Shanghai",
        "schema_version": SCHEMA_VERSION,
        "source": dict(data.get("source", {})),
        "metadata_fingerprint": content_hash(metadata.get("sessions", {})),
        "details": details,
        "rollups": rollups,
        "daily": daily_rows,
        "models": model_rows,
        "members": members,
        "warnings": warnings,
        "summary": summary,
        "unassigned_record_count": unassigned,
        "selection_coverage": {
            "matched_detail_count": matched_details,
            "total_detail_count": len(details),
            "rollup_rows": len(rollups),
            "unassigned_record_count": unassigned,
        },
    }
