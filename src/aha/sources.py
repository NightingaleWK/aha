"""Bounded, read-only consistent projection of CCS tables, including committed WAL."""

from __future__ import annotations

import hashlib
import sqlite3
import threading
import time
from collections.abc import Callable
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .domain import (
    DETAIL_FIELDS,
    MAX_ROWS,
    PRICING_FIELDS,
    ROLLUP_FIELDS,
    SCHEMA_VERSION,
    AppError,
    build_source_data,
    canonical_bytes,
    content_hash,
    source_name,
)

SNAPSHOT_TIMEOUT = 5.0
MAX_DATABASE_BYTES = 512 * 1024 * 1024  # Allowed projection budget, not whole source-file size.
TABLE_FIELDS = {
    "proxy_request_logs": DETAIL_FIELDS,
    "usage_daily_rollups": ROLLUP_FIELDS,
    "model_pricing": PRICING_FIELDS,
}


def _validate_schema(connection: sqlite3.Connection) -> None:
    if connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
        raise AppError("unsupported_schema", "仅支持 CC Switch 结构版本 23。")
    tables = {
        row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    for table, fields in TABLE_FIELDS.items():
        if table not in tables:
            raise AppError("incompatible_schema", "来源缺少必要用量表。")
        columns = {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}
        if not set(fields).issubset(columns):
            raise AppError("incompatible_schema", "来源缺少必要用量字段。")


def scan_sqlite(
    path: Path,
    sink: Callable[[str, dict[str, Any]], None],
    *,
    cancel: threading.Event | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """All allowed tables share ONE read transaction; unrelated pages are never copied."""
    observed = datetime.now(UTC).isoformat()
    deadline = time.monotonic() + (SNAPSHOT_TIMEOUT if timeout is None else timeout)
    digest = hashlib.sha256()
    size = 0

    def check() -> None:
        if cancel is not None and cancel.is_set():
            raise AppError("sync_cancelled", "同步已取消。", 409)
        if time.monotonic() > deadline:
            raise AppError("source_busy", "来源读取超过时限，请稍后重试或主动选择 SQL 备份。", 409)

    def progress() -> int:
        return int((cancel is not None and cancel.is_set()) or time.monotonic() > deadline)

    try:
        path = Path(path)
        if not path.is_file():
            raise AppError("source_unavailable", "找不到所选数据库，请检查文件或选择 SQL 备份。")
        uri = path.resolve().as_uri() + "?mode=ro"
        with closing(
            sqlite3.connect(uri, uri=True, timeout=0.25, isolation_level=None)
        ) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only=ON")
            connection.execute("PRAGMA trusted_schema=OFF")
            connection.set_progress_handler(progress, 1000)
            connection.execute("BEGIN")
            try:
                _validate_schema(connection)
                filters = {
                    "proxy_request_logs": "WHERE app_type='codex' AND data_source='codex_session'",
                    "usage_daily_rollups": ("WHERE app_type='codex' "
                                           "AND provider_id='_codex_session'"),
                    "model_pricing": (
                        "WHERE model_id IN (SELECT COALESCE(NULLIF(pricing_model,''),mode"
                        "l) FROM proxy_request_logs WHERE app_type='codex' AND data_sourc"
                        "e='codex_session' UNION SELECT COALESCE(NULLIF(pricing_model,'')"
                        ",model) FROM usage_daily_rollups WHERE app_type='codex' AND prov"
                        "ider_id='_codex_session')"
                    ),
                }
                for table, fields in TABLE_FIELDS.items():
                    check()
                    columns = ",".join(f'"{field}"' for field in fields)
                    with closing(connection.execute(
                        f'SELECT {columns} FROM "{table}" {filters[table]}'
                    )) as cursor:
                        count = 0
                        while rows := cursor.fetchmany(256):
                            check()
                            for row in rows:
                                count += 1
                                if count > MAX_ROWS:
                                    raise AppError(
                                        "source_too_large", "单次来源记录超过上限。", 413
                                    )
                                projected = dict(row)
                                encoded = canonical_bytes(projected)
                                size += len(encoded)
                                if size > MAX_DATABASE_BYTES:
                                    raise AppError(
                                        "source_too_large", "来源允许用量投影超过大小限制。", 413
                                    )
                                digest.update(encoded)
                                sink(table, projected)
                                check()
                check()
            finally:
                connection.set_progress_handler(None, 0)
                connection.execute("ROLLBACK")
        return {
            "kind": "sqlite",
            "name": source_name(str(path)),
            "fingerprint_kind": "allowed_projection_stream_sha256",
            "fingerprint": digest.hexdigest(),
            "observed_at": observed,
        }
    except AppError:
        raise
    except sqlite3.Error as exc:
        check()
        if "locked" in str(exc).lower() or "busy" in str(exc).lower():
            raise AppError("source_busy", "来源正在更新，请稍后重试。", 409) from exc
        raise AppError(
            "source_unavailable", "无法完成来源只读读取，请检查文件或选择 SQL 备份。"
        ) from exc
    except (OSError, ValueError) as exc:
        raise AppError(
            "source_unavailable", "无法完成来源只读读取，请检查文件或选择 SQL 备份。"
        ) from exc


def load_sqlite(path: Path) -> dict[str, Any]:
    """Bounded convenience loader. Production synchronisation uses scan_sqlite directly."""
    rows: dict[str, list[dict[str, Any]]] = {table: [] for table in TABLE_FIELDS}
    source = scan_sqlite(path, lambda table, row: rows[table].append(row))
    data = build_source_data(
        rows["proxy_request_logs"], rows["usage_daily_rollups"], rows["model_pricing"], source
    )
    source["fingerprint_kind"] = "allowed_projection_sha256"
    source["fingerprint"] = content_hash(
        {key: data[key] for key in ("schema_version", "details", "rollups", "pricing")}
    )
    return data
