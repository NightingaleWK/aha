"""Own one application's directory lock and its private launch credential."""

from __future__ import annotations

import errno
import hashlib
import http.client
import json
import os
import re
import socket
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from http.cookies import CookieError, SimpleCookie
from pathlib import Path
from typing import Any, TypeGuard

from .domain import AppError

PROTOCOL_VERSION = 1
DESCRIPTOR_LIMIT = 16 * 1024
INSTANCE_WAIT = 10.0
_STARTUP_URL = re.compile(r"http://127\.0\.0\.1:([1-9][0-9]{0,4})/\?token=[A-Za-z0-9_-]{1,256}\Z")
_IDENTIFIER = re.compile(r"[0-9a-f]{32}\Z")
_PROFILE = re.compile(r"[0-9a-f]{64}\Z")
_BUSY_MESSAGE = "aha 正在启动或退出，请稍后重试；若持续无响应，请先退出原程序。"


def canonical_directory(data_dir: Path) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir.resolve(strict=True)


def profile_id(data_dir: Path) -> str:
    name = os.path.normcase(str(data_dir.resolve()))
    return hashlib.sha256(name.encode("utf-8")).hexdigest()


class DirectoryLock:
    """Keep the same lock file/inode across launches, including after a crash."""

    def __init__(self, data_dir: Path) -> None:
        path = data_dir / ".instance.lock"
        if path.is_symlink():
            raise OSError("The instance lock must be a regular local file.")
        self._fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            os.set_inheritable(self._fd, False)
        except BaseException:
            os.close(self._fd)
            raise
        self.acquired = False

    def acquire(self) -> bool:
        if self.acquired:
            return True
        try:
            if sys.platform == "win32":
                import msvcrt

                os.lseek(self._fd, 0, os.SEEK_SET)
                msvcrt.locking(self._fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            if error.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                return False
            raise
        self.acquired = True
        return True

    def close(self) -> None:
        if self._fd < 0:
            return
        try:
            if self.acquired:
                if sys.platform == "win32":
                    import msvcrt

                    os.lseek(self._fd, 0, os.SEEK_SET)
                    msvcrt.locking(self._fd, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(self._fd, fcntl.LOCK_UN)
        finally:
            os.close(self._fd)
            self._fd = -1
            self.acquired = False


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate field")
        value[key] = item
    return value


def _record(data_dir: Path) -> dict[str, Any] | None:
    try:
        with (data_dir / "runtime.json").open("rb") as source:
            raw = source.read(DESCRIPTOR_LIMIT + 1)
    except FileNotFoundError:
        return None
    if len(raw) > DESCRIPTOR_LIMIT:
        return None
    try:
        value = json.loads(raw, object_pairs_hook=_object)
    except (ValueError, UnicodeError, RecursionError):
        return None
    return value if isinstance(value, dict) else None


def _valid_pid(value: Any) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool) and 0 < value <= 0xFFFFFFFF


def process_alive(pid: int) -> bool:
    """A permission error cannot prove that a legacy process has stopped."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() != 87
        try:
            code = wintypes.DWORD()
            return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OverflowError:
        return False
    except PermissionError:
        return True
    return True


@dataclass(frozen=True)
class LaunchDescriptor:
    pid: int
    run_id: str
    profile_id: str
    bootstrap_url: str = field(repr=False)

    def payload(self) -> dict[str, Any]:
        return {
            "descriptor_version": 1,
            "application": "aha",
            "protocol_version": PROTOCOL_VERSION,
            "pid": self.pid,
            "run_id": self.run_id,
            "profile_id": self.profile_id,
            "bootstrap_url": self.bootstrap_url,
        }


def _descriptor(record: dict[str, Any] | None, expected_profile: str) -> LaunchDescriptor | None:
    if record is None:
        return None
    if "descriptor_version" in record and (
        type(record["descriptor_version"]) is not int
        or record["descriptor_version"] != 1
        or type(record.get("protocol_version")) is not int
        or record.get("protocol_version") != PROTOCOL_VERSION
    ):
        raise AppError("instance_incompatible", "运行信息属于其他版本，请先退出原程序。", 409)
    run_id = record.get("run_id")
    identity = record.get("profile_id")
    address = record.get("bootstrap_url")
    if (
        record.get("descriptor_version") != 1
        or record.get("application") != "aha"
        or not _valid_pid(record.get("pid"))
        or not isinstance(run_id, str)
        or not _IDENTIFIER.fullmatch(run_id)
        or not isinstance(identity, str)
        or not _PROFILE.fullmatch(identity)
        or identity != expected_profile
        or not isinstance(address, str)
    ):
        return None
    matched = _STARTUP_URL.fullmatch(address)
    if matched is None or int(matched[1]) > 65535:
        return None
    return LaunchDescriptor(record["pid"], run_id, identity, address)


def _response_body(response: http.client.HTTPResponse) -> bytes:
    length = response.getheader("Content-Length", "")
    if not length.isdigit() or int(length) > DESCRIPTOR_LIMIT:
        raise ValueError("Unexpected instance response length")
    payload = response.read(DESCRIPTOR_LIMIT + 1)
    if len(payload) != int(length):
        raise ValueError("Incomplete instance response")
    return payload


def _inspect_instance(
    descriptor: LaunchDescriptor, port: int, deadline: float,
    connect: Callable[[http.client.HTTPConnection], None],
) -> bool:
    connection = http.client.HTTPConnection(
        "127.0.0.1", port, timeout=max(0.001, deadline - time.monotonic())
    )
    try:
        connect(connection)
        connection.request("GET", "/?" + descriptor.bootstrap_url.split("/?", 1)[1])
        response = connection.getresponse()
        raw_cookie = response.getheader("Set-Cookie")
        _response_body(response)
        if response.status != 303 or response.getheader("Location") != "/" or raw_cookie is None:
            return False
        cookies = SimpleCookie()
        cookies.load(raw_cookie)
        name = f"aha_session_{port}"
        cookie = cookies.get(name)
        if cookie is None or not re.fullmatch(r"[A-Za-z0-9_-]{16,256}", cookie.value):
            return False
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        # The bootstrap response uses HTTP/1.0, so the next request opens a new socket.
        connection.close()
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=remaining)
        connect(connection)
        connection.request("GET", "/api/instance", headers={"Cookie": f"{name}={cookie.value}"})
        response = connection.getresponse()
        payload = _response_body(response)
        if response.status != 200 or time.monotonic() > deadline:
            return False
        identity = json.loads(payload, object_pairs_hook=_object)
        return (
            isinstance(identity, dict)
            and identity.get("application") == "aha"
            and type(identity.get("protocol_version")) is int
            and identity.get("protocol_version") == PROTOCOL_VERSION
            and identity.get("run_id") == descriptor.run_id
            and identity.get("profile_id") == descriptor.profile_id
            and identity.get("state") == "ready"
        )
    except (
        OSError, ValueError, UnicodeError, RecursionError, CookieError, http.client.HTTPException
    ):
        return False
    finally:
        connection.close()


def verify_instance(descriptor: LaunchDescriptor, timeout: float = 1.0) -> bool:
    """Authenticate within a wall budget, including a listener trickling headers/body."""
    matched = _STARTUP_URL.fullmatch(descriptor.bootstrap_url)
    if matched is None or not 0 < int(matched[1]) <= 65535 or timeout <= 0:
        return False
    port = int(matched[1])
    deadline = time.monotonic() + timeout
    finished, cancelled = threading.Event(), threading.Event()
    guard = threading.Lock()
    sockets: list[socket.socket] = []
    result = [False]

    def connect(connection: http.client.HTTPConnection) -> None:
        connection.connect()
        with guard:
            if cancelled.is_set():
                connection.close()
                raise TimeoutError
            if connection.sock is not None:
                sockets.append(connection.sock)

    def inspect() -> None:
        try:
            result[0] = _inspect_instance(descriptor, port, deadline, connect)
        finally:
            finished.set()

    try:
        threading.Thread(target=inspect, name="aha-instance-probe", daemon=True).start()
    except RuntimeError:
        return False
    if finished.wait(max(0, deadline - time.monotonic())):
        return result[0]
    cancelled.set()
    with guard:
        for active in sockets:
            with suppress(OSError):
                active.shutdown(socket.SHUT_RDWR)
            active.close()
    return False


class InstanceLease:
    """Only the lifetime owner may publish/remove a launch descriptor."""

    def __init__(self, data_dir: Path, lock: DirectoryLock) -> None:
        self.data_dir = data_dir
        self.profile_id = profile_id(data_dir)
        self._lock = lock
        self._run_id: str | None = None

    def publish(self, bootstrap_url: str, run_id: str) -> LaunchDescriptor:
        descriptor = LaunchDescriptor(os.getpid(), run_id, self.profile_id, bootstrap_url)
        if _descriptor(descriptor.payload(), self.profile_id) is None:
            raise ValueError("Invalid launch descriptor")
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", prefix=".runtime-", suffix=".tmp",
                dir=self.data_dir, delete=False,
            ) as output:
                temporary = Path(output.name)
                json.dump(descriptor.payload(), output, ensure_ascii=False)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.data_dir / "runtime.json")
            self._run_id = run_id
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return descriptor

    def close(self) -> None:
        try:
            if self._run_id is not None:
                record = _record(self.data_dir)
                if record is not None and record.get("run_id") == self._run_id:
                    (self.data_dir / "runtime.json").unlink(missing_ok=True)
                self._run_id = None
        finally:
            self._lock.close()


def acquire_instance(
    data_dir: Path, *, timeout: float = INSTANCE_WAIT
) -> InstanceLease | LaunchDescriptor:
    """Acquire before constructing Store, or return a verified existing instance."""
    root = canonical_directory(data_dir)
    identity = profile_id(root)
    lock = DirectoryLock(root)
    deadline = time.monotonic() + timeout
    try:
        while True:
            if lock.acquire():
                record = _record(root)
                if record is not None and "descriptor_version" not in record:
                    pid = record.get("pid")
                    if _valid_pid(pid) and process_alive(pid):
                        raise AppError(
                            "legacy_instance_running",
                            "检测到旧版 aha 可能仍在运行，请先退出旧版再打开。",
                            409,
                        )
                elif record is not None:
                    # A free OS lock proves a supported new-format descriptor is stale.
                    _descriptor(record, identity)
                return InstanceLease(root, lock)
            record = _record(root)
            descriptor = _descriptor(record, identity)
            remaining = deadline - time.monotonic()
            if remaining > 0 and descriptor is not None:
                if verify_instance(descriptor, min(1.0, remaining)):
                    lock.close()
                    return descriptor
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AppError("instance_busy", _BUSY_MESSAGE, 409)
            time.sleep(min(0.05, remaining))
    except BaseException:
        lock.close()
        raise
