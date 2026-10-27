"""The single application database, atomic file writer and public Store facade."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .domain import AppError, canonical_bytes

SCHEMA_VERSION = 2

_SCHEMA = """
CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
INSERT INTO settings VALUES('revision','0');
CREATE TABLE projects(id TEXT PRIMARY KEY,name TEXT NOT NULL,description TEXT NOT NULL,
 directories_json TEXT NOT NULL);
CREATE TABLE overrides(record_key TEXT PRIMARY KEY,content_hash TEXT NOT NULL,
 project_id TEXT NOT NULL REFERENCES projects(id));
CREATE TABLE captures(id TEXT PRIMARY KEY,identity TEXT NOT NULL UNIQUE,
 usage_hash TEXT NOT NULL,metadata_hash TEXT NOT NULL,
 source_json TEXT NOT NULL,created_at TEXT NOT NULL,info_json TEXT NOT NULL);
CREATE TABLE observations(id INTEGER PRIMARY KEY,capture_id TEXT NOT NULL REFERENCES captures(id),
 observed_at TEXT NOT NULL,source_json TEXT NOT NULL);
CREATE TABLE batches(id TEXT PRIMARY KEY,number INTEGER NOT NULL UNIQUE,created_at TEXT NOT NULL);
CREATE TABLE revisions(batch_id TEXT NOT NULL REFERENCES batches(id),version INTEGER NOT NULL,
 created_at TEXT NOT NULL,status TEXT NOT NULL CHECK(status IN ('draft','submitted','reimbursed')),
 status_updated_at TEXT NOT NULL,analysis_json TEXT NOT NULL,claim_json TEXT NOT NULL,
 members_json TEXT NOT NULL,overlaps_json TEXT NOT NULL,
 zip_path TEXT NOT NULL,zip_hash TEXT NOT NULL,file_name TEXT NOT NULL,frozen_hash TEXT NOT NULL,
 PRIMARY KEY(batch_id,version));
CREATE TABLE status_events(id INTEGER PRIMARY KEY,batch_id TEXT NOT NULL,version INTEGER NOT NULL,
 old_status TEXT,new_status TEXT NOT NULL,changed_at TEXT NOT NULL,
 FOREIGN KEY(batch_id,version) REFERENCES revisions(batch_id,version));
CREATE TABLE idempotency(key TEXT PRIMARY KEY,payload_hash TEXT NOT NULL,
 batch_id TEXT NOT NULL,version INTEGER NOT NULL,
 FOREIGN KEY(batch_id,version) REFERENCES revisions(batch_id,version));
