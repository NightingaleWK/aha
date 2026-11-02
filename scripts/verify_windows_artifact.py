"""Verify an actual Windows EXE with isolated synthetic sources and local HTTP."""

from __future__ import annotations

import argparse
import base64
import csv
import ctypes
import hashlib
import http.client
import io
import json
import os
import runpy
import sqlite3
import subprocess
import sys
import time
import zipfile
from contextlib import closing
from ctypes import wintypes
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from build_windows import read_source_version

BEIJING = timezone(timedelta(hours=8))
MEMBER_NAMES = {"使用明细.csv", "每日汇总.csv", "费用说明.html", "导出信息.json"}
ROW_COUNT = 3
EXPECTED_COST = Decimal("0.570000003")
EXPECTED_TOKENS = 315


class VerificationError(ValueError):
    """Safe verification failure that does not include credentials or private paths."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def pe_version(executable: Path) -> dict[str, Any]:
    """Read fixed and string Windows version fields through the native API."""
    if sys.platform != "win32":
        raise VerificationError("Native Windows is required for PE inspection.")
    api = ctypes.WinDLL("version", use_last_error=True)
    api.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
    api.GetFileVersionInfoSizeW.restype = wintypes.DWORD
    api.GetFileVersionInfoW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
    ]
    api.GetFileVersionInfoW.restype = wintypes.BOOL
    api.VerQueryValueW.argtypes = [
        wintypes.LPCVOID, wintypes.LPCWSTR,
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT),
    ]
    api.VerQueryValueW.restype = wintypes.BOOL
    unused = wintypes.DWORD()
    size = api.GetFileVersionInfoSizeW(str(executable), ctypes.byref(unused))
    require(bool(size), "EXE has no readable Windows version resource.")
    buffer = ctypes.create_string_buffer(size)
    require(bool(api.GetFileVersionInfoW(str(executable), 0, size, buffer)),
            "Cannot read Windows version resource.")

    def query(key: str) -> ctypes.c_void_p:
        pointer, length = ctypes.c_void_p(), wintypes.UINT()
        require(bool(api.VerQueryValueW(buffer, key, ctypes.byref(pointer),
                                       ctypes.byref(length))) and bool(pointer.value),
                "Windows version resource is incomplete.")
        return pointer

    fixed = ctypes.cast(query("\\"), ctypes.POINTER(wintypes.DWORD))
    require(fixed[0] == 0xFEEF04BD, "Windows fixed version signature is invalid.")
    result: dict[str, Any] = {}
    for name, offset in (("file", 2), ("product", 4)):
        result[name + "_version_parts"] = [
            fixed[offset] >> 16, fixed[offset] & 0xFFFF,
            fixed[offset + 1] >> 16, fixed[offset + 1] & 0xFFFF,
        ]
        key = "FileVersion" if name == "file" else "ProductVersion"
        result[name + "_version"] = ctypes.wstring_at(
            query("\\StringFileInfo\\040904B0\\" + key)
        )
    return result


def isolated_environment(root: Path) -> tuple[dict[str, str], Path]:
    """Refuse unknown nonempty directories; never borrow a real user profile."""
    if root.exists():
        require(root.is_dir() and not any(root.iterdir()),
                "Verification data root must be new or empty.")
    root.mkdir(parents=True, exist_ok=True)
    (root / ".aha-artifact-verification.json").write_text(
        json.dumps({"schema_version": 1, "owner": "aha-artifact-verification"}) + "\n",
        encoding="utf-8",
    )
    profile = root / "synthetic-profile"
    for relative in (".cc-switch", ".codex", "AppData/Local", "AppData/Roaming", "Temp"):
        (profile / relative).mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env.update({
        "USERPROFILE": str(profile), "HOME": str(profile),
        "HOMEDRIVE": profile.drive, "HOMEPATH": str(profile)[len(profile.drive):],
        "LOCALAPPDATA": str(profile / "AppData/Local"),
        "APPDATA": str(profile / "AppData/Roaming"),
        "XDG_CONFIG_HOME": str(profile / ".config"),
        "XDG_DATA_HOME": str(profile / ".local/share"),
        "TEMP": str(profile / "Temp"), "TMP": str(profile / "Temp"),
    })
    return env, profile


class Client:
    def __init__(self, descriptor: dict[str, Any]) -> None:
        address = descriptor.get("bootstrap_url")
        if not isinstance(address, str):
            raise VerificationError("Missing private launch address.")
        parsed = urlsplit(address)
        tokens = parse_qs(parsed.query, max_num_fields=2)
        require(
            parsed.scheme == "http" and parsed.hostname == "127.0.0.1"
            and parsed.port is not None and 0 < parsed.port < 65536
            and parsed.path == "/" and not parsed.username and not parsed.password
            and not parsed.fragment and set(tokens) == {"token"}
            and len(tokens["token"]) == 1 and len(tokens["token"][0]) >= 16,
            "Launch descriptor does not name an allowed loopback service.",
        )
        self.port = parsed.port
        self.origin = f"http://127.0.0.1:{self.port}"
        self.cookie, self.csrf = "", ""
        status, headers, _ = self.request("GET", "/?" + parsed.query, expected=303)
        require(status == 303 and headers.get("location") == "/",
                "Bootstrap authentication did not redirect locally.")
        cookie = headers.get("set-cookie", "")
        require("HttpOnly" in cookie and "SameSite=Strict" in cookie,
                "Bootstrap cookie lacks required protections.")
        self.cookie = cookie.split(";", 1)[0]
        identity = self.json("GET", "/api/instance")
        require(
            identity.get("application") == "aha"
            and identity.get("state") == "ready"
            and all(identity.get(key) == descriptor.get(key)
                    for key in ("protocol_version", "run_id", "profile_id")),
            "Launch identity does not match the owned instance.",
        )
        self.csrf = self.json("GET", "/api/status")["csrf_token"]

    def request(
        self, method: str, path: str, body: dict[str, Any] | None = None,
        *, expected: int = 200,
    ) -> tuple[int, dict[str, str], bytes]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        headers = {"Cookie": self.cookie} if self.cookie else {}
        payload = None
        if body is not None:
            payload = json.dumps(body).encode("utf-8")
            headers.update({"Content-Type": "application/json", "Origin": self.origin,
                            "X-AHA-CSRF": self.csrf})
        try:
            connection.request(method, path, body=payload, headers=headers)
            response = connection.getresponse()
            raw = response.read(8 * 1024 * 1024 + 1)
            require(response.status == expected, "Unexpected HTTP status during artifact check.")
            require(len(raw) <= 8 * 1024 * 1024, "Artifact response exceeded synthetic limits.")
            return response.status, {k.lower(): v for k, v in response.getheaders()}, raw
        finally:
            connection.close()

    def json(
        self, method: str, path: str, body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        value = json.loads(self.request(method, path, body)[2])
        if not isinstance(value, dict):
            raise VerificationError("Expected an object from artifact HTTP API.")
        return value

    def sync(self, body: dict[str, Any], *, sql: bool = False) -> dict[str, Any]:
        job = self.json("POST", "/api/source/sql" if sql else "/api/sync", body)
        job_id = job["id"]
        deadline = time.monotonic() + 30
        while job["status"] == "running":
            require(time.monotonic() < deadline,
                    "Synthetic sync did not reach its own terminal job.")
            time.sleep(0.05)
            job = self.json("GET", "/api/sync/" + job_id)
        return job


def wait_descriptor(path: Path, process: subprocess.Popen[bytes]) -> dict[str, Any]:
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        if path.is_file():
            value = json.loads(path.read_text("utf-8"))
            if not isinstance(value, dict):
                raise VerificationError("Launch descriptor is not an object.")
            return value
        require(process.poll() is None, "EXE exited before publishing an owned descriptor.")
        time.sleep(0.05)
    raise VerificationError("EXE did not become ready within the startup budget.")


def stop_process(process: subprocess.Popen[bytes], client: Client | None) -> None:
    if process.poll() is not None:
        return
    if client is not None:
        try:
            client.json("POST", "/api/shutdown", {})
            process.wait(timeout=20)
            return
        except (OSError, ValueError, http.client.HTTPException, subprocess.TimeoutExpired):
            pass
    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, check=False)
    process.wait(timeout=10)


def check_shutdown(client: Client, process: subprocess.Popen[bytes], descriptor: Path) -> None:
    client.json("POST", "/api/shutdown", {})
    require(process.wait(timeout=20) == 0, "EXE did not exit successfully.")
    require(not descriptor.exists(), "Owned runtime descriptor remained after shutdown.")
    connection = http.client.HTTPConnection("127.0.0.1", client.port, timeout=1)
    try:
        try:
            connection.connect()
        except OSError:
            return
        raise VerificationError("Owned service port remained open after shutdown.")
    finally:
        connection.close()


def check_material(raw: bytes, version: str, output: Path) -> str:
    """Check known synthetic values, per-file digests and frozen package identity."""
    with zipfile.ZipFile(io.BytesIO(raw)) as package:
        require(set(package.namelist()) == MEMBER_NAMES and len(package.namelist()) == 4,
                "Evidence package must contain exactly the four expected files.")
        require(sum(member.file_size for member in package.infolist()) < 4 * 1024 * 1024,
                "Evidence exceeded the synthetic size budget.")
        files = {name: package.read(name) for name in MEMBER_NAMES}
    manifest = json.loads(files["导出信息.json"])
    require(manifest["application"] == {"name": "aha", "version": version},
            "Evidence application version differs from the EXE.")
    summary = manifest["summary"]
    require(summary["record_count"] == ROW_COUNT
            and Decimal(summary["total_cost_usd"]) == EXPECTED_COST
            and summary["total_tokens"] == EXPECTED_TOKENS
            and len(manifest["members"]) == ROW_COUNT,
            "Frozen evidence does not preserve the synthetic members or precise totals.")
    for name in MEMBER_NAMES - {"导出信息.json"}:
        require(manifest["files"][name]["sha256"] == hashlib.sha256(files[name]).hexdigest()
                and manifest["files"][name]["bytes"] == len(files[name]),
                "Evidence per-file SHA256 or byte count differs.")
    require(files["使用明细.csv"].startswith(b"\xef\xbb\xbf"), "CSV BOM is missing.")
    rows = list(csv.DictReader(io.StringIO(files["使用明细.csv"].decode("utf-8-sig"))))
    require(len(rows) == ROW_COUNT
            and sum((Decimal(row["total_cost_usd"]) for row in rows), Decimal()) == EXPECTED_COST
            and sum(int(row["total_tokens"]) for row in rows) == EXPECTED_TOKENS
            and all(row["model"] == "合成模型" for row in rows),
            "CSV contents differ from the frozen synthetic totals.")
    require(str(EXPECTED_COST) in files["费用说明.html"].decode("utf-8"),
            "HTML report lost the precise synthetic reference cost.")
    output.mkdir()
    for name, contents in files.items():
        (output / name).write_bytes(contents)
    (output / "evidence.zip").write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def verify(
    executable: Path, source_root: Path, data_root: Path, *, with_tray: bool = False,
) -> dict[str, Any]:
    require(sys.platform == "win32", "Run artifact verification with native Windows Python.")
    version = read_source_version(source_root)
    resource = pe_version(executable)
    expected_parts = [int(part) for part in version.split(".")] + [0]
    require(all(resource[key + "_version"] == version
                and resource[key + "_version_parts"] == expected_parts
                for key in ("file", "product")),
            "EXE Windows version does not match the source product version.")
    env, profile = isolated_environment(data_root)
    # Reuse existing synthetic fixtures rather than constructing a second source schema.
    sys.path.insert(0, str(source_root / "src"))
    fixtures = runpy.run_path(str(source_root / "tests" / "test_sources.py"))
    event = int(datetime.fromisoformat("2026-10-26T08:00:00+08:00").timestamp())
    rows = [fixtures["detail"](request_id=f"artifact-{n}", session_id=None,
                               model="合成模型", total_cost_usd="0.190000001",
                               created_at=event + n) for n in range(ROW_COUNT)]
    source = profile / ".cc-switch" / "cc-switch.db"
    fixtures["database"](source, rows, version=23).close()
    data_dir = data_root / "store"
    descriptor = data_dir / "runtime.json"
    command = [str(executable), "--data-dir", str(data_dir), "--no-browser"]
    if not with_tray:
        command.append("--no-tray")
    batch_id, material_sha = "", ""
    for iteration in range(2):
        process = subprocess.Popen(command, cwd=profile, env=env,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        client = None
        try:
            launch = wait_descriptor(descriptor, process)
            client = Client(launch)
            require(client.json("GET", "/api/status")["version"] == version,
                    "Runtime version does not match the source.")
            if iteration == 0:
                for name in ("index.html", "app.js", "form-controls.js", "time-range-picker.js",
                             "style.css", "mark.svg"):
                    route = "/" if name == "index.html" else "/" + name
                    require(client.request("GET", route)[2]
                            == (source_root / "src" / "aha" / "web" / name).read_bytes(),
                            "Packaged HTTP resource differs from the source.")
                require(b"CPython" in client.request("GET", "/licenses")[2],
                        "Packaged runtime license notices are missing.")
                job = client.sync({"trigger": "startup"})
                startup_job_id = job["id"]
                require(job["status"] == "completed"
                        and job["result"]["source_schema_version"] == 23,
                        "Synthetic CCS23 startup sync failed.")
                with closing(sqlite3.connect(source)) as connection:
                    connection.execute("PRAGMA user_version=24")
                    connection.commit()
                job = client.sync({})
                require(job["status"] == "completed"
                        and job["result"]["source_schema_version"] == 24
                        and job["result"]["new_count"] == 0,
                        "Synthetic CCS24 sync did not preserve existing usage.")
                raw_sql = fixtures["dump"](rows, [], [fixtures["price"]()], version=24)
                job = client.sync({"name": "synthetic-24.sql",
                                   "content_base64": base64.b64encode(raw_sql).decode()}, sql=True)
                require(job["status"] == "completed"
                        and job["result"]["source_schema_version"] == 24,
                        "Synthetic SQL24 import failed.")
                analysis = client.json("POST", "/api/analysis", {
                    "start_date": "2026-10-26", "end_date": "2026-10-26",
                    "project_id": "all", "availability_mode": "available",
                })
                require(analysis["summary"]["record_count"] == ROW_COUNT,
                        "Version changes or SQL import duplicated synthetic usage.")
                saved = client.json("POST", "/api/batches", {
                    "analysis_id": analysis["analysis_id"],
                    "claim": {"purpose": "合成成品验收", "amount": "", "currency": "CNY",
                              "amount_note": ""},
                    "idempotency_key": "artifact-verification-save-0001",
                })
                batch_id = saved.get("batch_id", saved.get("id", ""))
                require(bool(batch_id), "Save did not return an evidence batch.")
                raw = client.request("GET", f"/api/batches/{batch_id}/revisions/1/download")[2]
                material_sha = check_material(raw, version, data_root / "material")
                reopened = subprocess.run(command, cwd=profile, env=env,
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                          timeout=30, check=False)
                require(reopened.returncode == 0
                        and json.loads(descriptor.read_text("utf-8")) == launch,
                        "Reopening did not reuse the same owned instance.")
                require(client.json("POST", "/api/sync", {"trigger": "startup"})["id"]
                        == startup_job_id,
                        "Reopening did not preserve the startup job.")
            else:
                raw = client.request("GET", f"/api/batches/{batch_id}/revisions/1/download")[2]
                require(hashlib.sha256(raw).hexdigest() == material_sha,
                        "Frozen evidence changed after a complete restart.")
            check_shutdown(client, process, descriptor)
        finally:
            stop_process(process, client)
    return {
        "schema_version": 1, "verified": True, "version": version,
        "executable_sha256": digest(executable), "pe_version": resource,
        "material_sha256": material_sha,
        "verified_at": datetime.now(BEIJING).isoformat(timespec="seconds"),
        "scopes": ["native-exe", "pe-version", "http-authentication", "resource-bytes",
                   "ccs-23-24", "sql-24", "frozen-material", "same-directory-reopen",
                   "persistent-restart", "shutdown-cleanup"],
        "tray_enabled": with_tray, "tray_physical_checked": False,
        "browser_driven": False, "office_checked": False, "manual_checks": [],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify a built Windows aha EXE in isolation")
    parser.add_argument("--exe", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--with-tray", action="store_true")
    args = parser.parse_args()
    try:
        result = verify(args.exe.resolve(strict=True), args.source_root.resolve(strict=True),
                        args.data_root.resolve(), with_tray=args.with_tray)
    except Exception as error:
        result = {"schema_version": 1, "verified": False, "error_code": type(error).__name__,
                  "message": str(error) if isinstance(error, VerificationError)
                  else "Artifact verification could not complete; inspect the owned fixture."}
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", "utf-8")
        parser.exit(1, f"Artifact verification failed ({type(error).__name__}).\n")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print("AHA_ARTIFACT_VERIFIED=true", flush=True)


if __name__ == "__main__":
    main()
