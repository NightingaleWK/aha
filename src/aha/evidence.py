"""Bounded, deterministic four-file packages from an immutable ledger selection."""

from __future__ import annotations

import csv
import hashlib
import html
import os
import re
import shutil
import tempfile
import unicodedata
import zipfile
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, BinaryIO

from . import __version__
from .domain import BEIJING, AppError, canonical_bytes, decimal_text

UPSTREAM_COMMIT = "e55d8a21b3897b595b746e9f2139716b2931641d"
MANIFEST_VERSION = 3
COPY_BYTES = 1024 * 1024
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
    "version_id",
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
    "request_model",
    "pricing_model",
    "project_id",
    "project_name",
    "assignment_origin",
    "pricing_status",
)
SUMMARY_FIELDS = (
    "record_count",
    "detail_count",
    "rollup_record_count",
    "rollup_count",
    "unpriced_count",
    "fresh_input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_creation_tokens",
    "total_tokens",
    "total_cost_usd",
    "detail_cost_usd",
    "rollup_cost_usd",
    "source_grain",
)
RowFactory = Callable[[], Iterable[dict[str, Any]]]


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


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


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


def _summary(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {key: value[key] for key in SUMMARY_FIELDS if key in value}


def _availability_basis(analysis: dict[str, Any]) -> dict[str, Any] | None:
    original = analysis.get("availability")
    if not isinstance(original, dict):
        return None
    result: dict[str, Any] = {
        "mode": original.get("mode"),
        "claim_revision": original.get("claim_revision"),
    }
    for key in ("matched_summary", "available_summary", "excluded_summary"):
        result[key] = _summary(original.get(key))
    groups = []
    for group in original.get("excluded_groups", []):
        if not isinstance(group, dict):
            continue
        projected = {
            key: group[key]
            for key in (
                "reason",
                "row_count",
                "record_count",
                "detail_count",
                "rollup_record_count",
                "total_cost_usd",
            )
            if key in group
        }
        projected["owners"] = [
            {
                key: owner[key]
                for key in ("batch_id", "number", "version", "status", "lifecycle")
                if key in owner
            }
            for owner in group.get("owners", [])
            if isinstance(owner, dict)
        ]
        groups.append(projected)
    result["excluded_groups"] = groups
    return result


def _warnings(analysis: dict[str, Any]) -> list[str | dict[str, Any]]:
    result: list[str | dict[str, Any]] = []
    for warning in analysis.get("warnings", []):
        if isinstance(warning, str):
            result.append(warning)
        elif isinstance(warning, dict) and isinstance(warning.get("message"), str):
            result.append(
                {key: warning[key] for key in ("code", "message", "count") if key in warning}
            )
    return result


def _write_csv(path: Path, columns: tuple[str, ...], rows: Iterable[dict[str, Any]]) -> int:
    count = 0
    with path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.writer(output, lineterminator="\r\n")
        writer.writerow(columns)
        for row in rows:
            writer.writerow(csv_cell(row.get(column)) for column in columns)
            count += 1
    return count


def _write_report(
    path: Path,
    analysis: dict[str, Any],
    claim: dict[str, Any],
    batch: dict[str, Any],
    daily_rows: Iterable[dict[str, Any]],
) -> None:
    summary = _summary(analysis["summary"])
    amount = "未填写" if claim["amount"] is None else f"{claim['amount']} {claim['currency']}"
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
    basis = _availability_basis(analysis)
    if basis:
        excluded = basis["excluded_summary"]
        information.append(("用量范围", "本次可用用量"))
        information.append(
            (
                "已排除用量",
                f"{excluded.get('record_count', 0)} 条已占用或待核对记录，"
                f"参考成本 {excluded.get('total_cost_usd', '0')} USD",
            )
        )
    notes = [
        "参考成本为 CC Switch 保存的模型用量估算；申请报销金额由申请人填写。",
        "统计日期按北京时间计算，包含开始和结束日期。",
    ]
    if summary.get("rollup_record_count"):
        notes.append("历史日汇总按来源完整记录纳入，没有补成逐条调用。")
    if summary.get("unpriced_count"):
        notes.append(f"有 {summary['unpriced_count']} 条记录未计价，参考成本不完整。")
    generic_notes = {
        "参考成本沿用 CC Switch 保存值，是估算使用价值，不能单独证明实际扣款。",
        "参考成本按 CC Switch 历史记录汇总，申请报销金额由你填写。",
    }
    for warning in _warnings(analysis):
        message = warning if isinstance(warning, str) else warning["message"]
        if message not in generic_notes and message not in notes:
            notes.append(message)
    with path.open("w", encoding="utf-8", newline="\n") as output:
        output.write("""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>费用说明</title>
<style>body{font:16px/1.65 'Segoe UI','Microsoft YaHei',sans-serif;color:#182638;
max-width:1100px;margin:36px auto;padding:0 24px}h1{font-size:28px;line-height:1.4}
h2{font-size:21px;margin-top:28px}dl{display:grid;grid-template-columns:150px minmax(0,1fr);
gap:10px 20px}dt{color:#526176}dd{margin:0;overflow-wrap:anywhere;white-space:pre-wrap}
table{border-collapse:collapse;width:100%;font-size:15px}th,td{border:1px solid #d1dbe6;
padding:9px;text-align:left;overflow-wrap:anywhere}th{background:#f0f5f9;font-size:14px}
.hint{color:#526176;font-size:14px}.table-wrap{overflow-x:auto}
@media(max-width:600px){body{margin:24px auto;padding:0 18px}dl{grid-template-columns:1fr}}
@media print{@page{size:A4;margin:16mm}body{font-size:14px;margin:0;padding:0;max-width:none}
table{font-size:12px}th{font-size:12px}th,td{padding:7px}h1{font-size:23px}
dl{grid-template-columns:120px minmax(0,1fr)}.table-wrap{overflow:visible}
thead{display:table-header-group}tr{break-inside:avoid}h2{break-after:avoid}}</style></head><body>
<h1>Codex 项目用量与费用说明</h1>""")
        output.write(
            f'<p class="hint">{_escape(batch["number"])} · v{batch["version"]}'
            f" · {_escape(_display_time(batch['created_at']))}</p><dl>"
        )
        for label, value in information:
            output.write(f"<dt>{_escape(label)}</dt><dd>{_escape(value)}</dd>")
        output.write(
            '</dl><h2>每日用量与参考成本</h2><div class="table-wrap"><table><thead><tr>'
            "<th>项目</th><th>日期</th><th>模型</th><th>明细数</th>"
            "<th>汇总代表数</th><th>记录类型</th><th>参考成本 USD</th>"
            "</tr></thead><tbody>"
        )
        grains = {"detail": "逐条明细", "daily_rollup": "历史日汇总", "mixed": "明细与汇总"}
        for row in daily_rows:
            output.write("<tr>")
            for key in (
                "project_name",
                "date",
                "model",
                "detail_count",
                "rollup_record_count",
                "source_grain",
                "total_cost_usd",
            ):
                value = row.get(key)
                if key == "source_grain":
                    value = grains.get(str(value), value)
                output.write(f"<td>{_escape(value)}</td>")
            output.write("</tr>")
        output.write("</tbody></table></div><h2>数据说明</h2><ul>")
        for note in notes:
            output.write(f"<li>{_escape(note)}</li>")
        output.write(
            '</ul><p class="hint">数据来自 aha 本地保存的 CC Switch Codex 用量。'
            "本材料保存生成时的用量与申请说明，后续本地状态变化不改本包。"
            "逐条明细见“使用明细.csv”，文件校验和冻结依据见“导出信息.json”。</p>"
            "</body></html>"
        )


def _write_manifest(
    output: BinaryIO, metadata: dict[str, Any], members: Iterable[dict[str, Any]]
) -> int:
    """Write a deterministic JSON object without ever constructing its member array."""
    output.write(b"{")
    count = 0
    for index, key in enumerate(sorted((*metadata.keys(), "members"))):
        if index:
            output.write(b",")
        output.write(canonical_bytes(key) + b":")
        if key != "members":
            output.write(canonical_bytes(metadata[key]))
            continue
        output.write(b"[")
        for member in members:
            if count:
                output.write(b",")
            output.write(
                canonical_bytes(
                    {field: member[field] for field in MEMBER_FIELDS if field in member}
                )
            )
            count += 1
        output.write(b"]")
    output.write(b"}")
    return count


def build_evidence(
    destination: Path,
    analysis: dict[str, Any],
    claim: dict[str, Any],
    batch: dict[str, Any],
    *,
    rows: RowFactory,
    daily_rows: RowFactory,
    members: RowFactory,
) -> tuple[Path, str, dict[str, Any]]:
    """Build into a private path; caller atomically publishes it with billing metadata."""
    claim = validate_claim(claim)
    destination.parent.mkdir(parents=True, exist_ok=True)
    metadata: dict[str, Any] = {
        "manifest_version": MANIFEST_VERSION,
        "application": {"name": "aha", "version": __version__},
        "batch": {key: batch[key] for key in ("id", "number", "version", "created_at")},
        "source_schema_version": 23,
        "ledger": {
            key: analysis[key]
            for key in ("data_revision", "classification_revision", "claim_revision")
            if key in analysis
        },
        "selection": {
            "start_date": analysis["start_date"],
            "end_date": analysis["end_date"],
            "timezone": "Asia/Shanghai",
            "utc_offset": "+08:00",
            "project_id": analysis.get("project_id", "all"),
            "project_name": analysis.get("project_name", "全部项目"),
        },
        "selection_hash": analysis.get("selection_hash"),
        "effective_basis": {
            "batch_id": batch["id"],
            "version": batch["version"],
            "effective_when_saved": True,
            "status_when_saved": "draft",
        },
        "summary": _summary(analysis["summary"]),
        "claim": claim,
        "warnings": _warnings(analysis),
        "upstream_reference_commit": UPSTREAM_COMMIT,
        "cost_basis": "CCS 保存的历史参考成本；未按当前价格重新计算；不代表官方账单或实际支付。",
        "rollup_timezone_assumption": "历史日汇总缺少原始时区，以 Asia/Shanghai 整日解释。",
        "status_basis": "生成时为草稿；后续本地人工状态变化不改本包，不构成支付确认。",
    }
    basis = _availability_basis(analysis)
    if basis is not None:
        metadata["availability"] = basis
    try:
        with tempfile.TemporaryDirectory(prefix=".evidence-", dir=destination.parent) as workspace:
            directory = Path(workspace)
            files = {
                name: directory / name
                for name in ("使用明细.csv", "每日汇总.csv", "费用说明.html", "导出信息.json")
            }
            detail_count = _write_csv(
                files["使用明细.csv"],
                DETAIL_COLUMNS,
                (row for row in rows() if row["kind"] == "detail"),
            )
            _write_csv(files["每日汇总.csv"], DAILY_COLUMNS, daily_rows())
            _write_report(files["费用说明.html"], analysis, claim, batch, daily_rows())
            metadata["files"] = {
                name: {"sha256": file_hash(path), "bytes": path.stat().st_size}
                for name, path in files.items()
                if name != "导出信息.json"
            }
            with files["导出信息.json"].open("wb") as output:
                count = _write_manifest(output, metadata, members())
            if (
                detail_count != analysis["summary"]["detail_count"]
                or count != analysis["member_count"]
            ):
                raise AppError("selection_changed", "冻结材料与用量选择不一致，请重新预览。", 409)
            with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as package:
                for name, path in files.items():
                    info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.external_attr = 0o600 << 16
                    with (
                        path.open("rb") as source,
                        package.open(info, "w", force_zip64=True) as target,
                    ):
                        shutil.copyfileobj(source, target, COPY_BYTES)
            with destination.open("r+b") as output:
                output.flush()
                os.fsync(output.fileno())
    except AppError:
        destination.unlink(missing_ok=True)
        raise
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        destination.unlink(missing_ok=True)
        raise AppError("package_write_failed", "材料生成失败，请检查本地空间后重试。", 500) from exc
    project = safe_filename_component(str(analysis.get("project_name", "全部项目")))
    filename = (
        f"{project}_{analysis['start_date']}_{analysis['end_date']}_"
        f"{batch['number']}_v{batch['version']}.zip"
    )
    return (
        destination,
        filename,
        {
            "sha256": file_hash(destination),
            "member_count": count,
            "manifest_version": MANIFEST_VERSION,
        },
    )
