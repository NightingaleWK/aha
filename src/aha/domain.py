"""Shared, deterministic contracts for CCS usage projections and arithmetic."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

Row = dict[str, Any]
SCHEMA_VERSION = 23
BEIJING = timezone(timedelta(hours=8), name="Asia/Shanghai")
TOKEN_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_creation_tokens",
)
DETAIL_COST_FIELDS = (
    "input_cost_usd",
    "output_cost_usd",
    "cache_read_cost_usd",
    "cache_creation_cost_usd",
    "total_cost_usd",
    "cost_multiplier",
)
DETAIL_FIELDS = (
    "request_id",
    "provider_id",
    "app_type",
    "model",
    "request_model",
    *TOKEN_FIELDS,
    *DETAIL_COST_FIELDS,
    "session_id",
    "created_at",
    "data_source",
    "pricing_model",
    "input_token_semantics",
)
ROLLUP_KEY_FIELDS = (
    "date",
    "app_type",
    "provider_id",
    "model",
    "request_model",
    "pricing_model",
)
ROLLUP_FIELDS = (
    *ROLLUP_KEY_FIELDS,
    "request_count",
    *TOKEN_FIELDS,
    "total_cost_usd",
    "input_token_semantics",
)
PRICING_FIELDS = (
    "model_id",
    "display_name",
    "input_cost_per_million",
    "output_cost_per_million",
    "cache_read_cost_per_million",
    "cache_creation_cost_per_million",
)
MAX_ROWS = 1_000_000
_INTEGER = re.compile(r"[+-]?\d+\Z", re.ASCII)
_DECIMAL = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\Z", re.ASCII)
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z", re.ASCII)


class AppError(Exception):
    """An actionable public error; messages never contain source payloads."""

    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def decimal_value(value: Any, *, nonnegative: bool = False) -> Decimal:
    """Parse bounded decimal text, never pass money through binary floats."""
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise AppError("invalid_number", "来源包含无效金额；请检查备份的数字格式。")
    raw = str(value)
    if len(raw) > 512 or not _DECIMAL.fullmatch(raw):
        raise AppError("invalid_number", "来源包含无效金额；请检查备份的数字格式。")
    try:
        result = Decimal(raw)
    except InvalidOperation as exc:
        raise AppError("invalid_number", "来源包含无效金额；请检查备份的数字格式。") from exc
    exponent = result.as_tuple().exponent
    if (
        not result.is_finite()
        or not isinstance(exponent, int)
        or abs(exponent) > 100
        or len(result.as_tuple().digits) > 201
        or result.adjusted() > 100
        or (nonnegative and result < 0)
    ):
        raise AppError("invalid_number", "来源金额超出支持范围或为负数。")
    return result


def decimal_text(value: Any) -> str:
    # Sums can have more significant digits than an individual bounded source value.
    if isinstance(value, Decimal):
        exponent = value.as_tuple().exponent
        if (
            not value.is_finite()
            or not isinstance(exponent, int)
            or abs(exponent) > 200
            or len(value.as_tuple().digits) > 256
        ):
            raise AppError("invalid_number", "金额超出支持范围。")
        result = value
    else:
        result = decimal_value(value)
    return "0" if not result else format(result, "f")


def integer_value(value: Any, *, maximum: int = 2**63 - 1) -> int:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise AppError("invalid_number", "来源包含无效的整数或 Token 数。")
    raw = str(value)
    if len(raw) > 20 or not _INTEGER.fullmatch(raw):
        raise AppError("invalid_number", "来源包含无效的整数或 Token 数。")
    result = int(raw)
    if not 0 <= result <= maximum:
        raise AppError("invalid_number", "来源包含负数或超出范围的整数。")
    return result


def parse_date(value: Any) -> date:
    if not isinstance(value, str) or not _ISO_DATE.fullmatch(value):
        raise AppError("invalid_date", "日期必须使用有效的 YYYY-MM-DD 格式。")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise AppError("invalid_date", "日期必须使用有效的 YYYY-MM-DD 格式。") from exc


def fresh_input(row: Mapping[str, Any]) -> int:
    original = integer_value(row["input_tokens"])
    cached = integer_value(row["cache_read_tokens"])
    created = integer_value(row["cache_creation_tokens"])
    semantics = integer_value(row["input_token_semantics"], maximum=2)
    if semantics == 0:
        return original - cached if original >= cached else original
    if semantics == 1:
        return original - cached - created if original >= cached + created else original
    return original


def record_key(row: Mapping[str, Any], grain: str = "detail") -> str:
    if grain == "detail":
        identity = [row.get(key) for key in ("app_type", "data_source", "request_id")]
    elif grain in ("rollup", "daily_rollup"):
        identity = [row.get(key) for key in ROLLUP_KEY_FIELDS]
        grain = "rollup"
    else:
        raise AppError("invalid_grain", "不支持此来源粒度。")
    return f"{grain}:{content_hash(identity)}"


def row_fingerprint(row: Mapping[str, Any], grain: str = "detail") -> str:
    fields: tuple[str, ...]
    if grain == "detail":
        fields = DETAIL_FIELDS
    elif grain in ("rollup", "daily_rollup"):
        fields = ROLLUP_FIELDS
    else:
        raise AppError("invalid_grain", "不支持此来源粒度。")
    return content_hash({key: row.get(key) for key in fields})


def source_name(value: str) -> str:
    """Basename handling also works for Windows paths when running in WSL."""
    basename = value.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    return "".join(char for char in basename if ord(char) >= 32)[:200] or "未命名来源"


def _text(value: Any, *, nullable: bool = False, empty: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or len(value) > 4096 or "\x00" in value:
        raise AppError("invalid_data", "来源包含无效的标识或文本字段。")
    if not value and not empty:
        raise AppError("invalid_data", "来源缺少必要的标识字段。")
    return value


def normalize_row(row: Mapping[str, Any], grain: str) -> Row:
    fields = DETAIL_FIELDS if grain == "detail" else ROLLUP_FIELDS
    if not set(fields).issubset(row):
        raise AppError(
            "incompatible_schema", "来源缺少必要用量字段；请使用结构版本 23 的完整备份。"
        )
    result: Row = {}
    nullable = {"session_id", "request_model", "pricing_model"} if grain == "detail" else set()
    for key in fields:
        value = row[key]
        if key in TOKEN_FIELDS or key in ("request_count", "input_token_semantics"):
            result[key] = integer_value(
                value, maximum=2 if key == "input_token_semantics" else 2**63 - 1
            )
        elif key in DETAIL_COST_FIELDS:
            result[key] = decimal_text(decimal_value(value, nonnegative=True))
        elif key == "created_at":
            timestamp = integer_value(value, maximum=253402271999 - 8 * 3600)
            try:
                datetime.fromtimestamp(timestamp, BEIJING)
            except (ValueError, OverflowError, OSError) as exc:
                raise AppError("invalid_date", "来源事件时间超出支持范围。") from exc
            result[key] = timestamp
        elif key == "date":
            result[key] = parse_date(value).isoformat()
        else:
            result[key] = _text(
                value,
                nullable=key in nullable,
                empty=key in nullable or key in {"request_model", "pricing_model"},
            )
    return result


def normalize_price(row: Mapping[str, Any]) -> Row:
    if not set(PRICING_FIELDS).issubset(row):
        raise AppError("incompatible_schema", "来源缺少必要价格依据字段。")
    normalized: Row = {"model_id": _text(row["model_id"]),
                       "display_name": _text(row["display_name"], empty=True)}
    for key in PRICING_FIELDS[2:]:
        normalized[key] = decimal_text(decimal_value(row[key], nonnegative=True))
    return normalized


def build_source_data(
    details: Iterable[Mapping[str, Any]],
    rollups: Iterable[Mapping[str, Any]],
    pricing: Iterable[Mapping[str, Any]],
    source: Row,
) -> Row:
    """One projection/validation boundary shared by SQLite and literal SQL."""
    result: Row = {"schema_version": SCHEMA_VERSION, "details": [], "rollups": [], "pricing": []}
    for grain, rows, target in (("detail", details, "details"), ("rollup", rollups, "rollups")):
        seen: set[str] = set()
        for index, row in enumerate(rows):
            if index >= MAX_ROWS:
                raise AppError("source_too_large", "用量记录过多，请选择较小的来源备份。", 413)
            if row.get("app_type") != "codex":
                continue
            if grain == "detail" and row.get("data_source") != "codex_session":
                continue
            if grain == "rollup" and row.get("provider_id") != "_codex_session":
                continue
            normalized = normalize_row(row, grain)
            identity = record_key(normalized, grain)
            if identity in seen:
                raise AppError(
                    "duplicate_key", "来源中存在重复用量主键；未导入，请重新导出完整备份。"
                )
            seen.add(identity)
            result[target].append(normalized)
        result[target].sort(key=lambda item: record_key(item, grain))
    wanted = {
        row.get("pricing_model") or row["model"] for row in result["details"] + result["rollups"]
    }
    pricing_seen: set[str] = set()
    for row in pricing:
        model_id = row.get("model_id")
        if model_id not in wanted:
            continue
        normalized = normalize_price(row)
        if model_id in pricing_seen:
            raise AppError("duplicate_key", "来源中存在重复价格主键；未导入。")
        pricing_seen.add(str(model_id))
        result["pricing"].append(normalized)
    result["pricing"].sort(key=lambda item: item["model_id"])
    result["source"] = source
    return result
