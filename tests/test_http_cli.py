"""Exercise the real CLI launch descriptor, authenticated shutdown and port release."""

from __future__ import annotations

import http.client
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from urllib.parse import urlsplit


def stop_owned_server(process: subprocess.Popen[bytes], descriptor: Path) -> None:
    """Try authenticated shutdown before terminating a Windows launcher's child tree."""
    if process.poll() is not None:
        return
    try:
        launch = json.loads(descriptor.read_text(encoding="utf-8"))
        parsed = urlsplit(launch["bootstrap_url"])
        if parsed.hostname != "127.0.0.1":
            raise ValueError("unexpected launch host")
        client = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=2)
        try:
            client.request("GET", "/?" + parsed.query)
            reply = client.getresponse()
            raw_cookie = reply.getheader("Set-Cookie")
            reply.read()
            if reply.status != 303 or raw_cookie is None:
                raise ValueError("launch authentication failed")
            cookie = raw_cookie.split(";", 1)[0]
            client.request("GET", "/api/status", headers={"Cookie": cookie})
            reply = client.getresponse()
            status = json.loads(reply.read())
            client.request(
                "POST",
                "/api/shutdown",
                body="{}",
                headers={
                    "Cookie": cookie,
                    "Origin": f"http://{parsed.netloc}",
                    "Content-Type": "application/json",
                    "X-AHA-CSRF": status["csrf_token"],
                },
            )
            reply = client.getresponse()
            reply.read()
        finally:
            client.close()
        process.wait(timeout=5)
        return
    except (OSError, ValueError, KeyError, http.client.HTTPException, subprocess.TimeoutExpired):
        pass
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
    elif process.poll() is None:
        process.kill()
    process.wait(timeout=5)


class CLILifecycleTests(unittest.TestCase):
    def test_failure_cleanup_shuts_down_the_owned_server(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary) / "data"
            source_root = Path(__file__).resolve().parents[1] / "src"
            process = subprocess.Popen(
                [
                    sys.executable, "-m", "aha", "--data-dir", str(data_dir),
                    "--no-browser", "--no-tray",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env={**os.environ, "PYTHONPATH": str(source_root)},
            )
            descriptor = data_dir / "runtime.json"
            try:
                deadline = time.monotonic() + 10
                while not descriptor.exists() and process.poll() is None:
                    if time.monotonic() > deadline:
                        self.fail("CLI did not create its private launch descriptor")
                    time.sleep(0.02)
                launch = json.loads(descriptor.read_text(encoding="utf-8"))
                parsed = urlsplit(launch["bootstrap_url"])
            finally:
                # Exercise cleanup before the test has created any authenticated client.
                stop_owned_server(process, descriptor)
            self.assertEqual(process.returncode, 0)
            self.assertFalse(descriptor.exists())
            with self.assertRaises(OSError):
                client = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=1)
                try:
                    client.connect()
                finally:
                    client.close()

    def test_private_launch_descriptor_shutdown_and_persistent_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary) / "data"
            source_root = Path(__file__).resolve().parents[1] / "src"
            env = dict(os.environ)
            env["PYTHONPATH"] = str(source_root)
            for iteration in range(2):
                process = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "aha",
                        "--data-dir",
                        str(data_dir),
                        "--port",
                        "0",
                        "--no-browser",
                        "--no-tray",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=env,
                )
                descriptor = data_dir / "runtime.json"
                try:
                    deadline = time.monotonic() + 10
                    while not descriptor.exists() and process.poll() is None:
                        if time.monotonic() > deadline:
                            self.fail("CLI did not create its private launch descriptor")
                        time.sleep(0.02)
                    self.assertIsNone(process.poll(), "CLI exited before serving")
                    launch = json.loads(descriptor.read_text(encoding="utf-8"))
                    self.assertIsInstance(launch["pid"], int)
                    self.assertGreater(launch["pid"], 0)
                    # Windows venv python.exe may remain as a launcher for the server child.
                    if os.name != "nt":
                        self.assertEqual(launch["pid"], process.pid)
                        self.assertEqual(descriptor.stat().st_mode & 0o777, 0o600)
                    parsed = urlsplit(launch["bootstrap_url"])
                    self.assertEqual(parsed.hostname, "127.0.0.1")
                    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
                    connection.request("GET", "/?" + parsed.query)
                    response = connection.getresponse()
                    self.assertEqual(response.status, 303)
                    cookie = response.getheader("Set-Cookie").split(";", 1)[0]
                    response.read()
                    connection.close()

                    def request(method: str, path: str, body: dict[str, str] | None = None) -> dict:
                        client = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
                        headers = {"Cookie": cookie}
                        raw = None
                        if body is not None:
                            raw = json.dumps(body)
                            headers.update(
                                {
                                    "Origin": f"http://{parsed.netloc}",
                                    "Content-Type": "application/json",
                                    "X-AHA-CSRF": status["csrf_token"],
                                }
                            )
                        client.request(method, path, body=raw, headers=headers)
                        reply = client.getresponse()
                        result = json.loads(reply.read())
                        self.assertEqual(reply.status, 200, result)
                        client.close()
                        return result

                    status = request("GET", "/api/status")
                    if iteration == 0:
                        request("POST", "/api/projects", {"name": "重启保留项目"})
                    else:
                        self.assertEqual(
                            request("GET", "/api/projects")["projects"][0]["name"], "重启保留项目"
                        )
                    request("POST", "/api/shutdown", {})
                    self.assertEqual(process.wait(timeout=10), 0)
                    self.assertFalse(descriptor.exists())
                    with self.assertRaises(OSError):
                        client = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=1)
                        try:
                            client.connect()
                        finally:
                            client.close()
                finally:
                    stop_owned_server(process, descriptor)


if __name__ == "__main__":
    unittest.main()
