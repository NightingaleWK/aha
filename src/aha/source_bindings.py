"""Bind confirmed source locations to this installation and ledger instance."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from uuid import UUID, uuid4

from .codex_sessions import CodexSource
from .domain import AppError, content_hash, parse_date

if TYPE_CHECKING:
    from .storage import Store

_HASH = re.compile(r"[0-9a-f]{64}\Z")
CODEX_BINDINGS_KEY = "codex_source_"


@dataclass(frozen=True)
class CodexBinding:
    source: CodexSource
    source_id: str
    since: str | None


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


def _codex_context(store: Store) -> str:
    return content_hash([installation_id(), _restore_id(store)])


def _codex_binding(context: str, key: str, value: str) -> CodexBinding | None:
    try:
        if len(value.encode("utf-8")) > 32768:
            raise ValueError("binding limit")
        data = json.loads(value)
        if not isinstance(data, dict) or not _HASH.fullmatch(str(data.get("context", ""))):
            raise ValueError("binding context")
        if data["context"] != context:
            return None
        kind: Literal["windows", "wsl"] = (
            "windows" if key == f"{CODEX_BINDINGS_KEY}windows" else "wsl"
        )
        root, distribution = data.get("root"), data.get("distribution")
        if not isinstance(root, str) or not root or len(root) > 4096 or "\0" in root:
            raise ValueError("binding root")
        if kind == "wsl":
            if (
                not isinstance(distribution, str) or not distribution
                or len(distribution) > 256 or "\0" in distribution
            ):
                raise ValueError("binding distribution")
        elif distribution is not None:
            raise ValueError("binding distribution")
        since = data.get("since")
        if since is not None:
            since = parse_date(since).isoformat()
        location = os.path.normcase(root) if kind == "windows" else root
        source_id = content_hash(["codex-source", context, kind, distribution, location, since])
        return CodexBinding(CodexSource(kind, root, distribution), source_id, since)
    except (AppError, ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise AppError(
            "source_binding_damaged", "已保存的 Codex 来源配置无法读取，原历史资料仍可查看。", 409
        ) from exc


def configured_codex_sources(store: Store) -> dict[str, CodexBinding]:
    with store.read_connection() as connection:
        rows = connection.execute(
            "SELECT key,value FROM settings WHERE key IN (?,?) ORDER BY key",
            (f"{CODEX_BINDINGS_KEY}windows", f"{CODEX_BINDINGS_KEY}wsl"),
        ).fetchall()
    if not rows:
        return {}
    context = _codex_context(store)
    bindings: dict[str, CodexBinding] = {}
    for key, value in rows:
        if binding := _codex_binding(context, key, value):
            bindings[binding.source.kind] = binding
    return bindings


def history_default_since(store: Store) -> str | None:
    with store.read_connection() as connection:
        if connection.execute(
            "SELECT 1 FROM source_profiles WHERE kind NOT IN ('codex_windows','codex_wsl') LIMIT 1"
        ).fetchone() is None:
            return None
        last = connection.execute("""
            SELECT r.day FROM usage_records r JOIN usage_versions v ON v.id=r.version_id
            WHERE r.suppressed=0 AND
                (r.kind='rollup' OR json_extract(v.payload_json,'$.data_source')='codex_session')
            ORDER BY r.day DESC LIMIT 1
        """).fetchone()
    return str(last[0]) if last else None


def bind_codex_source(
    store: Store, source: CodexSource, expected_id: str | None, *, since: str | None = None
) -> None:
    from .sync import _recover_failed_runs

    context = _codex_context(store)
    key = f"{CODEX_BINDINGS_KEY}{source.kind}"
    encoded = store._encode({
        "context": context,
        "root": source.root,
        "distribution": source.distribution,
        "since": since,
    })
    desired = _codex_binding(context, key, encoded)
    assert desired is not None
    _recover_failed_runs(store)
    with store._staging_transaction(lambda: None):
        connection = store._db
        if connection.execute("SELECT 1 FROM sync_runs WHERE state='running'").fetchone():
            raise AppError("sync_in_progress", "请等待当前同步结束后再确认来源。", 409)
        row = connection.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        current = _codex_binding(context, key, row[0]) if row is not None else None
        if current == desired:
            return
        if (current.source_id if current else None) != expected_id:
            raise AppError("stale_source_binding", "来源配置已更新，请重新打开设置。", 409)
        connection.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) "
            "DO UPDATE SET value=excluded.value",
            (key, encoded),
        )
