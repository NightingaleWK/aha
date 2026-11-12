"""Private, consistent ledger backups and verified restores into new directories."""

from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import struct
import sys
import tempfile
import threading
import zipfile
from collections.abc import Iterator
from contextlib import closing, contextmanager, suppress
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path, PurePosixPath
from time import monotonic
from typing import Any, BinaryIO
from uuid import uuid4

from . import __version__, batches, migrations
from .domain import BEIJING, AppError, canonical_bytes

FORMAT = "aha-full-backup"
FORMAT_VERSION = 1
MAX_ARCHIVE_BYTES = 4 * 1024**3
MAX_EXPANDED_BYTES = 16 * 1024**3
MAX_ENTRIES = 100_000
MAX_MANIFEST_BYTES = 8 * 1024**2
MAX_CENTRAL_BYTES = 64 * 1024**2
OPERATION_TIMEOUT = 600.0
CHUNK_SIZE = 1024 * 1024
_DIGEST = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {
    f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10)
}
_COUNTS = (
    "usage_records",
    "usage_versions",
    "projects",
    "sessions",
    "batches",
    "revisions",
    "usage_claims",
    "reconciliation_cases",
)


class _Budget:
    def __init__(
        self, cancel: threading.Event | None, shutdown: threading.Event | None = None
    ) -> None:
        self.cancel, self.shutdown = cancel, shutdown
        self.deadline = monotonic() + OPERATION_TIMEOUT

    def check(self) -> None:
        if (self.cancel is not None and self.cancel.is_set()) or (
            self.shutdown is not None and self.shutdown.is_set()
        ):
            raise AppError("backup_cancelled", "备份或还原已取消，原资料未被替换。", 409)
        if monotonic() >= self.deadline:
            raise AppError("backup_timeout", "备份或还原超过时限，原资料未被替换。", 409)

    def progress(self) -> int:
        try:
            self.check()
        except AppError:
            return 1
        return 0


def _runtime() -> None:
    if not migrations.sqlite_wal_safe():
        raise AppError(
            "unsupported_sqlite", "SQLite 运行时缺少必要并发修复，请使用新版完整程序。", 500
        )


@contextmanager
def _reader(path: Path, budget: _Budget) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(
        path.as_uri() + "?mode=ro", uri=True, timeout=1, isolation_level=None
    )
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.set_progress_handler(budget.progress, 5000)
        connection.execute("BEGIN")
        yield connection
    finally:
        with suppress(sqlite3.Error):
            connection.execute("ROLLBACK")
        connection.close()


