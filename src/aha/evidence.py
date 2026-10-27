"""Four-file evidence packages built only from a frozen analysis result."""

from __future__ import annotations

import csv
import hashlib
import html
import io
import re
import unicodedata
import zipfile
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from . import __version__
from .archive import safe_source
from .domain import BEIJING, AppError, canonical_bytes, decimal_text

UPSTREAM_COMMIT = "e55d8a21b3897b595b746e9f2139716b2931641d"
DETAIL_COLUMNS = (
    "project_id",
    "project_name",
    "assignment_origin",
    "time",
    "model",
    "request_model",
    "pricing_model",
    "input_tokens",
    "input_token_semantics",
    "fresh_input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_creation_tokens",
    "total_tokens",
    "input_cost_usd",
    "output_cost_usd",
    "cache_read_cost_usd",
    "cache_creation_cost_usd",
    "total_cost_usd",
    "cost_multiplier",
    "request_id",
    "session_id",
    "pricing_status",
)
DAILY_COLUMNS = (
    "project_id",
    "project_name",
    "date",
    "model",
    "detail_count",
    "rollup_record_count",
    "record_count",
    "source_grain",
    "fresh_input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_creation_tokens",
    "total_tokens",
    "total_cost_usd",
    "detail_cost_usd",
    "rollup_cost_usd",
    "unpriced_count",
)
MEMBER_FIELDS = (
    "kind",
    "key",
    "content_hash",
    "date",
    "model",
    "app_type",
    "data_source",
    "provider_id",
    "session_id",
    "created_at",
    "fresh_input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_creation_tokens",
    "total_tokens",
    "request_count",
)