"""


class Store:
    """Serialize SQLite and immutable-object operations across HTTP threads."""

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self._lock = threading.RLock()
        self._closed = False
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            (self.data_dir / "objects").mkdir(exist_ok=True)
            (self.data_dir / "packages").mkdir(exist_ok=True)
            self._db = sqlite3.connect(
                self.data_dir / "aha.sqlite3",
                timeout=15,
                check_same_thread=False,
                isolation_level=None,
            )
            self._db.row_factory = sqlite3.Row
            self._db.execute("PRAGMA foreign_keys=ON")
            from .migrations import initialize

            with self._transaction():
                initialize(self, _SCHEMA)
            self._db.execute("SELECT value FROM settings WHERE key='revision'").fetchone()[0]
        except (OSError, sqlite3.Error, TypeError) as exc:
            if hasattr(self, "_db"):
                self._db.close()
            raise AppError(
                "storage_unavailable", "本地资料目录无法打开或结构损坏，请选择可写目录。", 500
            ) from exc
        except AppError:
            if hasattr(self, "_db"):
                self._db.close()
            raise

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
                    if isinstance(exc, sqlite3.OperationalError) and (
                        "locked" in str(exc).lower() or "busy" in str(exc).lower()
                    ):
                        raise AppError("store_busy", "资料正在更新，请稍后重试。", 409) from exc
                    raise AppError(
                        "storage_write_failed", "本地资料保存失败，请检查可用空间和目录权限。", 500
                    ) from exc
                raise

    def _advance_revision(self) -> None:
        self._db.execute("UPDATE settings SET value=CAST(value AS INTEGER)+1 WHERE key='revision'")

    def _file_path(self, relative: str) -> Path:
        path = self.data_dir / relative
        if path.parent not in {
            self.data_dir / "objects",
            self.data_dir / "packages",
        } or path.name in {"", ".", ".."}:
            raise AppError("storage_damaged", "本地资料路径无效。", 409)
        return path

    def _read_file(self, relative: str) -> bytes:
        try:
            return self._file_path(relative).read_bytes()
        except OSError as exc:
            raise AppError(
                "artifact_missing", "原留存文件缺失或无法读取，请保留现场并检查本地资料。", 409
            ) from exc

    def _write_immutable(self, relative: str, data: bytes) -> None:
        path = self._file_path(relative)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            if path.exists():
                if hashlib.sha256(path.read_bytes()).digest() != hashlib.sha256(data).digest():
                    raise AppError("artifact_damaged", "原留存文件校验失败，未覆盖原文件。", 409)
                return
            with temporary.open("xb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            if temporary.read_bytes() != data:
                raise AppError(
                    "storage_write_failed", "本地文件写入校验失败，未保存为可用资料。", 500
                )
            os.replace(temporary, path)
            if os.name == "posix":
                directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        except OSError as exc:
            raise AppError(
                "storage_write_failed", "本地文件保存失败，请检查可用空间和目录权限。", 500
            ) from exc
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._db.close()
                self._closed = True

    def retain(self, data: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
        from .archive import retain

        return retain(self, data, metadata)

    def list_captures(self) -> list[dict[str, Any]]:
        from .archive import list_captures

        return list_captures(self)

    def get_capture(self, capture_id: str) -> dict[str, Any]:
        from .archive import get_capture

        return get_capture(self, capture_id)

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
        from .projects import assign

        return assign(self, rows, project_id, grain)

    def overlaps(
        self, analysis: dict[str, Any], exclude_batch_id: str | None = None
    ) -> list[dict[str, Any]]:
        from .batches import overlaps

        return overlaps(self, analysis, exclude_batch_id)

    def create_batch(
        self,
        analysis: dict[str, Any],
        claim: dict[str, Any],
        idempotency_key: str,
        batch_id: str | None = None,
        *,
        expected_generation: int | None = None,
        expected_active_version: int | None = None,
        request_signature: str | None = None,
    ) -> dict[str, Any]:
        from .batches import create_batch

        return create_batch(
            self,
            analysis,
            claim,
            idempotency_key,
            batch_id,
            expected_generation=expected_generation,
            expected_active_version=expected_active_version,
            request_signature=request_signature,
        )

    def list_batches(self) -> list[dict[str, Any]]:
        from .batches import list_batches

        return list_batches(self)

    def batch_detail(self, batch_id: str) -> dict[str, Any]:
        from .batches import batch_detail

        return batch_detail(self, batch_id)

    def set_status(
        self,
        batch_id: str,
        version: int,
        status: str,
        expected_generation: int | None = None,
    ) -> dict[str, Any]:
        from .batches import set_status

        return set_status(self, batch_id, version, status, expected_generation)

    def download(self, batch_id: str, version: int) -> tuple[bytes, str]:
        from .batches import download

        return download(self, batch_id, version)

    def claim_revision(self) -> int:
        with self._lock:
            self._ensure_open()
            row = self._db.execute(
                "SELECT value FROM settings WHERE key='claim_revision'"
            ).fetchone()
            return int(row[0])

    def claim_snapshot(self, exclude_batch_id: str | None = None) -> dict[str, Any]:
        from .batches import claim_snapshot

        return claim_snapshot(self, exclude_batch_id)

    def replay_create(self, idempotency_key: str, request_signature: str) -> dict[str, Any] | None:
        from .batches import replay_create

        return replay_create(self, idempotency_key, request_signature)

    def withdraw_batch(
        self,
        batch_id: str,
        expected_generation: int,
        reason: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        from .batches import lifecycle_action

        return lifecycle_action(
            self, "withdraw", batch_id, expected_generation, reason, idempotency_key
        )

    def void_batch(
        self,
        batch_id: str,
        expected_generation: int,
        reason: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        from .batches import lifecycle_action

        return lifecycle_action(
            self, "void", batch_id, expected_generation, reason, idempotency_key
        )

    def resolve_legacy(
        self,
        batch_id: str,
        selected_version: int,
        expected_generation: int,
        reason: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        from .batches import lifecycle_action

        return lifecycle_action(
            self,
            "resolve",
            batch_id,
            expected_generation,
            reason,
            idempotency_key,
            selected_version,
        )

    def _backup_v1(self) -> Path:
        """Make a standalone pre-upgrade snapshot using a different read connection."""
        directory = self.data_dir / "backups"
        temporary: Path | None = None
        try:
            directory.mkdir(exist_ok=True)
            name = "aha-v1-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex
            final = directory / (name + ".sqlite3")
            temporary = directory / (name + ".tmp")
            with temporary.open("xb"):
                pass
            deadline = time.monotonic() + 20

            def progress(status: int, remaining: int, total: int) -> None:
                if time.monotonic() > deadline:
                    raise AppError("backup_failed", "升级备份超时，请退出其他程序后重试。", 409)

            uri = (self.data_dir / "aha.sqlite3").resolve().as_uri() + "?mode=ro"
            with closing(sqlite3.connect(uri, uri=True, timeout=0.25)) as source:
                with closing(sqlite3.connect(temporary)) as destination:
                    source.backup(destination, pages=256, progress=progress, sleep=0.02)
                    if destination.execute("PRAGMA user_version").fetchone()[0] != 1:
                        raise AppError("backup_failed", "升级备份校验失败，请保留原资料。", 409)
                    if destination.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                        raise AppError("backup_failed", "升级备份校验失败，请保留原资料。", 409)
            with temporary.open("r+b") as output:
                os.fsync(output.fileno())
            os.replace(temporary, final)
            return final
        except (OSError, sqlite3.Error) as exc:
            raise AppError(
                "backup_failed", "无法创建升级备份，请检查资料目录和可用空间。", 409
            ) from exc
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
