"""Real ownership, authenticated reuse, crash recovery and shutdown races."""

from __future__ import annotations

import http.client
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from test_http_cli import stop_owned_server

from aha.__main__ import _launch
from aha.domain import AppError
from aha.instance import (
    DirectoryLock,
    InstanceLease,
    LaunchDescriptor,
    acquire_instance,
    canonical_directory,
    profile_id,
    verify_instance,
)
from aha.runtime import ApplicationRuntime
from aha.server import create_server
from aha.storage import Store


def credentials(address: str) -> tuple[str, str, str]:
    parsed = urlsplit(address)
    client = http.client.HTTPConnection("127.0.0.1", parsed.port, timeout=3)
    try:
        client.request("GET", "/?" + parsed.query)
        response = client.getresponse()
        cookie = response.getheader("Set-Cookie").split(";", 1)[0]
        response.read()
        client.request("GET", "/api/status", headers={"Cookie": cookie})
        response = client.getresponse()
        csrf = json.loads(response.read())["csrf_token"]
        return cookie, csrf, f"http://{parsed.netloc}"
    finally:
        client.close()


def post(address: str, cookie: str, csrf: str, path: str, body: dict) -> tuple[int, dict]:
    parsed = urlsplit(address)
    client = http.client.HTTPConnection("127.0.0.1", parsed.port, timeout=5)
    try:
        client.request("POST", path, json.dumps(body), {
            "Cookie": cookie, "X-AHA-CSRF": csrf, "Origin": f"http://{parsed.netloc}",
            "Content-Type": "application/json",
        })
        response = client.getresponse()
        return response.status, json.loads(response.read())
    finally:
        client.close()


class InstanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.data = canonical_directory(self.root / "data")

    def descriptor(self, **changes: object) -> dict:
        value = LaunchDescriptor(
            os.getpid(), "a" * 32, profile_id(self.data), "http://127.0.0.1:9876/?token=test"
        ).payload()
        value.update(changes)
        return value

    def write(self, value: dict) -> None:
        (self.data / "runtime.json").write_text(json.dumps(value), encoding="utf-8")

    def test_lock_conflict_is_real_and_file_is_retained_after_release(self) -> None:
        first = DirectoryLock(self.data)
        second = DirectoryLock(self.data)
        try:
            self.assertTrue(first.acquire())
            self.assertFalse(second.acquire())
            first.close()
            self.assertTrue((self.data / ".instance.lock").exists())
            self.assertTrue(second.acquire())
        finally:
            first.close()
            second.close()

    def test_free_new_descriptor_ignores_reused_pid_and_recovers_corrupt_json(self) -> None:
        for payload in (json.dumps(self.descriptor()), "{broken", "[" * 1500):
            with self.subTest(kind=payload[:10]):
                (self.data / "runtime.json").write_text(payload, encoding="utf-8")
                lease = acquire_instance(self.data)
                self.assertIsInstance(lease, InstanceLease)
                try:
                    current = lease.publish("http://127.0.0.1:9877/?token=new", "b" * 32)
                    self.assertEqual(current.run_id, "b" * 32)
                finally:
                    lease.close()
                self.assertFalse((self.data / "runtime.json").exists())

    def test_possible_legacy_process_requires_exit_without_deleting_its_record(self) -> None:
        value = {"pid": os.getpid(), "bootstrap_url": "http://127.0.0.1:9876/?token=old"}
        self.write(value)
        with self.assertRaises(AppError) as caught:
            acquire_instance(self.data)
        self.assertEqual(caught.exception.code, "legacy_instance_running")
        self.assertEqual(json.loads((self.data / "runtime.json").read_text()), value)
        lock = DirectoryLock(self.data)
        try:
            self.assertTrue(lock.acquire())
        finally:
            lock.close()

    def test_unknown_protocol_is_not_overwritten(self) -> None:
        value = self.descriptor(protocol_version=999)
        self.write(value)
        with self.assertRaises(AppError) as caught:
            acquire_instance(self.data)
        self.assertEqual(caught.exception.code, "instance_incompatible")
        self.assertEqual(json.loads((self.data / "runtime.json").read_text()), value)

    def test_unverified_lock_holder_times_out_and_external_address_is_never_requested(self) -> None:
        holder = DirectoryLock(self.data)
        self.assertTrue(holder.acquire())
        try:
            self.write(self.descriptor(bootstrap_url="http://example.invalid/?token=test"))
            started = time.monotonic()
            with patch("aha.instance.http.client.HTTPConnection") as connect:
                with self.assertRaises(AppError) as caught:
                    acquire_instance(self.data, timeout=0.1)
                connect.assert_not_called()
            self.assertEqual(caught.exception.code, "instance_busy")
            self.assertLess(time.monotonic() - started, 1)
            self.assertTrue((self.data / "runtime.json").exists())
        finally:
            holder.close()

    def test_cleanup_does_not_remove_a_different_launch_descriptor(self) -> None:
        lease = acquire_instance(self.data)
        self.assertIsInstance(lease, InstanceLease)
        lease.publish("http://127.0.0.1:9877/?token=new", "b" * 32)
        replacement = self.descriptor(run_id="c" * 32)
        self.write(replacement)
        lease.close()
        self.assertEqual(json.loads((self.data / "runtime.json").read_text()), replacement)

    def test_directory_alias_uses_same_ownership_and_identity(self) -> None:
        alias = self.root / "alias"
        try:
            alias.symlink_to(self.data, target_is_directory=True)
        except OSError:
            if os.name != "nt":
                self.skipTest("Creating directory symlinks is not permitted in this environment")
            result = subprocess.run(
                ["cmd.exe", "/c", "mklink", "/J", str(alias), str(self.data)],
                capture_output=True, check=False,
            )
            if result.returncode:
                self.skipTest("Creating a task-owned directory junction is unavailable")
        lease = acquire_instance(self.data)
        try:
            self.assertEqual(profile_id(alias), profile_id(self.data))
            with self.assertRaises(AppError) as caught:
                acquire_instance(alias, timeout=0.05)
            self.assertEqual(caught.exception.code, "instance_busy")
        finally:
            lease.close()
            if alias.is_symlink():
                alias.unlink()
            else:
                alias.rmdir()

    def test_duplicate_launch_opens_verified_address_without_creating_store(self) -> None:
        descriptor = LaunchDescriptor(**{
            key: self.descriptor()[key] for key in ("pid", "run_id", "profile_id", "bootstrap_url")
        })
        with (
            patch("aha.__main__.acquire_instance", return_value=descriptor),
            patch("aha.__main__.create_server") as create,
            patch("aha.__main__.open_browser") as browser,
            patch("sys.stdout", new=io.StringIO()),
        ):
            _launch(self.data, 0, no_browser=False, no_tray=False)
            create.assert_not_called()
            browser.assert_called_once_with(descriptor.bootstrap_url, tray_available=False)


