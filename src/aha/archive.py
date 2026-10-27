"""Allowlisted, immutable retained usage and session-metadata projections."""

from __future__ import annotations

import gzip
import io
import json
import re
import zlib
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from .domain import (
    BEIJING,
    AppError,
    build_source_data,
    canonical_bytes,
    content_hash,
    source_name,
)

if TYPE_CHECKING:
    from .storage import Store

FORMAT_VERSION = 1
MAX_OBJECT_BYTES = 512 * 1024 * 1024


def usage_projection(data: dict[str, Any]) -> dict[str, Any]:
    if data.get("schema_version") != 23:
        raise AppError("unsupported_schema", "仅支持 CCS 结构版本 23，未保存不兼容来源。")
    for key in ("details", "rollups", "pricing"):
        incoming = data.get(key, [])
        if not isinstance(incoming, list) or not all(isinstance(row, dict) for row in incoming):
            raise AppError("invalid_capture", "来源用量或价格依据结构无效，请重新读取来源。")
    projected = build_source_data(
        data.get("details", []), data.get("rollups", []), data.get("pricing", []), {}
    )
    return {
        "format_version": FORMAT_VERSION,
        "adapter_version": 1,
        "schema_version": 23,
        **{key: projected[key] for key in ("details", "rollups", "pricing")},
    }


def metadata_projection(
    metadata: dict[str, Any], session_ids: set[str] | None = None
) -> dict[str, Any]:
    sessions = metadata.get("sessions", {})
    if not isinstance(sessions, dict):
        raise AppError("invalid_metadata", "会话目录依据结构无效。")
    if session_ids is not None:
        sessions = {
            key: sessions.get(key, {"cwd": None, "status": "missing", "parent_id": None})
            for key in session_ids
        }
    projected = {}
    for session_id, session in sorted(sessions.items()):
        if not isinstance(session_id, str) or not isinstance(session, dict):
            raise AppError("invalid_metadata", "会话目录依据结构无效。")
        status = session.get("status", "missing")
        cwd = session.get("cwd")
        parent = session.get("parent_id")
        if status not in {"matched", "missing", "conflict"}:
            raise AppError("invalid_metadata", "会话目录识别状态无效。")
        if cwd is not None and (not isinstance(cwd, str) or len(cwd) > 8192 or "\0" in cwd):
            raise AppError("invalid_metadata", "会话目录依据结构无效。")
        if status == "matched" and not cwd:
            raise AppError("invalid_metadata", "已识别的会话缺少目录依据。")
        projected[session_id] = {
            "cwd": cwd,
            "status": status,
            "parent_id": parent if isinstance(parent, str) else None,
        }
    errors = metadata.get("errors", [])
    if isinstance(errors, int):
        errors = [{"code": "metadata_read_error", "count": errors}] if errors else []
    if not isinstance(errors, list):
        raise AppError("invalid_metadata", "会话识别错误统计无效。")
    safe_errors = []
    for error in errors:
        if (
            not isinstance(error, dict)
            or not isinstance(error.get("code"), str)
            or not re.fullmatch(r"[a-z0-9_]{1,64}", error["code"])
            or not isinstance(error.get("count"), int)
            or error["count"] < 0
        ):
            raise AppError("invalid_metadata", "会话识别错误统计无效。")
        safe_errors.append({"code": error["code"], "count": error["count"]})
    return {
        "format_version": FORMAT_VERSION,
        "sessions": projected,
        "errors": sorted(safe_errors, key=lambda error: error["code"]),
    }


def safe_source(source: dict[str, Any]) -> dict[str, Any]:
    name = source_name(str(source.get("name", "未命名来源")))
    return {
        key: source.get(key) for key in ("kind", "fingerprint_kind", "fingerprint", "observed_at")
    } | {"name": name[:255]}


def _save_object(store: Store, kind: str, value: dict[str, Any]) -> str:
    fingerprint = content_hash(value)
    relative = f"objects/{kind}-{fingerprint}.json.gz"
    if store._file_path(relative).exists():
        _load_object(store, kind, fingerprint)
        return fingerprint
    encoded = canonical_bytes(value)
    store._write_immutable(relative, gzip.compress(encoded, mtime=0))
    _load_object(store, kind, fingerprint)
    return fingerprint


def _load_object(store: Store, kind: str, fingerprint: str) -> dict[str, Any]:
    raw = store._read_file(f"objects/{kind}-{fingerprint}.json.gz")
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as compressed:
            decoded = compressed.read(MAX_OBJECT_BYTES + 1)
        if len(decoded) > MAX_OBJECT_BYTES:
            raise ValueError("size")
        result = json.loads(decoded)
        if not isinstance(result, dict) or content_hash(result) != fingerprint:
            raise ValueError("hash")
        if result.get("format_version") != FORMAT_VERSION:
            raise AppError("unsupported_archive", "历史留存格式不兼容，请使用对应版本的程序。", 409)
        if kind == "usage" and (
            result.get("schema_version") != 23 or result.get("adapter_version") != 1
        ):
            raise AppError("unsupported_archive", "历史留存数据版本不兼容。", 409)
        return result
    except (OSError, ValueError, TypeError, EOFError, zlib.error) as exc:
        raise AppError("capture_damaged", "历史留存缺失或校验失败，无法使用该版本。", 409) from exc


