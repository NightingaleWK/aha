"""Associate requested sessions with bounded metadata headers, never conversation turns."""

from __future__ import annotations

import io
import json
import os
import re
import sqlite3
import threading
import time
from collections import Counter
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import Any, BinaryIO, cast

from .domain import AppError

MAX_HEADER_BYTES = 512 * 1024
MAX_COMPRESSED_BYTES = 2 * 1024 * 1024
MAX_WINDOW_BYTES = 16 * 1024 * 1024
MAX_SCAN_FILES = 250_000
MAX_ROOTS = 16
MAX_SESSIONS = 20_000
_UUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
_DRIVE_PATH = re.compile(r"([A-Za-z]):[/\\](.*)")


class _HeaderError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code


class _CompressedInput(io.RawIOBase):
    """Limit compressed bytes consumed even when an input produces no output."""

    def __init__(self, stream: BinaryIO) -> None:
        self.stream = stream
        self.remaining = MAX_COMPRESSED_BYTES

    def readable(self) -> bool:
        return True

    def read(self, size: int = -1) -> bytes:
        if self.remaining <= 0:
            raise _HeaderError("compressed_header_limit")
        amount = self.remaining if size < 0 else min(size, self.remaining)
        data = self.stream.read(amount)
        self.remaining -= len(data)
        return data

    def readinto(self, buffer: Any) -> int:
        data = self.read(len(buffer))
        buffer[: len(data)] = data
        return len(data)


def _first_line(path: Path) -> bytes:
    try:
        with path.open("rb") as stream:
            if path.name.endswith(".jsonl.zst"):
                try:
                    import zstandard
                except ImportError as exc:
                    raise _HeaderError("compression_unavailable") from exc
                try:
                    decompressor = zstandard.ZstdDecompressor(max_window_size=MAX_WINDOW_BYTES)
                    bounded = cast(BinaryIO, _CompressedInput(stream))
                    with decompressor.stream_reader(bounded) as reader:
                        with io.BufferedReader(reader, buffer_size=8192) as buffered:
                            line = buffered.readline(MAX_HEADER_BYTES + 1)
                except zstandard.ZstdError as exc:
                    raise _HeaderError("invalid_compressed_header") from exc
            else:
                line = stream.readline(MAX_HEADER_BYTES + 1)
    except OSError as exc:
        raise _HeaderError("header_unavailable") from exc
    if len(line) > MAX_HEADER_BYTES:
        raise _HeaderError("header_limit")
    return line


def _header(path: Path) -> tuple[str, str, str | None]:
    try:
        value = json.loads(_first_line(path).decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError, RecursionError) as exc:
        raise _HeaderError("invalid_header") from exc
    if not isinstance(value, dict) or value.get("type") != "session_meta":
        raise _HeaderError("metadata_header_missing")
    payload = value.get("payload")
    if not isinstance(payload, dict):
        raise _HeaderError("invalid_header")
    session_id = payload.get("id")
    cwd = payload.get("cwd")
    if (
        not isinstance(session_id, str)
        or not session_id
        or len(session_id) > 256
        or not isinstance(cwd, str)
        or not cwd
        or len(cwd) > 8192
        or any(ord(char) < 32 for char in cwd)
    ):
        raise _HeaderError("invalid_header")
    parent = payload.get(
        "forked_from_id", payload.get("parent_thread_id", payload.get("parent_id"))
    )
    if parent is not None and (not isinstance(parent, str) or len(parent) > 256):
        raise _HeaderError("invalid_header")
    return session_id, cwd, parent or None


def _local_path(raw: str) -> Path:
    if os.name != "nt":
        match = _DRIVE_PATH.fullmatch(raw)
        if match:
            return Path("/mnt", match.group(1).lower(), match.group(2).replace("\\", "/"))
    return Path(raw)


def _index_candidates(
    root: Path,
    session_ids: set[str],
    errors: Counter[str],
    stopped: Callable[[], bool] = lambda: False,
) -> set[Path]:
    candidates: set[Path] = set()
    try:
        indexes = sorted(root.glob("state_*.sqlite"))[:16]
    except OSError:
        errors["index_unavailable"] += 1
        return candidates
    for index in indexes:
        if stopped():
            return candidates
        try:
            uri = index.resolve().as_uri() + "?mode=ro"
            with closing(sqlite3.connect(uri, uri=True, timeout=0.1)) as connection:
                connection.set_progress_handler(lambda: int(stopped()), 1000)
                connection.execute("PRAGMA query_only=ON")
                connection.execute("PRAGMA trusted_schema=OFF")
                ids = sorted(session_ids)
                for position in range(0, len(ids), 500):
                    if stopped():
                        return candidates
                    chunk = ids[position : position + 500]
                    placeholders = ",".join("?" for _ in chunk)
                    query = f"SELECT id, rollout_path FROM threads WHERE id IN ({placeholders})"
                    for session_id, raw in connection.execute(query, chunk):
                        if (
                            session_id in session_ids
                            and isinstance(raw, str)
                            and len(raw) <= 8192
                            and "\x00" not in raw
                            and raw.endswith((".jsonl", ".jsonl.zst"))
                        ):
                            candidate = _local_path(raw)
                            if candidate.is_file():
                                candidates.add(candidate)
        except (sqlite3.Error, OSError, ValueError):
            errors["index_unavailable"] += 1
    return candidates