class ListenerTests(unittest.TestCase):
    @contextmanager
    def listener(self, *, redirect: str = "/", application: str = "aha", trickle: bool = False):
        requests: list[str] = []
        identity = {
            "application": application, "protocol_version": 1, "run_id": "a" * 32,
            "profile_id": "b" * 64, "state": "ready",
        }

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: object) -> None:
                return

            def do_GET(self) -> None:
                requests.append(self.path)
                try:
                    if trickle:
                        for byte in b"HTTP/1.0 303 See Other\r\nLocation: /\r\n\r\n":
                            self.wfile.write(bytes([byte]))
                            self.wfile.flush()
                            time.sleep(0.03)
                        return
                    if self.path.startswith("/?"):
                        self.send_response(303)
                        self.send_header("Location", redirect)
                        self.send_header("Set-Cookie", f"aha_session_{self.server.server_port}="
                                         + "c" * 32 + "; Path=/; HttpOnly; SameSite=Strict")
                        payload = b""
                    else:
                        self.send_response(200)
                        payload = json.dumps(identity).encode()
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                except OSError:
                    return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            yield LaunchDescriptor(
                os.getpid(), "a" * 32, "b" * 64,
                f"http://127.0.0.1:{server.server_port}/?token=test",
            ), requests
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_external_redirect_is_rejected_without_following_it(self) -> None:
        with self.listener(redirect="http://example.invalid/") as (descriptor, requests):
            self.assertFalse(verify_instance(descriptor))
            self.assertEqual(len(requests), 1)

    def test_foreign_local_listener_is_not_accepted_as_aha(self) -> None:
        with self.listener(application="other") as (descriptor, requests):
            self.assertFalse(verify_instance(descriptor))
            self.assertEqual(len(requests), 2)

    def test_probe_wall_budget_cannot_be_extended_by_trickling_headers(self) -> None:
        with self.listener(trickle=True) as (descriptor, _):
            started = time.monotonic()
            self.assertFalse(verify_instance(descriptor, timeout=0.12))
            self.assertLess(time.monotonic() - started, 0.5)

    def test_probe_thread_failure_is_an_unverified_instance(self) -> None:
        descriptor = LaunchDescriptor(
            os.getpid(), "a" * 32, "b" * 64, "http://127.0.0.1:9876/?token=test"
        )
        with patch("aha.instance.threading.Thread.start", side_effect=RuntimeError("no thread")):
            self.assertFalse(verify_instance(descriptor))