def _coverage(usage: dict[str, Any]) -> dict[str, Any]:
    details, rollups = usage["details"], usage["rollups"]
    dates = [
        datetime.fromtimestamp(float(row["created_at"]), BEIJING).date().isoformat()
        for row in details
    ]
    dates.extend(str(row["date"]) for row in rollups)
    represented = sum(int(row.get("request_count") or 0) for row in rollups)
    return {
        "counts": {
            "detail_count": len(details),
            "rollup_count": len(rollups),
            "rollup_record_count": represented,
            "record_count": len(details) + represented,
        },
        "coverage": {
            "start_date": min(dates) if dates else None,
            "end_date": max(dates) if dates else None,
        },
    }


def retain(store: Store, data: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    usage = usage_projection(data)
    session_ids = {row["session_id"] for row in usage["details"] if row.get("session_id")}
    meta = metadata_projection(metadata, session_ids)
    source = safe_source(data.get("source", {}))
    source["observed_at"] = source.get("observed_at") or store._now()
    with store._transaction():
        usage_hash = _save_object(store, "usage", usage)
        metadata_hash = _save_object(store, "metadata", meta)
        identity = content_hash(
            {
                "usage": usage_hash,
                "metadata": metadata_hash,
                "source": {k: v for k, v in source.items() if k != "observed_at"},
            }
        )
        existing = store._db.execute(
            "SELECT id FROM captures WHERE identity=?", (identity,)
        ).fetchone()
        capture_id = existing["id"] if existing else str(uuid4())
        if not existing:
            store._db.execute(
                "INSERT INTO captures(id,identity,usage_hash,metadata_hash,"
                "source_json,created_at,info_json) "
                "VALUES(?,?,?,?,?,?,?)",
                (
                    capture_id,
                    identity,
                    usage_hash,
                    metadata_hash,
                    store._encode(source),
                    store._now(),
                    store._encode(_coverage(usage)),
                ),
            )
        store._db.execute(
            "INSERT INTO observations(capture_id,observed_at,source_json) VALUES(?,?,?)",
            (capture_id, source["observed_at"], store._encode(source)),
        )
        return descriptor(store, capture_id)


def descriptor(store: Store, capture_id: str) -> dict[str, Any]:
    row = store._db.execute("SELECT * FROM captures WHERE id=?", (capture_id,)).fetchone()
    if row is None:
        raise AppError("capture_not_found", "未找到该历史留存，请重新选择。", 404)
    observed = store._db.execute(
        "SELECT observed_at FROM observations WHERE capture_id=? ORDER BY id DESC LIMIT 1",
        (capture_id,),
    ).fetchone()
    return {
        "id": row["id"],
        "capture_id": row["id"],
        "source": store._decode(row["source_json"]),
        "created_at": row["created_at"],
        "last_observed_at": observed[0] if observed else row["created_at"],
        "usage_snapshot_id": row["usage_hash"],
        "metadata_snapshot_id": row["metadata_hash"],
        **store._decode(row["info_json"]),
    }


def list_captures(store: Store) -> list[dict[str, Any]]:
    with store._lock:
        store._ensure_open()
        return [
            descriptor(store, row[0])
            for row in store._db.execute("SELECT id FROM captures ORDER BY created_at DESC,id")
        ]


def get_capture(store: Store, capture_id: str) -> dict[str, Any]:
    with store._lock:
        store._ensure_open()
        result = descriptor(store, capture_id)
        usage = _load_object(store, "usage", result["usage_snapshot_id"])
        metadata = _load_object(store, "metadata", result["metadata_snapshot_id"])
        # Validate internal shapes even when someone has replaced an index and object together.
        expected_metadata = {"errors": [], **metadata}
        if usage_projection(usage) != usage or metadata_projection(metadata) != expected_metadata:
            raise AppError("capture_damaged", "历史留存内容结构无效。", 409)
        result["data"] = {k: usage[k] for k in ("schema_version", "details", "rollups", "pricing")}
        result["data"]["source"] = result["source"]
        sessions = metadata["sessions"]
        result["metadata"] = {
            "sessions": sessions,
            "total_sessions": len(sessions),
            "matched_sessions": sum(s["status"] == "matched" for s in sessions.values()),
            "errors": metadata.get("errors", []),
        }
        return result