def validate_claim(claim: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(claim, dict):
        raise AppError("invalid_claim", "请填写有效的申请说明。")
    result: dict[str, Any] = {}
    for key in ("purpose", "amount_note"):
        value = claim.get(key, "")
        if not isinstance(value, str) or len(value) > 4000:
            raise AppError("invalid_claim", "用途及金额说明各最多为 4000 个字符。")
        result[key] = value.strip()
    currency = claim.get("currency", "CNY")
    if currency not in {"CNY", "USD"}:
        raise AppError("invalid_currency", "申请币种只能为 CNY 或 USD。")
    result["currency"] = currency
    amount = claim.get("amount")
    if amount is None or amount == "":
        result["amount"] = None
    else:
        if (
            not isinstance(amount, str)
            or len(amount) > 40
            or not re.fullmatch(r"\d+(?:\.\d{1,2})?", amount)
        ):
            raise AppError("invalid_amount", "申请金额须为非负金额，最多保留两位小数。")
        try:
            parsed = Decimal(amount)
        except InvalidOperation as exc:
            raise AppError("invalid_amount", "申请金额格式无效。") from exc
        if not parsed.is_finite() or parsed < 0:
            raise AppError("invalid_amount", "申请金额须为有限的非负金额。")
        if not result["amount_note"]:
            raise AppError("amount_note_required", "填写申请金额时，请同时填写金额依据。")
        result["amount"] = decimal_text(parsed)
    return result


def safe_filename_component(value: str, max_units: int = 80) -> str:
    value = unicodedata.normalize("NFKC", value)
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', "_", value).strip(" .")
    value = re.sub(r"\s+", " ", value)
    if not value:
        value = "未命名项目"
    if re.fullmatch(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", value, flags=re.IGNORECASE):
        value = "_" + value
    while len(value.encode("utf-16-le")) // 2 > max_units:
        value = value[:-1]
    return value.rstrip(" .") or "项目"


def csv_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    if text.startswith(("\t", "\r", "\n")) or text.lstrip(" \t\r\n").startswith(
        ("=", "+", "-", "@")
    ):
        return "'" + text
    return text


def _csv(columns: tuple[str, ...], rows: list[dict[str, Any]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow(csv_cell(row.get(column)) for column in columns)
    return output.getvalue().encode("utf-8-sig")


def _escape(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _display_time(value: Any) -> str:
    if not isinstance(value, str) or not value:
        return "未提供"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(BEIJING).strftime("%Y-%m-%d %H:%M（北京时间）")
    except ValueError:
        return value


def _availability_basis(analysis: dict[str, Any]) -> dict[str, Any] | None:
    original = analysis.get("availability")
    if not isinstance(original, dict):
        return None
    summary_fields = (
        "record_count", "detail_count", "rollup_record_count", "fresh_input_tokens",
        "output_tokens", "cache_read_tokens", "cache_creation_tokens", "total_tokens",
        "total_cost_usd", "detail_cost_usd", "rollup_cost_usd", "unpriced_count", "source_grain",
    )
    result: dict[str, Any] = {
        "mode": original.get("mode"), "claim_revision": original.get("claim_revision"),
    }
    for key in ("matched_summary", "available_summary", "excluded_summary"):
        summary = original.get(key, {})
        result[key] = {field: summary[field] for field in summary_fields if field in summary}
    groups = []
    for group in original.get("excluded_groups", []):
        projected = {
            key: group[key]
            for key in (
                "reason", "row_count", "record_count", "detail_count", "rollup_record_count",
                "total_cost_usd",
            )
            if key in group
        }
        projected["owners"] = [
            {key: owner[key] for key in ("batch_id", "number", "version", "status", "lifecycle")
             if key in owner}
            for owner in group.get("owners", [])
        ]
        groups.append(projected)
    result["excluded_groups"] = groups
    return result


def _report(
    analysis: dict[str, Any], claim: dict[str, Any], batch: dict[str, Any], capture: dict[str, Any]
) -> bytes:
    summary = analysis["summary"]
    amount = "未填写" if claim["amount"] is None else f"{claim['amount']} {claim['currency']}"
    grain_names = {"detail": "逐条明细", "daily_rollup": "历史日汇总", "mixed": "明细与汇总"}
    daily_rows = "".join(
        "<tr>"
        + "".join(
            "<td>"
            + _escape(
                grain_names.get(row.get(key), row.get(key))
                if key == "source_grain" else row.get(key)
            )
            + "</td>"
            for key in (
                "project_name", "date", "model", "detail_count", "rollup_record_count",
                "source_grain", "total_cost_usd",
            )
        )
        + "</tr>"
        for row in analysis["daily"]
    )
    note_items = [
        "参考成本为 CC Switch 保存的模型用量估算；申请报销金额由申请人填写。",
        "统计日期按北京时间计算，包含开始和结束日期。",
    ]
    if analysis.get("rollups"):
        note_items.append("历史日汇总按来源完整记录纳入，没有补成逐条调用。")
    if summary.get("unpriced_count", 0):
        note_items.append(f"有 {summary['unpriced_count']} 条记录未计价，参考成本不完整。")
    # The source's generic cost note is already explained once above.
    generic_cost_notes = {
        "参考成本沿用 CC Switch 保存值，是估算使用价值，不能单独证明实际扣款。",
        "参考成本按 CC Switch 历史记录汇总，申请报销金额由你填写。",
    }
    for warning in analysis.get("warnings", []):
        message = (
            str(warning.get("message", warning)) if isinstance(warning, dict) else str(warning)
        )
        if message not in generic_cost_notes and message not in note_items:
            note_items.append(message)
    notes = "".join(f"<li>{_escape(item)}</li>" for item in note_items)
    source = safe_source(capture.get("source", {}))
    information = [
        ("项目", analysis.get("project_name", "全部项目")),
        ("统计期间", f"{analysis['start_date']} 至 {analysis['end_date']}（北京时间）"),
        ("用途说明", claim["purpose"] or "未填写"),
        ("参考成本", f"{summary['total_cost_usd']} USD"),
        ("申请报销金额", amount),
        ("金额依据", claim["amount_note"] or "未填写"),
        (
            "用量记录",
            f"明细 {summary.get('detail_count', 0)} 条；"
            f"历史汇总代表 {summary.get('rollup_record_count', 0)} 条；"
            f"总 Token {summary.get('total_tokens', 0)}",
        ),
    ]
    availability = _availability_basis(analysis)
    if availability:
        excluded = availability["excluded_summary"]
        information.append(("用量范围", "本次可用用量"))
        information.append((
            "已排除用量",
            f"{excluded.get('record_count', 0)} 条已占用或待核对记录，"
            f"参考成本 {excluded.get('total_cost_usd', '0')} USD",
        ))
    information_html = "".join(
        f"<dt>{_escape(label)}</dt><dd>{_escape(value)}</dd>" for label, value in information
    )
    source_information = [
        ("数据文件", source.get("name")),
        ("读取时间", _display_time(source.get("observed_at"))),
        ("记录编号", f"{batch['number']} · v{batch['version']}"),
        ("生成时间", _display_time(batch["created_at"])),
    ]
    source_html = "".join(
        f"<dt>{_escape(label)}</dt><dd>{_escape(value)}</dd>" for label, value in source_information
    )
    report = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>费用说明 · {_escape(batch["number"])} v{batch["version"]}</title>
<style>
body{{font:16px/1.65 'Segoe UI','Microsoft YaHei',sans-serif;color:#182638;
max-width:1100px;margin:36px auto;padding:0 24px}}
h1{{font-size:28px;line-height:1.4;margin:0 0 10px}}h2{{font-size:21px;margin:28px 0 14px}}
dl{{display:grid;grid-template-columns:150px minmax(0,1fr);gap:10px 20px}}
dt{{color:#526176}}dd{{margin:0;overflow-wrap:anywhere;white-space:pre-wrap}}
table{{border-collapse:collapse;width:100%;font-size:15px}}
th,td{{border:1px solid #d1dbe6;padding:9px;text-align:left;overflow-wrap:anywhere}}
th{{background:#f0f5f9;font-size:14px}}li{{margin:8px 0}}.hint{{color:#526176;font-size:14px}}
thead{{display:table-header-group}}.table-wrap{{overflow-x:auto}}
@media(max-width:600px){{body{{margin:24px auto;padding:0 18px}}
dl{{grid-template-columns:1fr;gap:4px}}
dd{{margin-bottom:12px}}h1{{font-size:24px}}}}
@media print{{body{{font-size:14px;max-width:none;margin:0;padding:0}}
@page{{size:A4;margin:16mm}}table{{font-size:12px}}th{{font-size:12px}}th,td{{padding:7px}}
h1{{font-size:23px}}h2{{font-size:18px}}dl{{grid-template-columns:120px minmax(0,1fr);gap:8px 14px}}
.table-wrap{{overflow:visible}}tr{{break-inside:avoid}}h2{{break-after:avoid}}}}
</style></head><body>
<h1>Codex 项目用量与费用说明</h1>
<p class="hint">{_escape(batch["number"])} · v{batch["version"]}
· {_escape(_display_time(batch["created_at"]))}</p>
<dl>{information_html}</dl>
<h2>每日用量与参考成本</h2><div class="table-wrap"><table><thead><tr>
<th>项目</th><th>日期</th><th>模型</th><th>明细数</th>
<th>汇总代表数</th><th>记录类型</th><th>参考成本 USD</th>
</tr></thead><tbody>{daily_rows}</tbody></table></div>
<h2>数据说明</h2><ul>{notes}</ul><dl>{source_html}</dl>
<p class="hint">逐条明细见“使用明细.csv”，文件校验及来源信息见“导出信息.json”。</p>
</body></html>"""
    return report.encode("utf-8")


def build_evidence(
    analysis: dict[str, Any], claim: dict[str, Any], batch: dict[str, Any], capture: dict[str, Any]
) -> tuple[bytes, str, dict[str, Any]]:
    """Generate once; callers must retain and redeliver the resulting bytes."""
    detail_rows = []
    for row in analysis["details"]:
        projected = {field: row.get(field) for field in DETAIL_COLUMNS}
        projected["time"] = row["time"]
        detail_rows.append(projected)
    files = {
        "使用明细.csv": _csv(DETAIL_COLUMNS, detail_rows),
        "每日汇总.csv": _csv(DAILY_COLUMNS, analysis["daily"]),
        "费用说明.html": _report(analysis, claim, batch, capture),
    }
    metadata = capture.get("metadata", {})
    unassigned = sum(1 for row in analysis["details"] if row.get("project_id") is None)
    unassigned += sum(
        int(row.get("request_count", 0))
        for row in analysis["rollups"]
        if row.get("project_id") is None
    )
    assignments = {
        row["record_key"]: {
            key: row.get(key)
            for key in ("project_id", "project_name", "assignment_origin", "pricing_status")
        }
        for row in analysis["details"] + analysis["rollups"]
    }
    manifest = {
        "manifest_version": 2,
        "application": {"name": "aha", "version": __version__},
        "batch": {key: batch[key] for key in ("id", "number", "version", "created_at")},
        "capture_id": capture["id"],
        "source": safe_source(capture.get("source", {})),
        "usage_snapshot_id": capture["usage_snapshot_id"],
        "metadata_snapshot_id": capture["metadata_snapshot_id"],
        "schema_version": capture.get("data", {}).get("schema_version", 23),
        "selection": {
            "start_date": analysis["start_date"],
            "end_date": analysis["end_date"],
            "timezone": "Asia/Shanghai",
            "utc_offset": "+08:00",
            "project_id": analysis.get("project_id", "all"),
            "project_name": analysis.get("project_name", "全部项目"),
        },
        "classification_revision": analysis["classification_revision"],
        "effective_basis": {
            "batch_id": batch["id"], "version": batch["version"],
            "effective_when_saved": True, "status_when_saved": "draft",
        },
        "summary": analysis["summary"],
        "claim": claim,
        "members": [
            {
                **{key: member[key] for key in MEMBER_FIELDS if key in member},
                **assignments[member["key"]],
            }
            for member in analysis["members"]
        ],
        "selection_coverage": analysis.get("selection_coverage", {}),
        "coverage": capture.get("coverage", {}),
        "metadata_coverage": {
            "matched_sessions": metadata.get("matched_sessions", 0),
            "total_sessions": metadata.get("total_sessions", 0),
        },
        "unassigned_record_count": unassigned,
        "warnings": analysis.get("warnings", []),
        "upstream_reference_commit": UPSTREAM_COMMIT,
        "cost_basis": ("CCS 保存的历史参考成本；未按当前价格重新计算；不代表官方账单或实际支付。"),
        "rollup_timezone_assumption": "历史日汇总缺少原始时区，以 Asia/Shanghai 整日解释。",
        "status_basis": "生成时为草稿；后续本地人工状态变化不改本包，不构成付款确认。",
        "files": {
            name: {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
            for name, raw in files.items()
        },
    }
    availability = _availability_basis(analysis)
    if availability is not None:
        manifest["availability"] = availability
    files["导出信息.json"] = canonical_bytes(manifest)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as package:
        for name, raw in files.items():
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            package.writestr(info, raw)
    project = safe_filename_component(str(analysis.get("project_name", "全部项目")))
    filename = (
        f"{project}_{analysis['start_date']}_{analysis['end_date']}_"
        f"{batch['number']}_v{batch['version']}.zip"
    )
    return output.getvalue(), filename, manifest