class InstanceCLITests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.data = self.root / "data"
        self.processes: list[subprocess.Popen] = []
        self.addCleanup(self.temporary.cleanup)
        self.addCleanup(self.cleanup_processes)

    def launch(self) -> subprocess.Popen:
        process = subprocess.Popen(
            [sys.executable, "-m", "aha", "--data-dir", str(self.data),
             "--no-browser", "--no-tray"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
        )
        self.processes.append(process)
        return process

    def cleanup_processes(self) -> None:
        for process in self.processes:
            stop_owned_server(process, self.data / "runtime.json")

    def wait_descriptor(self) -> dict:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                value = json.loads((self.data / "runtime.json").read_text())
                descriptor = LaunchDescriptor(**{
                    key: value[key] for key in ("pid", "run_id", "profile_id", "bootstrap_url")
                })
                if verify_instance(descriptor):
                    return value
            except (OSError, ValueError, KeyError):
                pass
            time.sleep(0.02)
        self.fail("No ready owned instance")

    def test_five_concurrent_cold_launches_leave_one_service_then_reuse_it(self) -> None:
        processes = [self.launch() for _ in range(5)]
        value = self.wait_descriptor()
        deadline = time.monotonic() + 10
        while sum(process.poll() is None for process in processes) > 1:
            if time.monotonic() >= deadline:
                self.fail("Duplicate launchers did not finish")
            time.sleep(0.02)
        owners = [process for process in processes if process.poll() is None]
        self.assertEqual(len(owners), 1)
        self.assertTrue(all(
            process.returncode == 0 for process in processes if process not in owners
        ))
        for _ in range(3):
            self.assertEqual(self.launch().wait(timeout=10), 0)
            current = self.wait_descriptor()
            self.assertEqual(current["run_id"], value["run_id"])
            self.assertEqual(current["bootstrap_url"], value["bootstrap_url"])
        cookie, _, _ = credentials(value["bootstrap_url"])
        parsed = urlsplit(value["bootstrap_url"])
        client = http.client.HTTPConnection("127.0.0.1", parsed.port, timeout=3)
        try:
            client.request("GET", "/api/status", headers={"Cookie": cookie})
            status = json.loads(client.getresponse().read())
        finally:
            client.close()
        self.assertIsNone(status["startup_sync"], "CLI reuse must not initiate source reads")

    def test_killed_owned_process_releases_lock_and_restarts(self) -> None:
        first = self.launch()
        old = self.wait_descriptor()
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(first.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        else:
            first.kill()
        first.wait(timeout=5)
        self.assertTrue((self.data / "runtime.json").exists())
        second = self.launch()
        current = self.wait_descriptor()
        self.assertIsNone(second.poll())
        self.assertNotEqual(current["run_id"], old["run_id"])


class RuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.data = Path(self.temporary.name) / "data"
        lease = acquire_instance(self.data)
        self.server = create_server(self.data)
        self.runtime = ApplicationRuntime(self.server, lease)
        self.addCleanup(self.runtime.close)

    def assert_lock_held(self) -> None:
        contender = DirectoryLock(self.data)
        try:
            self.assertFalse(contender.acquire())
        finally:
            contender.close()

    def test_identity_is_authenticated_and_does_not_query_business_store(self) -> None:
        self.runtime.start()
        descriptor = LaunchDescriptor(
            os.getpid(), self.server.app.launch_id, self.server.profile_id,
            self.server.bootstrap_url,
        )
        with patch.object(self.server.app.store, "ledger_status", side_effect=AssertionError):
            self.assertTrue(verify_instance(descriptor))
        wrong = LaunchDescriptor(
            descriptor.pid, "e" * 32, descriptor.profile_id, descriptor.bootstrap_url
        )
        self.assertFalse(verify_instance(wrong))
        client = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            client.request("GET", "/api/instance")
            reply = client.getresponse()
            self.assertEqual(reply.status, 401)
            reply.read()
        finally:
            client.close()

    def test_shutdown_waits_for_an_accepted_write_before_releasing_lock(self) -> None:
        self.runtime.start()
        cookie, csrf, _ = credentials(self.server.bootstrap_url)
        entered, release = threading.Event(), threading.Event()
        original = self.server.app.post
        result: list[tuple[int, dict]] = []

        def slow_write(path: str, body: dict) -> object:
            entered.set()
            if not release.wait(5):
                raise RuntimeError("Test did not release write")
            return original(path, body)

        with patch.object(self.server.app, "post", side_effect=slow_write):
            writer = threading.Thread(target=lambda: result.append(post(
                self.server.bootstrap_url, cookie, csrf, "/api/projects", {"name": "保留项目"}
            )))
            writer.start()
            self.assertTrue(entered.wait(3))
            closer = threading.Thread(target=self.runtime.close)
            closer.start()
            try:
                self.assertTrue(self.server.stopping.wait(3))
                self.assert_lock_held()
                self.assertTrue(closer.is_alive())
            finally:
                release.set()
                writer.join(timeout=5)
                closer.join(timeout=5)
        self.assertFalse(closer.is_alive())
        self.assertEqual(result[0][0], 200)
        self.assertFalse((self.data / "runtime.json").exists())
        store = Store(self.data)
        try:
            self.assertEqual(store.config()["projects"][0]["name"], "保留项目")
        finally:
            store.close()

    def test_shutdown_cancels_and_waits_for_sync_worker_before_releasing_lock(self) -> None:
        self.runtime.start()
        cookie, csrf, _ = credentials(self.server.bootstrap_url)
        entered, cancelled, release = threading.Event(), threading.Event(), threading.Event()

        def slow_sync(*args: object, **kwargs: object) -> dict:
            entered.set()
            if self.server.app.cancel.wait(5):
                cancelled.set()
            release.wait(5)
            return {"state": "cancelled"}

        with patch.object(self.server.app.store, "sync_sqlite", side_effect=slow_sync):
            status, _ = post(self.server.bootstrap_url, cookie, csrf, "/api/sync", {})
            self.assertEqual(status, 200)
            self.assertTrue(entered.wait(3))
            closer = threading.Thread(target=self.runtime.close)
            closer.start()
            try:
                self.assertTrue(cancelled.wait(3))
                self.assert_lock_held()
                self.assertTrue(closer.is_alive())
            finally:
                release.set()
                closer.join(timeout=5)
        self.assertFalse(closer.is_alive())
        lease = acquire_instance(self.data)
        self.assertIsInstance(lease, InstanceLease)
        lease.close()

    def test_publication_failure_cleans_service_and_lease(self) -> None:
        port = self.server.server_port
        with patch.object(self.runtime.lease, "publish", side_effect=OSError):
            with self.assertRaises(OSError):
                self.runtime.start()
        self.runtime.close()
        client = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
        try:
            with self.assertRaises(OSError):
                client.connect()
        finally:
            client.close()
        lease = acquire_instance(self.data)
        self.assertIsInstance(lease, InstanceLease)
        lease.close()

    def test_service_thread_start_failure_cleans_listener_and_lease(self) -> None:
        port = self.server.server_port
        with patch("aha.runtime.threading.Thread.start", side_effect=RuntimeError("no thread")):
            with self.assertRaises(AppError) as caught:
                self.runtime.start()
            self.assertEqual(caught.exception.code, "service_unavailable")
            self.runtime.close()
        self.assertFalse((self.data / "runtime.json").exists())
        client = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
        try:
            with self.assertRaises(OSError):
                client.connect()
        finally:
            client.close()
        lease = acquire_instance(self.data)
        self.assertIsInstance(lease, InstanceLease)
        lease.close()

    def test_stopping_rejects_new_writes(self) -> None:
        self.runtime.start()
        cookie, csrf, _ = credentials(self.server.bootstrap_url)
        self.server.mark_stopping()
        status, result = post(
            self.server.bootstrap_url, cookie, csrf, "/api/projects", {"name": "不应保存"}
        )
        self.assertEqual(status, 409)
        self.assertEqual(result["code"], "application_closed")
        self.assertEqual(self.server.app.store.config()["projects"], [])

    def test_tray_initialization_failure_does_not_leave_an_orphan_service(self) -> None:
        class FailedTray:
            closed = False

            def start(self) -> None:
                raise OSError("synthetic tray initialization failure")

            def run(self) -> None:
                raise AssertionError("Failed tray must never enter its loop")

            def stop(self) -> None:
                return

            def close(self) -> None:
                self.closed = True

        tray = FailedTray()
        self.runtime.tray = tray
        with self.assertRaises(OSError):
            self.runtime.start()
        self.runtime.close()
        self.assertTrue(tray.closed)
        self.assertFalse((self.data / "runtime.json").exists())
        lease = acquire_instance(self.data)
        self.assertIsInstance(lease, InstanceLease)
        lease.close()

    def test_exit_during_tray_startup_does_not_publish_or_open_a_page(self) -> None:
        runtime = self.runtime

        class ExitingTray:
            closed = False

            def start(self) -> None:
                runtime.request_shutdown()

            def run(self) -> None:
                raise AssertionError("An exited startup must not enter the native loop")

            def stop(self) -> None:
                return

            def close(self) -> None:
                self.closed = True

        tray = ExitingTray()
        runtime.tray = tray
        output = io.StringIO()
        with (
            patch("aha.__main__.acquire_instance", return_value=runtime.lease),
            patch("aha.__main__.create_server", return_value=self.server),
            patch("aha.__main__.ApplicationRuntime", return_value=runtime),
            patch("aha.__main__.open_browser") as browser,
            patch("sys.stdout", new=output),
        ):
            _launch(self.data, 0, no_browser=False, no_tray=True)
            browser.assert_not_called()
        self.assertEqual(output.getvalue(), "")
        self.assertTrue(tray.closed)
        self.assertFalse((self.data / "runtime.json").exists())
        client = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=1)
        try:
            with self.assertRaises(OSError):
                client.connect()
        finally:
            client.close()
        lease = acquire_instance(self.data)
        self.assertIsInstance(lease, InstanceLease)
        lease.close()

    def test_other_directory_remains_ready_after_first_runtime_closes(self) -> None:
        self.runtime.start()
        other_dir = Path(self.temporary.name) / "other"
        other_lease = acquire_instance(other_dir)
        other_server = create_server(other_dir)
        other = ApplicationRuntime(other_server, other_lease)
        try:
            other.start()
            self.runtime.close()
            descriptor = LaunchDescriptor(
                os.getpid(), other_server.app.launch_id, other_server.profile_id,
                other_server.bootstrap_url,
            )
            self.assertTrue(verify_instance(descriptor))
            self.assertTrue((other_dir / "runtime.json").exists())
        finally:
            other.close()


if __name__ == "__main__":
    unittest.main()