@lru_cache(maxsize=2)
def _schema(version: int = migrations.SCHEMA_VERSION) -> tuple[
    dict[str, list[tuple[object, ...]]], dict[str, str]
]:
    """Use the production DDL, never a second hand-maintained schema definition."""
    connection = sqlite3.connect(":memory:")
    try:
        connection.executescript(migrations.SCHEMA_V3 if version == 3 else migrations.SCHEMA)
        migrations.initialize_monthly(connection)
        migrations.initialize_source_observations(connection)
        migrations.initialize_query_indexes(connection)
        batches.initialize_schema(connection)
        tables = {
            str(row[0]): list(connection.execute(f'PRAGMA table_info("{row[0]}")'))
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        definitions = {
            str(kind) + ":" + str(name): " ".join(str(sql).split())
            for kind, name, sql in connection.execute(
                "SELECT type,name,sql FROM sqlite_master WHERE type IN ('table','index','trigger')"
            )
        }
        return tables, definitions
    finally:
        connection.close()


def _validate_database(connection: sqlite3.Connection, budget: _Budget) -> dict[str, int]:
    budget.check()
    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if version not in migrations.SUPPORTED_BACKUP_SCHEMAS:
        raise AppError("unsupported_backup_store", "备份中的 aha 资料版本不受支持。", 409)
    expected, definitions = _schema(version)
    tables = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    if (
        tables != set(expected)
        or connection.execute("SELECT 1 FROM sqlite_master WHERE type='view' LIMIT 1").fetchone()
    ):
        raise AppError("invalid_backup", "备份中的 aha 数据库结构不完整或不兼容。", 409)
    for table, columns in expected.items():
        if list(connection.execute(f'PRAGMA table_info("{table}")')) != columns:
            raise AppError("invalid_backup", "备份中的 aha 数据库字段不兼容。", 409)
    actual_definitions = {
        str(kind) + ":" + str(name): " ".join(str(sql).split())
        for kind, name, sql in connection.execute(
            "SELECT type,name,sql FROM sqlite_master WHERE type IN ('table','index','trigger')"
        )
    }
    if actual_definitions != definitions:
        raise AppError("invalid_backup", "备份中的资料索引或历史保护结构不兼容。", 409)
    with closing(connection.execute("PRAGMA quick_check")) as cursor:
        if cursor.fetchone() != ("ok",) or cursor.fetchone() is not None:
            raise AppError("invalid_backup", "备份中的数据库完整性校验失败。", 409)
    with closing(connection.execute("PRAGMA foreign_key_check")) as cursor:
        if cursor.fetchone() is not None:
            raise AppError("invalid_backup", "备份中的数据库关联校验失败。", 409)
    budget.check()
    return {
        table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        for table in _COUNTS
    }


def _safe_name(name: str) -> str:
    parts = PurePosixPath(name).parts
    if (
        not name
        or len(name) > 1024
        or "\\" in name
        or name.startswith("/")
        or not parts
        or "/".join(parts) != name
        or any(
            part in {".", ".."}
            or len(part) > 255
            or part.endswith((" ", "."))
            or any(ord(char) < 32 or char in '<>:"|?*' for char in part)
            or part.split(".", 1)[0].upper() in _RESERVED
            for part in parts
        )
    ):
        raise AppError("invalid_backup", "备份包含不安全或不兼容的文件路径。", 409)
    if name not in {"aha.sqlite3", "manifest.json"} and (
        len(parts) < 2 or parts[0] not in {"objects", "packages"}
    ):
        raise AppError("invalid_backup", "备份包含未识别的资料文件。", 409)
    return name


def _regular_file(path: Path) -> None:
    if path.is_symlink() or path.is_junction() or not stat.S_ISREG(path.lstat().st_mode):
        raise AppError("invalid_backup", "资料包含链接或特殊文件，未执行备份或还原。", 409)


def _packages(connection: sqlite3.Connection) -> dict[str, str]:
    result: dict[str, str] = {}
    with closing(connection.execute("SELECT zip_path,zip_hash FROM revisions")) as cursor:
        for name, digest in cursor:
            if (
                not isinstance(name, str)
                or not isinstance(digest, str)
                or not _DIGEST.fullmatch(digest)
                or _safe_name(name) != name
                or len(PurePosixPath(name).parts) != 2
                or not name.startswith("packages/")
                or name in result
                and result[name] != digest
            ):
                raise AppError("invalid_backup", "原材料的文件登记无效，未生成或还原备份。", 409)
            result[name] = digest
            if len(result) >= MAX_ENTRIES:
                raise AppError("backup_too_large", "资料文件数量超过完整备份上限。", 413)
    return result


def _objects(root: Path, budget: _Budget) -> Iterator[tuple[str, Path]]:
    if not root.exists():
        return
    if root.is_symlink() or root.is_junction() or not root.is_dir():
        raise AppError("invalid_backup", "资料对象目录包含链接或不可识别结构。", 409)
    for parent, directories, files in os.walk(root, followlinks=False):
        budget.check()
        for name in directories:
            path = Path(parent) / name
            if path.is_symlink() or path.is_junction():
                raise AppError("invalid_backup", "资料对象包含链接，未生成备份。", 409)
        for name in sorted(files):
            path = Path(parent) / name
            _regular_file(path)
            relative = "objects/" + path.relative_to(root).as_posix()
            yield _safe_name(relative), path


def _inventory(root: Path) -> None:
    excluded_files = {
        "aha.sqlite3",
        "aha.sqlite3-wal",
        "aha.sqlite3-shm",
        ".instance.lock",
        "runtime.json",
        "restore-info.json",
    }
    for entry in root.iterdir():
        if entry.name in {"objects", "packages", "temporary", "backups"}:
            if entry.is_symlink() or entry.is_junction() or not entry.is_dir():
                raise AppError("invalid_backup", "资料目录包含链接或不可识别结构。", 409)
        elif entry.name not in excluded_files:
            raise AppError(
                "backup_unknown_files", "资料目录包含未识别的文件；请先独立保管并核实其用途。", 409
            )


def _hash_stream(stream: BinaryIO, budget: _Budget) -> tuple[int, str]:
    digest, size = hashlib.sha256(), 0
    while True:
        budget.check()
        chunk = stream.read(CHUNK_SIZE)
        if not chunk:
            return size, digest.hexdigest()
        digest.update(chunk)
        size += len(chunk)


def _hash_file(path: Path, budget: _Budget) -> tuple[int, str]:
    _regular_file(path)
    with path.open("rb") as stream:
        return _hash_stream(stream, budget)


def _add_file(
    archive: zipfile.ZipFile,
    path: Path,
    name: str,
    budget: _Budget,
    total: int,
    expected: str | None = None,
) -> dict[str, Any]:
    _regular_file(path)
    before = path.stat()
    if before.st_size + total > MAX_EXPANDED_BYTES:
        raise AppError("backup_too_large", "完整资料超过备份展开大小上限。", 413)
    digest, size = hashlib.sha256(), 0
    with path.open("rb") as source, archive.open(name, "w", force_zip64=True) as target:
        while True:
            budget.check()
            chunk = source.read(CHUNK_SIZE)
            if not chunk:
                break
            size += len(chunk)
            if total + size > MAX_EXPANDED_BYTES or size > before.st_size:
                raise AppError("backup_too_large", "资料大小变化或超过完整备份上限。", 413)
            digest.update(chunk)
            target.write(chunk)
            if archive.fp is not None and archive.fp.tell() > MAX_ARCHIVE_BYTES:
                raise AppError("backup_too_large", "完整备份包超过文件大小上限。", 413)
    after = path.stat()
    value = digest.hexdigest()
    if (
        size != before.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or before.st_ino != after.st_ino
        or expected is not None
        and expected != value
    ):
        raise AppError("backup_file_changed", "原材料缺失、变化或校验不符，未生成完整备份。", 409)
    return {"path": name, "size": size, "sha256": value}


def _publish_file(source: Path, destination: Path) -> None:
    if sys.platform == "win32":
        os.rename(source, destination)  # Windows rename never replaces an existing file.
    else:
        os.link(source, destination)  # Atomic no-replace publication on POSIX.
        source.unlink()


def create_backup(
    data_dir: Path,
    destination: Path,
    *,
    cancel: threading.Event | None = None,
    shutdown: threading.Event | None = None,
) -> dict[str, Any]:
    """Read an existing ledger without initializing it; never overwrite a backup."""
    _runtime()
    budget = _Budget(cancel, shutdown)
    budget.check()
    root, output = Path(data_dir).resolve(), Path(destination).absolute()
    if output.is_symlink() or output.exists():
        raise AppError("backup_exists", "备份目标文件已存在，请选择新的文件名。", 409)
    output = output.resolve()
    if output.is_relative_to(root) and not output.is_relative_to(root / "backups"):
        raise AppError("invalid_backup_destination", "备份请保存在资料目录外或 backups 目录。")
    try:
        _regular_file(root / "aha.sqlite3")
        _inventory(root)
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".aha-backup-", dir=output.parent) as temporary:
            workspace = Path(temporary)
            database = workspace / "aha.sqlite3"
            with _reader(root / "aha.sqlite3", budget) as source:
                # The schema read pins the same snapshot subsequently copied by backup().
                source_version = int(source.execute("PRAGMA user_version").fetchone()[0])
                if source_version not in migrations.SUPPORTED_BACKUP_SCHEMAS:
                    raise AppError(
                        "unsupported_backup_store", "这份 aha 资料版本不支持完整备份。", 409
                    )
                with closing(sqlite3.connect(database)) as target:
                    source.backup(
                        target,
                        pages=256,
                        sleep=0.05,
                        progress=lambda _status, _remaining, _total: budget.check(),
                    )
            with _reader(database, budget) as snapshot:
                counts = _validate_database(snapshot, budget)
                packages = _packages(snapshot)
            created_at = datetime.now(BEIJING).isoformat(timespec="seconds")
            manifest: dict[str, Any] = {
                "format": FORMAT,
                "format_version": FORMAT_VERSION,
                "application_version": __version__,
                "store_schema_version": source_version,
                "created_at": created_at,
                "files": [],
                "excluded": [
                    "runtime.json",
                    ".instance.lock",
                    "temporary",
                    "backups",
                    "restore-info.json",
                    "machine_installation_identity",
                ],
            }
            packed = workspace / "archive.tmp"
            total = 0
            with zipfile.ZipFile(
                packed, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True
            ) as archive:
                files: list[tuple[str, Path, str | None]] = [("aha.sqlite3", database, None)]
                files.extend(
                    (name, root / name, digest) for name, digest in sorted(packages.items())
                )
                for name, path, expected in files:
                    budget.check()
                    record = _add_file(archive, path, name, budget, total, expected)
                    manifest["files"].append(record)
                    total += record["size"]
                for name, path in _objects(root / "objects", budget):
                    if len(manifest["files"]) + 1 >= MAX_ENTRIES:
                        raise AppError("backup_too_large", "资料文件数量超过完整备份上限。", 413)
                    record = _add_file(archive, path, name, budget, total)
                    manifest["files"].append(record)
                    total += record["size"]
                portable_names = [record["path"].casefold() for record in manifest["files"]]
                if len(portable_names) != len(set(portable_names)):
                    raise AppError(
                        "invalid_backup", "资料文件名在其他系统上冲突，未生成备份。", 409
                    )
                encoded = canonical_bytes(manifest)
                if len(encoded) > MAX_MANIFEST_BYTES or total + len(encoded) > MAX_EXPANDED_BYTES:
                    raise AppError("backup_too_large", "完整备份清单或资料超过上限。", 413)
                archive.writestr("manifest.json", encoded)
            size, digest = _hash_file(packed, budget)
            if size > MAX_ARCHIVE_BYTES:
                raise AppError("backup_too_large", "完整备份包超过文件大小上限。", 413)
            with packed.open("r+b") as stream:
                stream.flush()
                os.fsync(stream.fileno())
            budget.check()
            _publish_file(packed, output)
            return {
                "archive_path": str(output),
                "sha256": digest,
                "size": size,
                "created_at": created_at,
                "format_version": FORMAT_VERSION,
                "store_schema_version": source_version,
                "counts": counts,
            }
    except AppError:
        raise
    except FileExistsError:
        raise AppError("backup_exists", "备份目标文件已存在，请选择新的文件名。", 409) from None
    except (OSError, sqlite3.Error, zipfile.BadZipFile, zipfile.LargeZipFile):
        budget.check()
        raise AppError("backup_failed", "完整备份未完成，请检查空间、权限和原材料。", 409) from None


