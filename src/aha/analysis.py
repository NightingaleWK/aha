"""One set of date, project, token and saved-cost calculations for all consumers."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from decimal import Decimal, localcontext
from typing import Any

from . import claims
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
    return claims.member_from_row(row, grain)


_EXCLUSION_MESSAGES = {
    "identity": "已被其他报销记录占用。",
    "suspected_rebuild": "这部分用量可能与已有记录重复，请先核对。",
    "cross_grain": "这部分用量与已有日汇总或明细可能重复，请先核对。",
    "rollup_scope": "这条日汇总与已有记录可能重复，请先核对。",
    "internal_overlap": "来源中的明细和汇总可能重复，请先核对。",
    "legacy_hold": "旧报销记录尚待核对，这部分用量暂不可用。",
}


def _usage_state(exclusion: dict[str, Any] | None) -> str:
    if exclusion is None:
        return "available"
    return "claimed" if exclusion["reason"] == "identity" else "ambiguous"


def empty_summary() -> dict[str, Any]:
    return _finish_totals(_empty_totals())


def _group_exclusions(
    candidates: list[tuple[str, dict[str, Any], dict[str, Any]]],
    exclusions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    excluded_by_key = {item["key"]: item for item in exclusions}
    groups: dict[str, dict[str, Any]] = {}
    with localcontext() as context:
        context.prec = 256
        for grain, row, member in candidates:
            exclusion = excluded_by_key.get(member["key"])
            if exclusion is None:
                continue
            reason = exclusion["reason"]
            owners = sorted(
                exclusion["owners"], key=lambda owner: (owner["batch_id"], owner["version"])
            )
            group_key = content_hash({"reason": reason, "owners": owners})
            if group_key not in groups:
                groups[group_key] = {
                    "reason": reason,
                    "message": _EXCLUSION_MESSAGES.get(
                        reason, "这部分用量暂不可用，请先核对。"
                    ),
                    "owners": owners,
                    "row_count": 0,
                    "_totals": _empty_totals(),
                }
            group = groups[group_key]
            group["row_count"] += 1
            _accumulate(group["_totals"], row, grain)
        result = []
        for group in groups.values():
            totals = _finish_totals(group.pop("_totals"))
            group.update({name: totals[name] for name in (
                "record_count", "detail_count", "rollup_record_count", "total_cost_usd"
            )})
            result.append(group)
    return result


def selection_conflicts(
    result: dict[str, Any], snapshot: dict[str, Any], target_batch_id: str | None = None
) -> list[dict[str, Any]]:
    """Check the actual frozen selection without silently changing its totals."""
    evaluated = claims.evaluate(result["members"], snapshot, target_batch_id)
    candidates = [
        (grain, row, _member(row, grain))
        for grain, key in (("detail", "details"), ("rollup", "rollups"))
        for row in result[key]
    ]
    return _group_exclusions(candidates, evaluated["excluded"])


def analyze(
    data: dict[str, Any],
    metadata: dict[str, Any],
    config: dict[str, Any],
    start_date: str,
    end_date: str,
    project_id: str = "all",
    *,
    claim_snapshot: dict[str, Any] | None = None,
    availability_mode: str = "all",
    target_batch_id: str | None = None,
    expected_generation: int | None = None,
    expected_active_version: int | None = None,
) -> dict[str, Any]:
    if availability_mode not in {"available", "all"}:
        raise AppError("invalid_availability_mode", "请选择可用用量或全部用量。")
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
    candidates: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    details: list[dict[str, Any]] = []
    rollups: list[dict[str, Any]] = []
    members: list[dict[str, Any]] = []
    daily: dict[tuple[str, str, str], dict[str, Any]] = {}
    models: dict[str, dict[str, Any]] = {}
    summary = _empty_totals()
    matched_totals = _empty_totals()
    available_totals = _empty_totals()
    excluded_totals = _empty_totals()
    unassigned = 0
    matched_details = 0
    missing_basis = 0
    anomalies = 0
    grain_days: dict[str, set[tuple[str, str]]] = {"detail": set(), "rollup": set()}
    with localcontext() as context:
        # Source magnitude/scale are bounded to 100; a million-row sum fits 256 digits.
        context.prec = 256
        for grain, originals in (
            ("detail", data.get("details", [])),
            ("rollup", data.get("rollups", [])),
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
                candidates.append((grain, row, _member(row, grain)))
        snapshot = claim_snapshot or {"claim_revision": 0, "claims": [], "legacy_holds": []}
        evaluated = claims.evaluate(
            [member for _, _, member in candidates], snapshot, target_batch_id
        )
        available_keys = set(evaluated["available_keys"])
        excluded_by_key = {item["key"]: item for item in evaluated["excluded"]}
        for grain, row, member in candidates:
            key = member["key"]
            exclusion = excluded_by_key.get(key)
            _accumulate(matched_totals, row, grain)
            if key in available_keys:
                _accumulate(available_totals, row, grain)
            else:
                _accumulate(excluded_totals, row, grain)
                if exclusion is None:
                    raise AppError("invalid_availability", "用量状态不完整，请重新预览。", 409)
            row["usage_state"] = _usage_state(exclusion)
            row["usage_reason"] = exclusion["reason"] if exclusion else None
            row["usage_owners"] = exclusion["owners"] if exclusion else []
            if availability_mode == "available" and key not in available_keys:
                continue
            (details if grain == "detail" else rollups).append(row)
            members.append(member)
            _accumulate(summary, row, grain)
            assigned_id = row["project_id"]
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
        matched_summary = _finish_totals(matched_totals)
        available_summary = _finish_totals(available_totals)
        excluded_summary = _finish_totals(excluded_totals)
        excluded_groups = _group_exclusions(candidates, evaluated["excluded"])
        summary = _finish_totals(summary)
        daily_rows = [_finish_totals(daily[key]) for key in sorted(daily)]
        model_rows = [_finish_totals(models[key]) for key in sorted(models)]
    details.sort(key=lambda row: (row["created_at"], row["request_id"]))
    rollups.sort(key=lambda row: (row["date"], row["model"], row["record_key"]))
    members.sort(key=lambda row: (row["kind"], row["key"]))
    warnings = ["参考成本按 CC Switch 历史记录汇总，申请报销金额由你填写。"]
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
        "claim_revision": evaluated["claim_revision"],
        "availability_mode": availability_mode,
        "target_batch_id": target_batch_id,
        "expected_generation": expected_generation,
        "expected_active_version": expected_active_version,
        "availability": {
            "mode": availability_mode,
            "claim_revision": evaluated["claim_revision"],
            "matched_summary": matched_summary,
            "available_summary": available_summary,
            "excluded_summary": excluded_summary,
            "excluded_groups": excluded_groups,
        },
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
