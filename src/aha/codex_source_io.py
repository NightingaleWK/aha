"""Read bounded snapshots of Codex rollouts from local files and a selected WSL distro."""

from __future__ import annotations

import json
import os
import queue
import shutil
import stat
import subprocess
import threading
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from .domain import AppError

ROOTS = ("sessions", "archived_sessions")
SUFFIXES = (".jsonl", ".jsonl.zst")
MAX_ENTRIES = 250_000
READ_BYTES = 512 * 1024
_FRAME_LIMIT = 2 * READ_BYTES


@dataclass(frozen=True)
class CodexSource:
    kind: Literal["windows", "wsl"]
    root: str
    distribution: str | None = None


@dataclass(frozen=True)
class FileStamp:
    path: str
    size: int
    mtime: int
    ctime: int
    device: int
    inode: int

    @classmethod
    def local(cls, path: str, info: os.stat_result) -> FileStamp:
        # Windows path and handle stat can expose different ctime meanings.
        # Birth time identifies replacements consistently on Python 3.12+.
        change = info.st_ctime_ns
        if os.name == "nt":
            change = getattr(info, "st_birthtime_ns", info.st_ctime_ns)
        return cls(path, info.st_size, info.st_mtime_ns, change, info.st_dev, info.st_ino)

    @property
    def identity(self) -> tuple[int, int]:
        return self.device, self.inode

    @property
    def signature(self) -> list[int]:
        return [self.device, self.inode, self.size, self.mtime, self.ctime]


class SourceFile(Protocol):
    def stamp(self) -> FileStamp: ...
    def read(self, offset: int, limit: int) -> bytes: ...


class SourceFiles(Protocol):
    root: str
    issues: Counter[str]

    def files(self) -> Iterator[FileStamp]: ...
    def open(self, path: str) -> SourceFile: ...
    def close_file(self) -> None: ...


def default_local_root() -> str:
    return str(Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser().absolute())


def _unavailable(kind: str) -> AppError:
    if kind == "wsl":
        return AppError(
            "wsl_unavailable",
            "无法在所选 WSL 发行版读取 Codex 目录，请检查发行版、目录和 Python 3。",
            409,
        )
    return AppError("source_unavailable", "无法打开本机 Codex 目录，请检查来源设置。", 409)


def _checked_source(source: CodexSource) -> None:
    if source.kind not in {"windows", "wsl"} or (
        len(source.root) > 4096 or any(ord(char) < 32 for char in source.root)
    ):
        raise AppError("invalid_source", "Codex 来源目录无效。")
    if source.kind == "wsl":
        distribution = source.distribution
        if (
            not distribution or len(distribution) > 128 or distribution.startswith("-")
            or distribution != distribution.strip()
            or any(ord(char) < 32 for char in distribution)
        ):
            raise AppError("invalid_source", "请选择有效的 WSL 发行版。")
    elif source.distribution is not None:
        raise AppError("invalid_source", "本机 Codex 来源不接受 WSL 发行版。")


def _wsl_executable() -> str | None:
    if os.name == "nt":
        # Prefer Windows' system executable to an arbitrary PATH entry.
        candidate = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "wsl.exe"
    else:
        candidate = Path("/mnt/c/Windows/System32/wsl.exe")
    return str(candidate) if candidate.is_file() else shutil.which("wsl.exe")


