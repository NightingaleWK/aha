"""Four-file evidence packages built only from a frozen analysis result."""

from __future__ import annotations

import csv
import hashlib
import html
import io
import re
import unicodedata
import zipfile
from decimal import Decimal, InvalidOperation
from typing import Any

from . import __version__
from .archive import safe_source
from .domain import AppError, canonical_bytes, decimal_text

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


def _report(
    analysis: dict[str, Any], claim: dict[str, Any], batch: dict[str, Any], capture: dict[str, Any]
) -> bytes:
    summary = analysis["summary"]
    amount = "未填写" if claim["amount"] is None else f"{claim['amount']} {claim['currency']}"
    daily_rows = "".join(
        "<tr>"
        + "".join(
            f"<td>{_escape(row.get(key))}</td>"
            for key in (
                "project_name",
                "date",
                "model",
                "detail_count",
                "rollup_record_count",
                "source_grain",
                "total_cost_usd",
            )
        )
        + "</tr>"
        for row in analysis["daily"]
    )
    warning_items = [
        "参考成本按 CCS 已保存的模型估算金额合计，不是官方账单、逐次扣款或付款证明。",
        "申请金额由使用者独立填写；未自动分摊订阅费用或换算汇率。",
        "历史日汇总没有逐次时间和会话；日期采用北京时间假设，不能据此还原明细。",
        "没有记录的日期不证明零消耗。会话本地请求 ID 不属于官方账单流水号。",
        "报销状态由本机使用者人工管理；生成和下载材料不代表已提交或已收款。",
    ]
    if summary.get("unpriced_count", 0):
        warning_items.append(f"含 {summary['unpriced_count']} 条未定价记录，零金额不等于免费。")
    for warning in analysis.get("warnings", []):
        warning_items.append(
            str(warning.get("message", warning)) if isinstance(warning, dict) else str(warning)
        )
    warnings = "".join(f"<li>{_escape(item)}</li>" for item in warning_items)
    source = safe_source(capture.get("source", {}))
    information = [
        ("项目", analysis.get("project_name", "全部项目")),
        ("期间（北京时间）", f"{analysis['start_date']} 至 {analysis['end_date']}，包含两端整日"),
        ("用途", claim["purpose"] or "未填写"),
        ("期间参考成本", f"{summary['total_cost_usd']} USD"),
        (
            "参考成本构成",
            f"逐条明细 {summary.get('detail_cost_usd', '0')} USD；"
            f"历史日汇总 {summary.get('rollup_cost_usd', '0')} USD",
        ),
        ("人工申请金额", amount),
        ("金额依据", claim["amount_note"] or "未填写"),
        (
            "用量记录",
            f"实际明细 {summary.get('detail_count', 0)} 条；"
            f"历史汇总代表 {summary.get('rollup_record_count', 0)} 条；"
            f"总 Token {summary.get('total_tokens', 0)}",
        ),
        (
            "来源",
            f"{source.get('name')}；"
            f"结构版本 {capture.get('data', {}).get('schema_version', 23)}；"
            f"观察时间 {source.get('observed_at')}",
        ),
        ("留存与归属版本", f"{capture['id']}；归属版本 {analysis.get('classification_revision')}"),
        (
            "目录识别覆盖",
            f"{capture.get('metadata', {}).get('matched_sessions', 0)} / "
            f"{capture.get('metadata', {}).get('total_sessions', 0)} 个会话；"
            "目录线索不等于业务归属证明",
        ),
    ]
    information_html = "".join(
        f"<dt>{_escape(label)}</dt><dd>{_escape(value)}</dd>" for label, value in information
    )
    report = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>费用说明 · {_escape(batch["number"])} v{batch["version"]}</title>
<style>
body{{font:14px/1.65 'Microsoft YaHei','Noto Sans CJK SC',sans-serif;
color:#152336;max-width:1100px;margin:36px auto;padding:0 22px}}
h1{{font-size:25px}}h2{{font-size:18px;margin-top:25px}}
dl{{display:grid;grid-template-columns:150px 1fr;gap:8px 16px}}
dt{{color:#526178}}dd{{margin:0;overflow-wrap:anywhere;white-space:pre-wrap}}
table{{border-collapse:collapse;width:100%;font-size:12px}}
th,td{{border:1px solid #cbd4e0;padding:7px;text-align:left;overflow-wrap:anywhere}}
th{{background:#edf2f9}}li{{margin:7px 0}}.hint{{color:#526178}}
thead{{display:table-header-group}}
@media print{{body{{max-width:none;margin:0;padding:0}}@page{{size:A4;margin:16mm}}
tr{{break-inside:avoid}}h2{{break-after:avoid}}}}
</style></head><body><h1>Codex 项目用量与费用说明</h1>
<p class="hint">本地批次 {_escape(batch["number"])} · 版本 {batch["version"]}
· 生成时间 {_escape(batch["created_at"])}</p>
<dl>{information_html}</dl>
<h2>每日与模型构成</h2><table><thead><tr><th>项目</th><th>日期</th><th>模型</th>
<th>明细数</th><th>历史代表数</th><th>来源粒度</th><th>参考成本 USD</th>
</tr></thead><tbody>{daily_rows}</tbody></table>
<h2>使用与覆盖说明</h2><ul>{warnings}</ul>
<p class="hint">本包另含使用明细 CSV、每日汇总 CSV 与导出信息 JSON；
清单记录来源指纹和文件 SHA-256，便于材料复查。</p>
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
        "manifest_version": 1,
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