def _container_limits(stream: BinaryIO, size: int) -> None:
    """Bound the central directory before ZipFile allocates all entry metadata."""
    stream.seek(max(0, size - 65557))
    tail = stream.read(65557)
    offset = tail.rfind(b"PK\x05\x06")
    if offset < 0 or len(tail) - offset < 22:
        raise AppError("invalid_backup", "文件不是完整的 aha 备份包。", 409)
    end = struct.unpack("<4s4H2LH", tail[offset : offset + 22])
    if offset + 22 + end[7] != len(tail) or end[1] or end[2] or end[3] != end[4]:
        raise AppError("invalid_backup", "完整备份的容器结构不受支持。", 409)
    count, central_size, central_offset = end[4], end[5], end[6]
    absolute_end = size - len(tail) + offset
    if count == 65535 or central_size == 0xFFFFFFFF or central_offset == 0xFFFFFFFF:
        stream.seek(max(0, absolute_end - 20))
        locator = stream.read(20)
        if len(locator) != 20:
            raise AppError("invalid_backup", "完整备份的 ZIP64 目录不完整。", 409)
        signature, disk, address, disks = struct.unpack("<4sLQL", locator)
        if signature != b"PK\x06\x07" or disk or disks != 1 or address > absolute_end - 56:
            raise AppError("invalid_backup", "完整备份的 ZIP64 目录无效。", 409)
        stream.seek(address)
        raw = stream.read(56)
        if len(raw) != 56:
            raise AppError("invalid_backup", "完整备份的 ZIP64 目录不完整。", 409)
        large = struct.unpack("<4sQ2H2L4Q", raw)
        if large[0] != b"PK\x06\x06" or large[1] < 44 or large[4] or large[5]:
            raise AppError("invalid_backup", "完整备份的 ZIP64 目录无效。", 409)
        if large[6] != large[7]:
            raise AppError("invalid_backup", "完整备份不能使用分卷文件。", 409)
        count, central_size, central_offset = large[7], large[8], large[9]
        absolute_end = address
    if count > MAX_ENTRIES or central_size > MAX_CENTRAL_BYTES:
        raise AppError("backup_too_large", "完整备份的文件数量或目录大小超过上限。", 413)
    if central_offset + central_size > absolute_end:
        raise AppError("invalid_backup", "完整备份的文件目录范围无效。", 409)
    stream.seek(0)