def list_distributions() -> list[str]:
    executable = _wsl_executable()
    if executable is None:
        return []
    try:
        output = subprocess.run(
            [executable, "--list", "--quiet"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, timeout=4, check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
        if len(output) > 32_768:
            return []
        if output.startswith((b"\xff\xfe", b"\xfe\xff")):
            names = output.decode("utf-16")
        elif b"\x00" in output:
            names = output.decode("utf-16-le")
        else:
            names = output.decode("utf-8-sig")
    except (OSError, UnicodeError, subprocess.SubprocessError):
        return []
    return list(dict.fromkeys(
        name for line in names.splitlines() if (name := line.strip()) and len(name) <= 128
        and not name.startswith("-") and not any(ord(char) < 32 for char in name)
    ))


def _path_parts(path: str) -> tuple[str, ...]:
    parts = tuple(path.split("/"))
    if (
        len(path) > 4096 or len(parts) < 2 or parts[0] not in ROOTS
        or any(part in {"", ".", ".."} for part in parts)
        or any(ord(char) < 32 or char in "\\:" for char in path)
        or not path.endswith(SUFFIXES)
    ):
        raise OSError("invalid rollout path")
    return parts


def _is_link(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    )


def _rollout_directory(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return stat.S_ISDIR(info.st_mode) and not _is_link(info)


def _open_posix(root: Path, parts: tuple[str, ...]) -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    directory = os.open(root, flags)
    try:
        for part in parts[:-1]:
            child = os.open(part, flags, dir_fd=directory)
            os.close(directory)
            directory = child
        return os.open(
            parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
        )
    finally:
        os.close(directory)


def _open_windows(root: Path, parts: tuple[str, ...]) -> int:
    current = root
    for part in parts[:-1]:
        current /= part
        info = current.lstat()
        if not stat.S_ISDIR(info.st_mode) or _is_link(info):
            raise OSError("invalid rollout directory")
    path = current / parts[-1]
    info = path.lstat()
    if _is_link(info) or not stat.S_ISREG(info.st_mode) or path.resolve(strict=True) != path:
        raise OSError("invalid rollout file")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
    try:
        opened = os.fstat(descriptor)
        verified = path.lstat()
        if (
            not os.path.samestat(opened, info) or not os.path.samestat(opened, verified)
            or _is_link(verified) or path.resolve(strict=True) != path
        ):
            raise OSError("rollout file changed while opening")
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


@dataclass
class _LocalFile:
    descriptor: int
    path: str

    def stamp(self) -> FileStamp:
        return FileStamp.local(self.path, os.fstat(self.descriptor))

    def read(self, offset: int, limit: int) -> bytes:
        os.lseek(self.descriptor, offset, os.SEEK_SET)
        return os.read(self.descriptor, limit)


class _LocalFiles:
    def __init__(self, root: str, check: Callable[[], None]) -> None:
        try:
            path = Path(root or default_local_root()).expanduser().resolve(strict=True)
            if not path.is_dir() or not any(_rollout_directory(path / name) for name in ROOTS):
                raise OSError("not a directory")
        except (OSError, ValueError, RuntimeError):
            raise _unavailable("windows") from None
        self._path = path
        self.root = str(path)
        self.issues: Counter[str] = Counter()
        self._file: _LocalFile | None = None
        self._check = check

    def files(self) -> Iterator[FileStamp]:
        def failed(_: OSError) -> None:
            self.issues["directory_unavailable"] += 1

        count = 0
        for name in ROOTS:
            scan = self._path / name
            try:
                info = scan.lstat()
            except FileNotFoundError:
                continue
            except OSError:
                self.issues["directory_unavailable"] += 1
                continue
            if _is_link(info) or not stat.S_ISDIR(info.st_mode):
                self.issues["directory_unavailable"] += 1
                continue
            for directory, directories, filenames in os.walk(scan, onerror=failed):
                self._check()
                count += len(directories) + len(filenames)
                if count > MAX_ENTRIES:
                    self.issues["inventory_limit"] += 1
                    return
                folder = Path(directory)
                # os.walk doesn't prune Windows junctions on every supported interpreter.
                for subdir in list(directories):
                    try:
                        if _is_link((folder / subdir).lstat()):
                            directories.remove(subdir)
                            self.issues["directory_unavailable"] += 1
                    except OSError:
                        directories.remove(subdir)
                        self.issues["directory_unavailable"] += 1
                directories.sort(reverse=True)
                for filename in sorted(filenames, reverse=True):
                    self._check()
                    if not filename.endswith(SUFFIXES):
                        continue
                    path = folder / filename
                    relative = path.relative_to(self._path).as_posix()
                    try:
                        _path_parts(relative)
                        info = path.lstat()
                        if _is_link(info) or not stat.S_ISREG(info.st_mode):
                            raise OSError("invalid rollout file")
                    except OSError:
                        self.issues["file_unavailable"] += 1
                        continue
                    yield FileStamp.local(relative, info)

    def open(self, path: str) -> SourceFile:
        self.close_file()
        parts = _path_parts(path)
        descriptor = (
            _open_windows(self._path, parts) if os.name == "nt"
            else _open_posix(self._path, parts)
        )
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            raise OSError("invalid rollout file")
        self._file = _LocalFile(descriptor, path)
        return self._file

    def close_file(self) -> None:
        if self._file is not None:
            os.close(self._file.descriptor)
            self._file = None


# The child uses only distro-local stdlib. Selection, paths and offsets arrive as framed
# data. The fixed command never accepts shell text or loads user Python startup hooks.
_WSL_PROGRAM = r'''
import json
import os
import signal
import stat
import sys
from collections import Counter
from pathlib import Path

ROOTS = ("sessions", "archived_sessions")
SUFFIXES = (".jsonl", ".jsonl.zst")
MAX_ENTRIES = 250_000
READ_BYTES = 512 * 1024
signal.alarm(120)
issues = Counter()
root = None
entries = None
descriptor = None
relative = None

def stamp(path, info):
    return [path, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_dev, info.st_ino]

def failed(error):
    issues["directory_unavailable"] += 1

def rollout_directory(path):
    try:
        return stat.S_ISDIR(path.lstat().st_mode)
    except OSError:
        return False

def list_files():
    count = 0
    for name in ROOTS:
        scan = root / name
        try:
            if not stat.S_ISDIR(scan.lstat().st_mode):
                issues["directory_unavailable"] += 1
                continue
        except FileNotFoundError:
            continue
        except OSError:
            issues["directory_unavailable"] += 1
            continue
        for directory, directories, filenames in os.walk(scan, onerror=failed):
            count += len(directories) + len(filenames)
            if count > MAX_ENTRIES:
                issues["inventory_limit"] += 1
                return
            folder = Path(directory)
            directories[:] = sorted(
                (dirname for dirname in directories if not (folder / dirname).is_symlink()),
                reverse=True,
            )
            for name in sorted(filenames, reverse=True):
                if not name.endswith(SUFFIXES):
                    continue
                candidate = folder / name
                rel = candidate.relative_to(root).as_posix()
                try:
                    info = candidate.lstat()
                    if (
                        len(rel) > 4096 or not stat.S_ISREG(info.st_mode)
                        or any(ord(ch) < 32 or ch in "\\:" for ch in rel)
                    ):
                        raise OSError
                except OSError:
                    issues["file_unavailable"] += 1
                    continue
                yield stamp(rel, info)

def open_file(path):
    parts = path.split("/")
    if (
        len(path) > 4096 or len(parts) < 2 or parts[0] not in ROOTS
        or any(part in {"", ".", ".."} for part in parts)
        or not path.endswith(SUFFIXES)
        or any(ord(ch) < 32 or ch in "\\:" for ch in path)
    ):
        raise OSError
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    folder = os.open(root, flags)
    try:
        for part in parts[:-1]:
            child = os.open(part, flags, dir_fd=folder)
            os.close(folder)
            folder = child
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=folder)
    finally:
        os.close(folder)
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise OSError
    return fd

def reply(value):
    if isinstance(value, bytes):
        body = b'B' + value
    else:
        body = b'J' + json.dumps(value, ensure_ascii=True).encode("ascii")
    sys.stdout.buffer.write(len(body).to_bytes(4, "big"))
    sys.stdout.buffer.write(body)

while request := sys.stdin.buffer.readline(32768):
    op = ""
    try:
        command = json.loads(request)
        op = command[0]
        if op == "root":
            raw = command[1] or os.environ.get("CODEX_HOME") or str(Path.home() / ".codex")
            root = Path(raw).expanduser().resolve(strict=True)
            if not root.is_dir() or not any(rollout_directory(root / name) for name in ROOTS):
                raise OSError
            entries = list_files()
            result = str(root)
        elif op == "page":
            result = {"files": [], "done": False}
            for _ in range(64):
                entry = next(entries, None)
                if entry is None:
                    result["done"] = True
                    break
                result["files"].append(entry)
            result["issues"] = dict(issues)
        elif op == "open":
            if descriptor is not None:
                os.close(descriptor)
                descriptor = None
            relative = command[1]
            descriptor = open_file(relative)
            result = stamp(relative, os.fstat(descriptor))
        elif op == "stat":
            result = stamp(relative, os.fstat(descriptor))
        elif op == "read":
            offset, length = command[1:]
            if offset < 0 or not 0 <= length <= READ_BYTES:
                raise ValueError
            result = os.pread(descriptor, length, offset)
        elif op == "close":
            if descriptor is not None:
                os.close(descriptor)
                descriptor = None
            result = None
        else:
            raise ValueError
    except (OSError, ValueError, TypeError, RuntimeError, IndexError):
        result = {"error": "root" if op == "root" else "file"}
    reply(result)
'''


@dataclass
class _Exchange:
    request: bytes
    result: queue.Queue[bytes | Exception]


class _WSLFiles:
    def __init__(self, source: CodexSource, check: Callable[[], None]) -> None:
        executable = _wsl_executable()
        if not executable:
            raise _unavailable("wsl")
        assert source.distribution is not None
        try:
            self._process = subprocess.Popen(
                [executable, "--distribution", source.distribution, "--exec", "python3",
                 "-I", "-S", "-u", "-c", _WSL_PROGRAM],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError:
            raise _unavailable("wsl") from None
        self._check = check
        self._requests: queue.Queue[_Exchange | None] = queue.Queue()
        self._thread = threading.Thread(target=self._serve, name="aha-wsl-read", daemon=True)
        self._thread.start()
        self._opened = False
        self.issues: Counter[str] = Counter()
        try:
            root = self._call("root", source.root)
            if not isinstance(root, str):
                raise _unavailable("wsl")
            self.root = root
        except BaseException:
            self.finish()
            raise

    def _serve(self) -> None:
        request_in, reply_out = self._process.stdin, self._process.stdout
        assert request_in is not None and reply_out is not None
        while exchange := self._requests.get():
            try:
                request_in.write(exchange.request)
                request_in.flush()
                header = reply_out.read(4)
                length = int.from_bytes(header, "big")
                if len(header) != 4 or not 0 < length <= _FRAME_LIMIT:
                    raise OSError("invalid WSL reply")
                body = reply_out.read(length)
                if len(body) != length:
                    raise OSError("incomplete WSL reply")
                exchange.result.put(body)
            except (OSError, ValueError) as exc:
                exchange.result.put(exc)
                return

    def _call(self, op: str, *arguments: Any) -> Any:
        self._check()
        result: queue.Queue[bytes | Exception] = queue.Queue(maxsize=1)
        request = json.dumps([op, *arguments], ensure_ascii=True).encode("ascii") + b"\n"
        self._requests.put(_Exchange(request, result))
        while True:
            self._check()
            try:
                body = result.get(timeout=0.05)
                break
            except queue.Empty:
                if not self._thread.is_alive():
                    raise _unavailable("wsl") from None
        if isinstance(body, Exception):
            raise _unavailable("wsl") from None
        if body[:1] == b"B":
            return body[1:]
        if body[:1] != b"J":
            raise _unavailable("wsl")
        try:
            value = json.loads(body[1:])
        except (ValueError, RecursionError):
            raise _unavailable("wsl") from None
        if isinstance(value, dict) and value.get("error") == "file":
            raise OSError("WSL rollout became unavailable")
        return value

    def files(self) -> Iterator[FileStamp]:
        while True:
            page = self._call("page")
            self.issues.update({
                key: amount - self.issues[key] for key, amount in page["issues"].items()
            })
            yield from (FileStamp(*entry) for entry in page["files"])
            if page["done"]:
                return

    def open(self, path: str) -> SourceFile:
        self.close_file()
        _path_parts(path)
        self._call("open", path)
        self._opened = True
        return self

    def stamp(self) -> FileStamp:
        return FileStamp(*self._call("stat"))

    def read(self, offset: int, limit: int) -> bytes:
        result = self._call("read", offset, limit)
        if not isinstance(result, bytes):
            raise _unavailable("wsl")
        return result

    def close_file(self) -> None:
        if self._opened:
            self._call("close")
            self._opened = False

    def finish(self) -> None:
        self._requests.put(None)
        request_in, reply_out = self._process.stdin, self._process.stdout
        assert request_in is not None and reply_out is not None
        self._thread.join(timeout=0.1)
        try:
            if not self._thread.is_alive():
                request_in.close()
            self._process.wait(timeout=0.2)
        except (OSError, subprocess.TimeoutExpired):
            with suppress(OSError):
                self._process.kill()
            with suppress(OSError, subprocess.TimeoutExpired):
                self._process.wait(timeout=0.2)
        self._thread.join(timeout=0.2)
        if not self._thread.is_alive():
            for pipe in (request_in, reply_out):
                with suppress(OSError):
                    pipe.close()


@contextmanager
def source_files(source: CodexSource, check: Callable[[], None]) -> Iterator[SourceFiles]:
    _checked_source(source)
    if source.kind == "windows":
        local = _LocalFiles(source.root, check)
        try:
            yield local
        finally:
            local.close_file()
    else:
        remote = _WSLFiles(source, check)
        try:
            yield remote
        finally:
            remote.finish()
