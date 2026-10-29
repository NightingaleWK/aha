"""Store owns all connections, transaction boundaries and the local ledger facade."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Any
from uuid import uuid4

from .decimal_sql import register
from .domain import AppError, canonical_bytes
from .migrations import initialize, sqlite_wal_safe


class Store:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self._lock = threading.RLock()
        self._closed = False
        self._readers: set[sqlite3.Connection] = set()
        self._reader_lock = threading.Lock()
        self._sync_cancel = threading.Event()
        if not sqlite_wal_safe():
            raise AppError(
                "unsupported_sqlite", "SQLite 运行时缺少必要并发修复，请使用新版完整程序。", 500
            )
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            for directory in ("objects", "packages", "temporary"):
                (self.data_dir / directory).mkdir(exist_ok=True)
            self._db = sqlite3.connect(
                self.data_dir / "aha.sqlite3",
                timeout=5,
                check_same_thread=False,
                isolation_level=None,
            )
            self._db.row_factory = sqlite3.Row
            self._db.execute("PRAGMA foreign_keys=ON")
            self._db.execute("PRAGMA trusted_schema=OFF")
            register(self._db)
            # Reject old trial databases before changing their journal mode.
            with self._transaction():
                initialize(self)
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=FULL")
        except AppError:
            if hasattr(self, "_db"):
                self._db.close()
            raise
        except (OSError, sqlite3.Error) as exc:
            if hasattr(self, "_db"):
                self._db.close()
            raise AppError("storage_unavailable", "本地资料目录无法打开或结构损坏。", 500) from exc

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat(timespec="microseconds")

    @staticmethod
    def _encode(value: Any) -> str:
        return canonical_bytes(value).decode("utf-8")

    @staticmethod
    def _decode(value: str) -> Any:
        try:
            return json.loads(value)
        except (TypeError, ValueError) as exc:
            raise AppError("storage_damaged", "本地资料内容损坏，无法读取。", 409) from exc

    def _ensure_open(self) -> None:
        if self._closed:
            raise AppError("store_closed", "本地资料库已关闭。", 409)

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        with self._lock:
            self._ensure_open()
            try:
                self._db.execute("BEGIN IMMEDIATE")
                yield
                self._db.execute("COMMIT")
            except BaseException as exc:
                if self._db.in_transaction:
                    self._db.execute("ROLLBACK")
                if isinstance(exc, sqlite3.Error):
                    if "locked" in str(exc).lower() or "busy" in str(exc).lower():
                        raise AppError("store_busy", "资料正在更新，请稍后重试。", 409) from exc
                    raise AppError(
                        "storage_write_failed", "本地资料保存失败，请检查空间和目录权限。", 500
                    ) from exc
                raise

    @contextmanager
    def _staging_transaction(
        self, check: Callable[[], None], source_deadline: float | None = None
    ) -> Iterator[None]:
        # A source DELETE-mode reader must never wait indefinitely on our Python
        # writer lock. Limit both this wait and SQLite's subsequent busy wait;
        # ordinary business transactions keep their existing wait semantics.
        deadline = monotonic() + 0.25
        if source_deadline is not None:
            deadline = min(deadline, source_deadline)
        while True:
            check()
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise AppError("store_busy", "本地资料正在更新，同步未完成，请稍后重试。", 409)
            if self._lock.acquire(timeout=min(0.02, remaining)):
                break
        previous_timeout: int | None = None
        try:
            self._ensure_open()
            check()
            previous_timeout = self._db.execute("PRAGMA busy_timeout").fetchone()[0]
            # Windows' busy-handler sleeps can overshoot its configured count;
            # keep headroom inside the separate 250ms staging deadline.
            milliseconds = min(100, max(1, int((deadline - monotonic()) * 1000)))
            self._db.execute(f"PRAGMA busy_timeout={milliseconds}")
            with self._transaction():
                yield
                check()
        finally:
            if previous_timeout is not None:
                self._db.execute(f"PRAGMA busy_timeout={previous_timeout}")
            self._lock.release()

    @contextmanager
    def read_connection(self) -> Iterator[sqlite3.Connection]:
        # Never acquire the writer RLock while opening a reader: WAL readers must
        # remain usable while a long publish transaction holds that lock.
        self._ensure_open()
        connection = sqlite3.connect(
            (self.data_dir / "aha.sqlite3").resolve().as_uri() + "?mode=ro",
            uri=True,
            timeout=2,
            isolation_level=None,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA trusted_schema=OFF")
        register(connection)
        with self._reader_lock:
            if self._closed:
                connection.close()
                self._ensure_open()
            self._readers.add(connection)
        try:
            connection.execute("BEGIN")
            yield connection
        finally:
            with suppress(sqlite3.Error):
                connection.execute("ROLLBACK")
            with self._reader_lock:
                self._readers.discard(connection)
                connection.close()

    def revisions(self, connection: sqlite3.Connection | None = None) -> dict[str, int]:
        if connection is None:
            with self.read_connection() as reader:
                return self.revisions(reader)
        values = dict(
            connection.execute(
                "SELECT key,value FROM settings WHERE key IN ('data_revision','re"
                "vision','claim_revision')"
            )
        )
        return {
            "data_revision": int(values["data_revision"]),
            "classification_revision": int(values["revision"]),
            "claim_revision": int(values["claim_revision"]),
        }

    def _advance_revision(self) -> None:
        self._db.execute("UPDATE settings SET value=CAST(value AS INTEGER)+1 WHERE key='revision'")

    def claim_revision(self) -> int:
        return self.revisions()["claim_revision"]

    def canonical_record_key(
        self, key: str, connection: sqlite3.Connection | None = None
    ) -> str:
        from .ledger import canonical_record_key

        if connection is None:
            with self.read_connection() as reader:
                return canonical_record_key(reader, key)
        return canonical_record_key(connection, key)

    def _file_path(self, relative: str) -> Path:
        path = Path(relative)
        if len(path.parts) != 2 or path.parts[0] not in {"objects", "packages", "temporary"}:
            raise AppError("storage_damaged", "本地资料路径无效。", 409)
        result = self.data_dir / path
        if result.resolve().parent != (self.data_dir / path.parts[0]).resolve():
            raise AppError("storage_damaged", "本地资料路径无效。", 409)
        return result

    def _read_file(self, relative: str) -> bytes:
        try:
            return self._file_path(relative).read_bytes()
        except OSError as exc:
            raise AppError("artifact_missing", "原资料文件缺失或无法读取。", 409) from exc

    def publish_file(self, relative: str, temporary_path: Path) -> None:
        target = self._file_path(relative)
        try:
            with temporary_path.open("r+b") as stream:
                stream.flush()
                os.fsync(stream.fileno())
            if target.exists():
                with target.open("rb") as first, temporary_path.open("rb") as second:
                    if (
                        hashlib.file_digest(first, "sha256").digest()
                        != hashlib.file_digest(second, "sha256").digest()
                    ):
                        raise AppError("artifact_damaged", "原资料校验失败，未覆盖原文件。", 409)
                temporary_path.unlink()
                return
            os.replace(temporary_path, target)
            if sys.platform != "win32" and os.name == "posix":
                fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
        except OSError as exc:
            raise AppError("storage_write_failed", "本地材料保存失败。", 500) from exc

    def _write_immutable(self, relative: str, data: bytes) -> None:
        temporary = self._file_path("temporary/" + uuid4().hex + ".tmp")
        try:
            with temporary.open("xb") as stream:
                stream.write(data)
            self.publish_file(relative, temporary)
        finally:
            temporary.unlink(missing_ok=True)

    def close(self) -> None:
        self._sync_cancel.set()
        with self._lock:
            if not self._closed:
                self._closed = True
                for reader in tuple(self._readers):
                    with suppress(sqlite3.Error):
                        reader.interrupt()
                self._db.close()

    def ledger_status(self) -> dict[str, Any]:
        from .queries import ledger_status

        return ledger_status(self)

    def sync_status(self, run_id: str | None = None) -> dict[str, Any] | None:
        from .sync import sync_status

        return sync_status(self, run_id)

    def sync_data(
        self, data: dict[str, Any], metadata: dict[str, Any] | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        from .sync import sync_data

        return sync_data(self, data, metadata, **kwargs)

    def sync_sql(
        self, data: bytes, name: str, metadata_roots: list[Path] | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        from .sync import sync_sql

        return sync_sql(self, data, name, metadata_roots, **kwargs)

    def sync_sqlite(
        self, path: Path, metadata_roots: list[Path] | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        from .sync import sync_sqlite

        return sync_sqlite(self, path, metadata_roots, **kwargs)

    def refresh_metadata(self, roots: list[Path]) -> dict[str, Any]:
        from .sync import refresh_metadata

        return refresh_metadata(self, roots)

    def config(self) -> dict[str, Any]:
        from .projects import configuration

        return configuration(self)

    def save_project(
        self, project_id: str | None, name: str, description: str, directories: list[str]
    ) -> dict[str, Any]:
        from .projects import save_project

        return save_project(self, project_id, name, description, directories)

    def assign(
        self, rows: list[dict[str, Any]], project_id: str | None, grain: str = "detail"
    ) -> dict[str, Any]:
        from .domain import record_key

        return self.assign_keys(
            [row.get("record_key") or record_key(row, grain) for row in rows], project_id
        )

    def assign_keys(self, keys: list[str], project_id: str | None) -> dict[str, Any]:
        from .projects import assign_keys

        return assign_keys(self, keys, project_id)

    def assign_sessions(self, session_ids: list[str], project_id: str | None) -> dict[str, Any]:
        from .projects import assign_sessions

        return assign_sessions(self, session_ids, project_id)

    def assign_session(self, session_id: str, project_id: str | None) -> dict[str, Any]:
        return self.assign_sessions([session_id], project_id)

    def analyze(
        self, start_date: str, end_date: str, project_id: str = "all", **kwargs: Any
    ) -> dict[str, Any]:
        from .queries import analyze

        return analyze(self, start_date, end_date, project_id, **kwargs)

    def analysis_details(self, analysis: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        from .queries import analysis_details

        return analysis_details(self, analysis, **kwargs)

    def iter_analysis_rows(
        self, analysis: dict[str, Any], connection: sqlite3.Connection | None = None
    ) -> Iterator[dict[str, Any]]:
        from .queries import iter_analysis_rows

        yield from iter_analysis_rows(self, analysis, connection)

    def iter_analysis_daily(
        self, analysis: dict[str, Any], connection: sqlite3.Connection | None = None
    ) -> Iterator[dict[str, Any]]:
        from .queries import iter_analysis_daily

        yield from iter_analysis_daily(self, analysis, connection)

    def validate_analysis(
        self,
        analysis: dict[str, Any],
        connection: sqlite3.Connection | None = None,
        *,
        check_claims: bool = True,
    ) -> None:
        from .queries import validate_analysis

        validate_analysis(self, analysis, connection, check_claims=check_claims)

    def refresh_availability(
        self, connection: sqlite3.Connection, scopes: set[str] | None = None
    ) -> None:
        from .ledger import refresh_availability

        refresh_availability(connection, scopes)

    def list_reconciliations(self) -> list[dict[str, Any]]:
        from .ledger import list_reconciliations

        return list_reconciliations(self)

    def resolve_reconciliation(
        self,
        case_id: str,
        choice: str,
        reason: str,
        expected_generation: int | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        from .ledger import resolve_reconciliation

        return resolve_reconciliation(
            self, case_id, choice, reason, expected_generation, idempotency_key
        )

    def create_batch(
        self,
        analysis: dict[str, Any],
        claim: dict[str, Any],
        idempotency_key: str,
        batch_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        from .batches import create_batch

        return create_batch(self, analysis, claim, idempotency_key, batch_id, **kwargs)

    def list_batches(self) -> list[dict[str, Any]]:
        from .batches import list_batches

        return list_batches(self)

    def batch_detail(self, batch_id: str) -> dict[str, Any]:
        from .batches import batch_detail

        return batch_detail(self, batch_id)

    def replay_create(self, idempotency_key: str, request_signature: str) -> dict[str, Any] | None:
        from .batches import replay_create

        return replay_create(self, idempotency_key, request_signature)

    def set_status(
        self, batch_id: str, version: int, status: str, expected_generation: int | None = None
    ) -> dict[str, Any]:
        from .batches import set_status

        return set_status(self, batch_id, version, status, expected_generation)

    def withdraw_batch(
        self, batch_id: str, expected_generation: int, reason: str, idempotency_key: str
    ) -> dict[str, Any]:
        from .batches import lifecycle_action

        return lifecycle_action(
            self, "withdraw", batch_id, expected_generation, reason, idempotency_key
        )

    def void_batch(
        self, batch_id: str, expected_generation: int, reason: str, idempotency_key: str
    ) -> dict[str, Any]:
        from .batches import lifecycle_action

        return lifecycle_action(
            self, "void", batch_id, expected_generation, reason, idempotency_key
        )

    def download(self, batch_id: str, version: int) -> tuple[Path, str]:
        from .batches import download

        return download(self, batch_id, version)

    def overlaps(
        self, analysis: dict[str, Any], exclude_batch_id: str | None = None
    ) -> list[dict[str, Any]]:
        from .batches import overlaps

        return overlaps(self, analysis, exclude_batch_id)