def _json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate manifest field")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise ValueError("non-finite manifest value")


def _manifest(
    archive: zipfile.ZipFile, budget: _Budget
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    infos = archive.infolist()
    if len(infos) > MAX_ENTRIES:
        raise AppError("backup_too_large", "完整备份文件数量超过上限。", 413)
    names: set[str] = set()
    folded: set[str] = set()
    expanded = 0
    for info in infos:
        budget.check()
        name = _safe_name(info.filename)
        mode = stat.S_IFMT(info.external_attr >> 16)
        if (
            name != info.orig_filename
            or name in names
            or name.casefold() in folded
            or info.is_dir()
            or mode not in {0, stat.S_IFREG}
            or info.flag_bits & 1
            or info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
        ):
            raise AppError("invalid_backup", "完整备份包含重复、链接或不支持的文件成员。", 409)
        names.add(name)
        folded.add(name.casefold())
        expanded += info.file_size
        if expanded > MAX_EXPANDED_BYTES:
            raise AppError("backup_too_large", "完整备份展开大小超过上限。", 413)
    for name in names:
        for parent in PurePosixPath(name).parents:
            if parent.as_posix().casefold() in folded:
                raise AppError("invalid_backup", "完整备份的文件与目录路径存在冲突。", 409)
    if (
        "manifest.json" not in names
        or archive.getinfo("manifest.json").file_size > MAX_MANIFEST_BYTES
    ):
        raise AppError("invalid_backup", "完整备份缺少有效的校验清单。", 409)
    raw = archive.read("manifest.json")
    value = json.loads(raw, object_pairs_hook=_json_pairs, parse_constant=_invalid_constant)
    if (
        not isinstance(value, dict)
        or value.get("format") != FORMAT
        or type(value.get("format_version")) is not int
        or value["format_version"] != FORMAT_VERSION
        or type(value.get("store_schema_version")) is not int
        or value["store_schema_version"] not in migrations.SUPPORTED_BACKUP_SCHEMAS
        or not isinstance(value.get("application_version"), str)
        or not isinstance(value.get("created_at"), str)
        or not isinstance(value.get("files"), list)
    ):
        raise AppError("invalid_backup", "完整备份清单格式或资料版本不兼容。", 409)
    created = datetime.fromisoformat(value["created_at"])
    if created.tzinfo is None:
        raise AppError("invalid_backup", "完整备份时间缺少时区依据。", 409)
    records: dict[str, dict[str, Any]] = {}
    for record in value["files"]:
        if (
            not isinstance(record, dict)
            or set(record) != {"path", "size", "sha256"}
            or not isinstance(record["path"], str)
            or type(record["size"]) is not int
            or record["size"] < 0
            or not isinstance(record["sha256"], str)
            or not _DIGEST.fullmatch(record["sha256"])
        ):
            raise AppError("invalid_backup", "完整备份文件校验信息无效。", 409)
        name = _safe_name(record["path"])
        if name == "manifest.json" or name in records or name not in names:
            raise AppError("invalid_backup", "完整备份文件清单存在重复或缺失。", 409)
        if archive.getinfo(name).file_size != record["size"]:
            raise AppError("invalid_backup", "完整备份文件长度与清单不一致。", 409)
        records[name] = record
    if "aha.sqlite3" not in records or set(records) | {"manifest.json"} != names:
        raise AppError("invalid_backup", "完整备份清单与实际文件不一致。", 409)
    return value, records


def _extract(
    archive: zipfile.ZipFile, records: dict[str, dict[str, Any]], root: Path, budget: _Budget
) -> None:
    for name, record in records.items():
        budget.check()
        target = root.joinpath(*PurePosixPath(name).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        digest, size = hashlib.sha256(), 0
        with archive.open(name) as source, target.open("xb") as output:
            while True:
                budget.check()
                chunk = source.read(CHUNK_SIZE)
                if not chunk:
                    break
                size += len(chunk)
                if size > record["size"]:
                    raise AppError("invalid_backup", "备份文件的实际长度超过清单。", 409)
                digest.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        if size != record["size"] or digest.hexdigest() != record["sha256"]:
            raise AppError("invalid_backup", "完整备份文件校验失败，未替换原资料。", 409)


def _interrupt_restored_runs(path: Path, budget: _Budget) -> int:
    """Only volatile staging changes; published facts and immutable material stay intact."""
    with _reader(path, budget) as connection:
        pending = sum(
            int(connection.execute(query).fetchone()[0])
            for query in (
                "SELECT COUNT(*) FROM sync_runs WHERE state='running'",
                "SELECT COUNT(*) FROM sync_stage",
                "SELECT COUNT(*) FROM sync_pricing",
            )
        )
    if not pending:
        return 0
    with closing(sqlite3.connect(path, isolation_level=None)) as connection:
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.set_progress_handler(budget.progress, 5000)
        try:
            connection.execute("BEGIN IMMEDIATE")
            interrupted = connection.execute(
                "UPDATE sync_runs SET state='failed',completed_at=?,error_code='sync_interrupted',"
                "error_message='恢复副本中的未完成同步已结束，未发布暂存资料。' "
                "WHERE state='running'",
                (datetime.now(UTC).isoformat(timespec="microseconds"),),
            ).rowcount
            connection.execute("DELETE FROM sync_stage")
            connection.execute("DELETE FROM sync_pricing")
            budget.check()
            connection.execute("COMMIT")
            return interrupted
        except BaseException:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise


def _publish_directory(source: Path, destination: Path) -> None:
    if sys.platform == "win32":
        os.rename(source, destination)
    elif sys.platform == "linux":
        # renameat2(RENAME_NOREPLACE) also rejects an empty directory created concurrently.
        library = ctypes.CDLL(None, use_errno=True)
        rename = getattr(library, "renameat2", None)
        if rename is None:
            raise OSError(errno.ENOTSUP, "atomic restore publication unavailable")
        rename.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename.restype = ctypes.c_int
        if rename(-100, os.fsencode(source), -100, os.fsencode(destination), 1):
            raise OSError(ctypes.get_errno(), "atomic restore publication failed")
    else:
        raise OSError(errno.ENOTSUP, "atomic restore publication unavailable")


def restore_backup(
    archive: Path, destination: Path, *, cancel: threading.Event | None = None
) -> dict[str, Any]:
    """Validate all members in isolation and publish a fresh complete data directory."""
    _runtime()
    budget = _Budget(cancel)
    budget.check()
    original, output = Path(archive).absolute(), Path(destination).absolute()
    if output.exists() or output.is_symlink():
        raise AppError("restore_destination_exists", "还原目录已存在，请选择全新的资料目录。", 409)
    output = output.resolve()
    if any((parent / "aha.sqlite3").exists() for parent in output.parents):
        raise AppError("invalid_restore_destination", "还原请使用现有 aha 资料目录之外的新目录。")
    staging: Path | None = None
    try:
        _regular_file(original)
        if original.stat().st_size > MAX_ARCHIVE_BYTES:
            raise AppError("backup_too_large", "完整备份文件超过大小上限。", 413)
        output.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".aha-restore-", dir=output.parent))
        with original.open("rb") as stream:
            before = os.fstat(stream.fileno())
            _container_limits(stream, before.st_size)
            _, digest = _hash_stream(stream, budget)
            stream.seek(0)
            with zipfile.ZipFile(stream) as bundle:
                manifest, records = _manifest(bundle, budget)
                _extract(bundle, records, staging, budget)
            after = os.fstat(stream.fileno())
            if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
                raise AppError("backup_file_changed", "恢复期间备份文件发生变化，请重新选择。", 409)
        with _reader(staging / "aha.sqlite3", budget) as database:
            counts = _validate_database(database, budget)
            if database.execute("PRAGMA user_version").fetchone()[0] != manifest[
                "store_schema_version"
            ]:
                raise AppError("invalid_backup", "备份清单与数据库资料版本不一致。", 409)
            references = _packages(database)
        if {name for name in records if name.startswith("packages/")} != set(references):
            raise AppError("invalid_backup", "完整备份的原材料与数据库登记不一致。", 409)
        if any(records[name]["sha256"] != expected for name, expected in references.items()):
            raise AppError("invalid_backup", "完整备份的原材料校验与历史登记不一致。", 409)
        interrupted = _interrupt_restored_runs(staging / "aha.sqlite3", budget)
        if manifest["store_schema_version"] == 3:
            # The immutable schema3 archive is the rollback copy. Upgrade only
            # the isolated restore staging, never the archive or running ledger.
            with closing(sqlite3.connect(staging / "aha.sqlite3", isolation_level=None)) as target:
                target.execute("PRAGMA foreign_keys=ON")
                target.execute("PRAGMA trusted_schema=OFF")
                target.set_progress_handler(budget.progress, 5000)
                try:
                    target.execute("BEGIN IMMEDIATE")
                    migrations.upgrade_schema3(
                        target, datetime.now(UTC).isoformat(timespec="microseconds")
                    )
                    budget.check()
                    target.execute("COMMIT")
                except BaseException:
                    if target.in_transaction:
                        target.execute("ROLLBACK")
                    raise
        restored_at = datetime.now(BEIJING).isoformat(timespec="seconds")
        marker = {
            "format_version": 1,
            "restore_id": str(uuid4()),
            "restored_at": restored_at,
            "archive_sha256": digest,
        }
        with (staging / "restore-info.json").open("xb") as stream:
            stream.write(canonical_bytes(marker))
            stream.flush()
            os.fsync(stream.fileno())
        for name in ("objects", "packages", "temporary"):
            (staging / name).mkdir(exist_ok=True)
        budget.check()
        _publish_directory(staging, output)
        staging = None
        return {
            "destination": str(output),
            "archive_sha256": digest,
            "restored_at": restored_at,
            "format_version": FORMAT_VERSION,
            "store_schema_version": migrations.SCHEMA_VERSION,
            "counts": counts,
            "interrupted_runs": interrupted,
        }
    except AppError:
        raise
    except FileExistsError:
        raise AppError(
            "restore_destination_exists", "还原目录已存在，请选择全新的资料目录。", 409
        ) from None
    except (
        OSError,
        ValueError,
        RecursionError,
        sqlite3.Error,
        zipfile.BadZipFile,
        zipfile.LargeZipFile,
        RuntimeError,
        NotImplementedError,
    ):
        budget.check()
        raise AppError(
            "invalid_backup", "完整备份无法校验或还原，请检查文件、空间和目录权限。", 409
        ) from None
    finally:
        if staging is not None:
            try:
                shutil.rmtree(staging)
            except OSError:
                raise AppError(
                    "restore_cleanup_failed", "还原未完成，暂存目录清理失败；原资料未被替换。", 500
                ) from None
