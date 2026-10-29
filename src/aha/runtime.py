"""Keep the directory lease until HTTP, jobs and the native tray have closed."""

from __future__ import annotations

import threading
from typing import Protocol

from .domain import AppError
from .instance import InstanceLease
from .server import LocalHTTPServer


class Tray(Protocol):
    def start(self) -> None: ...
    def run(self) -> None: ...
    def stop(self) -> None: ...
    def close(self) -> None: ...


class ApplicationRuntime:
    """Own resources; callbacks only signal and never wait for their own thread."""

    def __init__(self, server: LocalHTTPServer, lease: InstanceLease) -> None:
        self.server = server
        self.lease = lease
        self.tray: Tray | None = None
        self._thread: threading.Thread | None = None
        self._shutdown_thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._entered = threading.Event()
        self._finished = threading.Event()
        self._failed = False
        self._closed = False
        self.server.on_shutdown = self.request_shutdown
        self.server.mark_starting()

    def start(self) -> None:
        if self.tray is not None:
            self.tray.start()
        with self._lock:
            if self.server.stopping.is_set():
                return
            self._thread = threading.Thread(target=self._serve, name="aha-http")
            try:
                self._thread.start()
            except RuntimeError as error:
                # There is no loop to shut down or join when the OS cannot start it.
                self._thread = None
                raise AppError(
                    "service_unavailable", "本机服务未能启动，请重新打开程序。", 500
                ) from error
        self._entered.wait()
        with self._lock:
            if self._failed:
                raise AppError("service_unavailable", "本机服务未能启动，请重新打开程序。", 500)
            if self.server.stopping.is_set():
                return
            self.server.mark_ready()
            self.lease.publish(self.server.bootstrap_url, self.server.app.launch_id)

    def _serve(self) -> None:
        self._entered.set()
        try:
            self.server.serve_forever(poll_interval=0.1)
        except Exception:
            self._failed = True
        finally:
            self.server.mark_stopping()
            self._finished.set()
            if self.tray is not None:
                try:
                    self.tray.stop()
                except OSError:
                    self._failed = True

    def request_shutdown(self) -> None:
        with self._lock:
            self.server.mark_stopping()
            if self._shutdown_thread is not None or self._finished.is_set():
                return
            if self._thread is not None:
                self._shutdown_thread = threading.Thread(
                    target=self.server.shutdown, name="aha-shutdown"
                )
                self._shutdown_thread.start()

    def run(self) -> None:
        if self.tray is not None:
            self.tray.run()
            # A native loop ending also closes its service instead of leaving an orphan.
            self.request_shutdown()
        else:
            self._finished.wait()
        if self._failed:
            raise AppError("service_unavailable", "本机服务已停止，请重新打开程序。", 500)

    def close(self) -> None:
        if self._closed:
            return
        self.request_shutdown()
        if self._shutdown_thread is not None:
            self._shutdown_thread.join()
        if self._thread is not None:
            self._thread.join()
        self.server.server_close()
        self.server.wait_for_requests()
        # Cancellation is already signalled; close waits for the finite workers.
        self.server.app.close()
        if self.tray is not None:
            self.tray.close()
        self.lease.close()
        self._closed = True
