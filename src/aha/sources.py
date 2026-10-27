"""Read-only, WAL-aware bounded snapshots of CCS SQLite databases."""

from __future__ import annotations

import sqlite3
import time
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
    content_hash,
    source_name,
)

SNAPSHOT_TIMEOUT = 5.0
MAX_DATABASE_BYTES = 512 * 1024 * 1024
TABLE_FIELDS = {
    "proxy_request_logs": DETAIL_FIELDS,
    "usage_daily_rollups": ROLLUP_FIELDS,
    "model_pricing": PRICING_FIELDS,
}


def _validate_schema(connection: sqlite3.Connection) -> None:
    if connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
        raise AppError(
            "unsupported_schema", "仅支持 CC Switch 结构版本 23；请检查来源或选择兼容的 SQL 备份。"
        )
    tables = {
        row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    for table, fields in TABLE_FIELDS.items():
        if table not in tables:
            raise AppError(
                "incompatible_schema", "来源缺少必要用量表，请选择完整的 CC Switch 备份。"
            )
        columns = {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}
        if not set(fields).issubset(columns):
            raise AppError("incompatible_schema", "来源缺少必要用量字段，请选择结构兼容的备份。")


def _table_rows(
    connection: sqlite3.Connection, table: str, where: str = ""
) -> list[dict[str, Any]]:
    columns = ",".join(f'"{name}"' for name in TABLE_FIELDS[table])
    rows = connection.execute(
        f'SELECT {columns} FROM "{table}" {where} LIMIT {MAX_ROWS + 1}'
    ).fetchall()
    if len(rows) > MAX_ROWS:
        raise AppError("source_too_large", "用量记录过多，请选择较小的备份。", 413)
    return [dict(row) for row in rows]


def load_sqlite(path: Path) -> dict[str, Any]:
    """A live source is never opened immutable or copied without its WAL."""
    observed = datetime.now(UTC).isoformat()
    deadline = time.monotonic() + SNAPSHOT_TIMEOUT
    page_size = 4096

    def progress(status: int, remaining: int, total: int) -> None:
        if total * page_size > MAX_DATABASE_BYTES:
            raise AppError("source_too_large", "数据库快照过大，请选择较小的 SQL 备份。", 413)
        if time.monotonic() > deadline:
            raise AppError(
                "source_busy", "只读快照未能在限制内完成；请稍后重试或主动选择 SQL 备份。"
            )

    try:
        path = Path(path)
        if not path.is_file():
            raise AppError("source_unavailable", "找不到所选数据库；请检查文件或选择 SQL 备份。")
        if path.stat().st_size > MAX_DATABASE_BYTES:
            raise AppError("source_too_large", "数据库过大，请选择较小的 SQL 备份。", 413)
        uri = path.resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=0.25)) as original:
            original.execute("PRAGMA query_only=ON")
            original.execute("PRAGMA trusted_schema=OFF")
            page_size = original.execute("PRAGMA page_size").fetchone()[0]
            with closing(sqlite3.connect(":memory:")) as snapshot:
                original.backup(snapshot, pages=256, progress=progress, sleep=0.02)
                snapshot.execute("PRAGMA query_only=ON")
                snapshot.execute("PRAGMA trusted_schema=OFF")
                snapshot.row_factory = sqlite3.Row
                _validate_schema(snapshot)
                data = build_source_data(
                    _table_rows(
                        snapshot,
                        "proxy_request_logs",
                        "WHERE app_type='codex' AND data_source='codex_session'",
                    ),
                    _table_rows(
                        snapshot,
                        "usage_daily_rollups",
                        "WHERE app_type='codex' AND provider_id='_codex_session'",
                    ),
                    _table_rows(snapshot, "model_pricing"),
                    {},
                )
        projection = {key: data[key] for key in ("schema_version", "details", "rollups", "pricing")}
        data["source"] = {
            "kind": "sqlite",
            "name": source_name(str(path)),
            "fingerprint_kind": "allowed_projection_sha256",
            "fingerprint": content_hash(projection),
            "observed_at": observed,
        }
        return data
    except AppError:
        raise
    except (OSError, ValueError, sqlite3.Error) as exc:
        raise AppError(
            "source_unavailable", "无法完成数据库只读快照；请稍后重试或主动选择 SQL 备份。"
        ) from exc
