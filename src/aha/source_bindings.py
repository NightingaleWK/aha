"""Bind a local CCS instance without giving copied paths historical authority."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from .domain import AppError, content_hash, source_name

if TYPE_CHECKING:
    from .storage import Store

SETTINGS_KEY = "source_bindings_v1"
MAX_BINDINGS = 1024
MAX_BINDING_BYTES = 1024 * 1024
_HASH = re.compile(r"[0-9a-f]{64}\Z")


def _state_file() -> Path:
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        root = Path(local) if local else Path.home() / "AppData" / "Local"
    else:
        state = os.environ.get("XDG_STATE_HOME")
        root = Path(state) if state else Path.home() / ".local" / "state"
    return root / "aha-device" / "installation.json"


def installation_id() -> str:
    """A per-installation UUID lives outside all portable ledger directories."""
    path = _state_file()
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if path.is_symlink():
            raise ValueError("linked installation identity")
        try:
            with path.open("x", encoding="utf-8") as stream:
                value = uuid4().hex
                json.dump({"format_version": 1, "id": value}, stream)
                stream.flush()
                os.fsync(stream.fileno())
                return value
        except FileExistsError:
            # An independent launch may have exclusively created, but not yet
            # finished writing, the same small identity file.
            for attempt in range(21):
                try:
                    with path.open("rb") as stream:
                        raw = stream.read(1025)
                    if len(raw) > 1024:
                        raise ValueError("installation identity limit")
                    data = json.loads(raw)
                    if (
                        not isinstance(data, dict)
                        or type(data.get("format_version")) is not int
                        or data["format_version"] != 1
                    ):
                        raise ValueError("installation identity format")
                    identity = data.get("id")
                    if not isinstance(identity, str) or UUID(identity).hex != identity:
                        raise ValueError("installation identity value")
                    return identity
                except (ValueError, UnicodeError):
                    if attempt == 20:
                        raise
                    time.sleep(0.01)
    except (OSError, ValueError, UnicodeError, RecursionError) as exc:
        raise AppError(
            "device_identity_unavailable", "本机来源标识无法读取，请检查应用设置目录后重试。", 409
        ) from exc
    raise AssertionError("unreachable installation identity")


def _restore_id(store: Store) -> str | None:
    marker = store.data_dir / "restore-info.json"
    try:
        if marker.is_symlink():
            raise ValueError("linked restore marker")
        if not marker.exists():
            return None
        with marker.open("rb") as stream:
            raw = stream.read(4097)
        if len(raw) > 4096:
            raise ValueError("restore marker limit")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("restore marker format")
        identity = data.get("restore_id")
        if type(data.get("format_version")) is not int or data["format_version"] != 1:
            raise ValueError("restore marker format")
        if not isinstance(identity, str):
            raise ValueError("restore marker format")
        return UUID(identity).hex
    except (OSError, ValueError, UnicodeError, AttributeError, RecursionError) as exc:
        raise AppError(
            "source_binding_damaged", "还原资料的来源标识不完整，未连接当前来源。", 409
        ) from exc


def _identity(value: str | None) -> str:
    return value if value is not None else installation_id()


def _key(store: Store, path: Path, identity: str | None) -> tuple[str, str]:
    identity = _identity(identity)
    if not isinstance(identity, str) or not identity or len(identity) > 128 or "\0" in identity:
        raise AppError("invalid_device_identity", "本机来源标识无效。")
    try:
        location = str(path.resolve())
    except (OSError, RuntimeError, ValueError) as exc:
        raise AppError("source_unavailable", "当前来源路径无法读取。", 409) from exc
    # normcase retains case-sensitive Unix paths and normalizes Windows paths.
    key = content_hash([identity, os.path.normcase(location), _restore_id(store)])
    return key, location


def _bindings(connection: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    row = connection.execute("SELECT value FROM settings WHERE key=?", (SETTINGS_KEY,)).fetchone()
    if row is None:
        return {}
    try:
        if not isinstance(row[0], str) or len(row[0].encode("utf-8")) > MAX_BINDING_BYTES:
            raise ValueError("binding limit")
        data = json.loads(row[0])
        if (
            not isinstance(data, dict)
            or type(data.get("format_version")) is not int
            or data["format_version"] != 1
        ):
            raise ValueError("binding version")
        values = data.get("bindings")
        if not isinstance(values, dict) or len(values) > MAX_BINDINGS:
            raise ValueError("binding entries")
        checked: dict[str, dict[str, Any]] = {}
        for key, entry in values.items():
            if not isinstance(key, str) or not _HASH.fullmatch(key) or not isinstance(entry, dict):
                raise ValueError("binding entry")
            if not isinstance(entry.get("source_id"), str) or not _HASH.fullmatch(
                entry["source_id"]
            ):
                raise ValueError("binding source")
            checked[key] = entry
        return checked
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise AppError(
            "source_binding_damaged", "已保存的来源绑定无法校验，原历史资料保持不变。", 409
        ) from exc


def _descriptor(
    store: Store, connection: sqlite3.Connection, key: str, location: str
) -> dict[str, Any]:
    bindings = _bindings(connection)
    entry = bindings.get(key)
    history = connection.execute("SELECT 1 FROM usage_records LIMIT 1").fetchone() is not None
    legacy = connection.execute(
        "SELECT 1 FROM source_profiles WHERE kind='sqlite' LIMIT 1"
    ).fetchone() is not None
    if entry is not None:
        profile = connection.execute(
            "SELECT kind,location FROM source_profiles WHERE id=?", (entry["source_id"],)
        ).fetchone()
        if (
            profile is None
            or profile["kind"] != "sqlite"
            or not isinstance(profile["location"], str)
            or os.path.normcase(profile["location"]) != os.path.normcase(location)
        ):
            raise AppError("source_binding_damaged", "来源绑定与已保存的来源不一致。", 409)
    required = entry is None and (legacy or _restore_id(store) is not None)
    return {
        "required": required,
        "bound": entry is not None,
        "has_history": history,
        "source_name": source_name(location),
        "source_id": entry["source_id"] if entry else None,
        "reason": "需要确认新电脑来源，旧历史将继续保留。" if required else "",
        "confirmed_at": entry.get("confirmed_at") if entry else None,
    }


def binding_status(
    store: Store, path: Path, *, installation_id: str | None = None
) -> dict[str, Any]:
    key, location = _key(store, Path(path), installation_id)
    with store.read_connection() as connection:
        return _descriptor(store, connection, key, location)


def bind_source(
    store: Store, path: Path, reason: str, *, installation_id: str | None = None
) -> dict[str, Any]:
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 4000:
        raise AppError("reason_required", "请填写新电脑来源的接续说明。")
    key, location = _key(store, Path(path), installation_id)
    # Binding can precede the first _begin on an old/restored ledger. Recover
    # expired leases independently before checking for a genuinely active run.
    from .sync import _recover_failed_runs

    _recover_failed_runs(store)
    with store._staging_transaction(lambda: None):
        connection = store._db
        status = _descriptor(store, connection, key, location)
        if status["bound"]:
            return status
        if connection.execute("SELECT 1 FROM sync_runs WHERE state='running'").fetchone():
            raise AppError("sync_in_progress", "已有同步正在进行，请稍后连接来源。", 409)
        bindings = _bindings(connection)
        if len(bindings) >= MAX_BINDINGS:
            raise AppError("source_binding_limit", "已保存的来源绑定过多，请先保全资料。", 409)
        source_id = content_hash(["sqlite-instance", uuid4().hex])
        created = store._now()
        connection.execute(
            "INSERT INTO source_profiles(id,kind,name,location,trust,created_at) "
            "VALUES(?,'sqlite',?,?,'live',?)",
            (source_id, source_name(location), location, created),
        )
        bindings[key] = {"source_id": source_id, "confirmed_at": created, "reason": reason.strip()}
        encoded = store._encode({"format_version": 1, "bindings": bindings})
        if len(encoded.encode("utf-8")) > MAX_BINDING_BYTES:
            raise AppError("source_binding_limit", "已保存的来源绑定过多，请先保全资料。", 409)
        connection.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) "
            "DO UPDATE SET value=excluded.value",
            (SETTINGS_KEY, encoded),
        )
        return _descriptor(store, connection, key, location)


def source_id_for_sync(
    store: Store, path: Path, *, installation_id: str | None = None
) -> str:
    identity = _identity(installation_id)
    status = binding_status(store, path, installation_id=identity)
    if status["required"]:
        raise AppError(
            "source_binding_required",
            "需要先确认新电脑来源；已保存的历史仍可查看，请在数据来源中连接当前电脑。",
            409,
        )
    if not status["bound"]:
        status = bind_source(store, path, "首次连接本机CCS来源", installation_id=identity)
    source_id = status["source_id"]
    if not isinstance(source_id, str):
        raise AppError("source_binding_damaged", "当前来源绑定不完整。", 409)
    return source_id