def _candidate_paths(
    session_ids: set[str],
    roots: list[Path],
    errors: Counter[str],
    stopped: Callable[[], bool] = lambda: False,
) -> set[Path]:
    candidates: set[Path] = set()
    scanned = 0
    ordinary_ids = sorted(item for item in session_ids if not _UUID.fullmatch(item))
    for root in roots:
        if stopped():
            errors["scan_budget_exceeded"] += 1
            return candidates
        if not root.is_dir():
            errors["root_unavailable"] += 1
            continue
        candidates.update(_index_candidates(root, session_ids, errors, stopped))
        scan_roots = [
            root / name for name in ("sessions", "archived_sessions") if (root / name).is_dir()
        ]
        for scan_root in scan_roots or [root]:

            def walk_error(error: OSError) -> None:
                errors["directory_unavailable"] += 1

            for directory, subdirectories, filenames in os.walk(scan_root, onerror=walk_error):
                subdirectories.sort()
                for filename in sorted(filenames):
                    if stopped():
                        errors["scan_budget_exceeded"] += 1
                        return candidates
                    scanned += 1
                    if scanned > MAX_SCAN_FILES:
                        errors["scan_limit"] += 1
                        return candidates
                    if not filename.endswith((".jsonl", ".jsonl.zst")):
                        continue
                    found = set(_UUID.findall(filename)) & session_ids
                    if found or any(item in filename for item in ordinary_ids):
                        candidates.add(Path(directory, filename))
    return candidates


def scan_metadata(
    session_ids: set[str],
    roots: list[Path],
    *,
    cancel: threading.Event | None = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout

    def stopped() -> bool:
        return time.monotonic() >= deadline or (cancel is not None and cancel.is_set())

    if (
        not isinstance(session_ids, set)
        or len(session_ids) > MAX_SESSIONS
        or any(not isinstance(item, str) or not item or len(item) > 256 for item in session_ids)
        or not isinstance(roots, list)
        or len(roots) > MAX_ROOTS
    ):
        raise AppError("invalid_metadata_selection", "会话或元数据目录选择超出支持范围。")
    sessions: dict[str, dict[str, Any]] = {
        item: {"cwd": None, "status": "missing", "parent_id": None} for item in sorted(session_ids)
    }
    errors: Counter[str] = Counter()
    if not session_ids:
        return {"sessions": sessions, "matched_sessions": 0, "total_sessions": 0, "errors": []}
    paths = _candidate_paths(session_ids, [Path(root) for root in roots], errors, stopped)
    # One owner normalizes directory meaning for both matching and header conflicts.
    from .projects import canonical_path

    for path in sorted(paths, key=str):
        if stopped():
            errors["scan_budget_exceeded"] += 1
            break
        try:
            session_id, cwd, parent = _header(path)
            if session_id not in sessions:
                errors["header_session_mismatch"] += 1
                continue
            try:
                normalized = canonical_path(cwd)
            except AppError as exc:
                raise _HeaderError("invalid_directory") from exc
            existing = sessions[session_id]
            if existing["status"] == "conflict":
                continue
            if existing["status"] == "matched":
                different_cwd = canonical_path(existing["cwd"]) != normalized
                different_parent = bool(
                    existing["parent_id"] and parent and existing["parent_id"] != parent
                )
                if different_cwd or different_parent:
                    sessions[session_id] = {"cwd": None, "status": "conflict", "parent_id": None}
                    continue
                if not existing["parent_id"]:
                    existing["parent_id"] = parent
            else:
                sessions[session_id] = {"cwd": cwd, "status": "matched", "parent_id": parent}
        except _HeaderError as exc:
            errors[exc.code] += 1
    return {
        "sessions": sessions,
        "matched_sessions": sum(item["status"] == "matched" for item in sessions.values()),
        "total_sessions": len(sessions),
        "errors": [{"code": code, "count": count} for code, count in sorted(errors.items())],
    }
