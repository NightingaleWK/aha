"""Verify/deliver official v0.5.1 bytes and clean only this release's QA files."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4


ROOT = Path("C:/Users/djsyw/AppData/Local/Temp/aha-release-v051-20261113")
RESEARCH = Path(__file__).resolve().parent
SOURCE = next(p for p in RESEARCH.parents if (p / "pyproject.toml").is_file())


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def now():
    return datetime.now(timezone(timedelta(hours=8))).isoformat()


def desktop_path():
    buffer = ctypes.create_unicode_buffer(32768)
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    shell.SHGetFolderPathW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p,
                                     ctypes.c_uint32, ctypes.c_wchar_p]
    shell.SHGetFolderPathW.restype = ctypes.c_long
    assert shell.SHGetFolderPathW(None, 0x10, None, 0, buffer) == 0
    return Path(buffer.value).resolve(strict=True) / "aha.exe"


def process_image(pid):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.QueryFullProcessImageNameW.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
        ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_uint32)]
    handle = kernel.OpenProcess(0x1000, False, pid)
    assert handle
    try:
        value, size = ctypes.create_unicode_buffer(32768), ctypes.c_uint32(32768)
        assert kernel.QueryFullProcessImageNameW(handle, 0, value, ctypes.byref(size))
        return Path(value.value).resolve()
    finally:
        kernel.CloseHandle(handle)


def processes():
    command = ["powershell.exe", "-NoProfile", "-Command",
        '[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); '
        'Get-CimInstance Win32_Process | Where-Object {$_.Name -eq "aha.exe"} | '
        'Select-Object ProcessId,ExecutablePath,CommandLine | ConvertTo-Json -Compress']
    result = subprocess.run(command, check=True, capture_output=True, text=True, encoding="utf-8")
    value = json.loads(result.stdout) if result.stdout.strip() else []
    return value if isinstance(value, list) else [value]


def arguments(command):
    shell, kernel = ctypes.WinDLL("shell32"), ctypes.WinDLL("kernel32")
    shell.CommandLineToArgvW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
    shell.CommandLineToArgvW.restype = ctypes.POINTER(ctypes.c_wchar_p)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    count = ctypes.c_int()
    pointer = shell.CommandLineToArgvW(command, ctypes.byref(count))
    assert pointer
    try:
        return [pointer[i] for i in range(count.value)]
    finally:
        kernel.LocalFree(pointer)


def stop_owned_instances(target, artifact):
    restarted = []
    seen = set()
    for item in processes():
        if not item.get("ExecutablePath") or Path(item["ExecutablePath"]).resolve() != target:
            continue
        argv = arguments(item["CommandLine"])
        data = (Path(argv[argv.index("--data-dir") + 1]) if "--data-dir" in argv
                else Path(os.environ["LOCALAPPDATA"]) / "aha").resolve()
        if data in seen:
            continue
        seen.add(data)
        path = data / "runtime.json"
        descriptor = read(path)
        assert process_image(descriptor["pid"]) == target
        client = artifact.Client(descriptor)
        assert Path(client.json("GET", "/api/status")["data_directory"]).resolve() == data
        client.json("POST", "/api/shutdown", {})
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            with socket.socket() as probe:
                probe.settimeout(0.2)
                closed = probe.connect_ex(("127.0.0.1", client.port)) != 0
            if not path.exists() and closed:
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("Owned prior instance did not exit normally.")
        flags = [flag for flag in ("--no-browser", "--no-tray") if flag in argv]
        restarted.append((data, flags))
    return restarted


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["verify", "deliver", "cleanup"])
    args = parser.parse_args()
    assert sys.platform == "win32"
    marker = read(ROOT / "task-ownership.json")
    assert marker["task"] == "ccs-schema-26" and marker["purpose"] == "release-v051"
    identity = read(RESEARCH / "release-v051-identity.json")
    if args.action == "cleanup":
        assert not Path(sys.executable).is_relative_to(ROOT)
        delivery = read(RESEARCH / "release-v051-desktop-delivery.json")
        target = Path(delivery["destination"])
        assert delivery["verified"] and sha(target) == delivery["executable_sha256"]
        observed = subprocess.run(["powershell.exe", "-NoProfile", "-Command",
            "[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); "
            "Get-CimInstance Win32_Process | Select-Object ProcessId,ExecutablePath | ConvertTo-Json -Compress"],
            check=True, capture_output=True, text=True, encoding="utf-8")
        assert not [p for p in json.loads(observed.stdout) if p.get("ExecutablePath")
                    and Path(p["ExecutablePath"]).is_relative_to(ROOT)]
        inventory = []
        total = 0
        for child in ROOT.iterdir():
            assert child.name in {"qa", "downloads", "official-verification", "desktop-verification",
                                  "task-ownership.json"}
            size = 0
            for path in [child, *child.rglob("*")] if child.is_dir() else [child]:
                assert not path.is_symlink() and not path.is_junction()
                assert path.resolve().is_relative_to(ROOT)
                if path.is_file():
                    size += path.stat().st_size
            total += size
            inventory.append({"path": child.name, "bytes": size})
        assert not list(ROOT.rglob("runtime.json"))
        write(RESEARCH / "release-v051-cleanup-inventory.json", inventory)
        shutil.rmtree(ROOT)
        assert not ROOT.exists() and sha(target) == delivery["executable_sha256"]
        result = {"verified": True, "task_root_absent": True, "removed_bytes": total,
            "removed_mib": round(total / 1024 / 1024, 2), "desktop_preserved": True,
            "executable_sha256": sha(target), "rollback_program_preserved": delivery["backup"],
            "completed_at": now()}
        write(RESEARCH / "release-v051-cleanup.json", result)
        print(json.dumps(result), flush=True)
        return
    assert sys.prefix != sys.base_prefix
    sys.path.insert(0, str(SOURCE / "scripts"))
    import verify_windows_artifact as artifact
    assert artifact.read_source_version(SOURCE) == "0.5.1"
    public = read(RESEARCH / "release-v051-public-assets.json")
    executable = ROOT / "downloads/aha-0.5.1-windows-x64.exe"
    info = read(ROOT / "downloads/build-info.json")
    assert public["draft"] is False and public["prerelease"] is False
    assert info["source_sha"] == identity["source_sha"] and info["version"] == "0.5.1"
    assert info["executable"]["sha256"] == sha(executable)
    assert info["fingerprints"] == identity["fingerprints"]
    if args.action == "verify":
        checked = artifact.verify(executable, SOURCE, ROOT / "official-verification", with_tray=True)
        checked.update(source_sha=info["source_sha"], runtime_sha256=info["runtime_sha256"],
                       qa_python=list(sys.version_info[:3]), qa_sqlite=sqlite3.sqlite_version,
                       runtime_identity_from_verified_build_info=True)
        write(RESEARCH / "release-v051-official-verification.json", checked)
        print(json.dumps({"verified": True, "version": "0.5.1", "executable_sha256": sha(executable)}), flush=True)
        return
    checked = read(RESEARCH / "release-v051-official-verification.json")
    assert checked["verified"] and checked["executable_sha256"] == sha(executable)
    target = desktop_path()
    old = sha(target) if target.is_file() else None
    assert not target.is_symlink()
    assert old in {None, identity["previous_desktop_sha256"], sha(executable),
                   "8991fa71cadd906678cb1b76d302921d1e874f022918f854a0540f2bb3d0e4d5"}
    backup = None
    if old and old != sha(executable):
        folder = Path(os.environ["LOCALAPPDATA"]) / "aha-program-backups" / ("before-v0.5.1-" + old[:12])
        if folder.exists():
            assert read(folder / "ownership.json")["sha256"] == old
        else:
            folder.mkdir(parents=True)
            write(folder / "ownership.json", {"purpose": "program-rollback", "sha256": old})
        backup = folder / "aha.exe"
        if not backup.exists():
            shutil.copy2(target, backup)
        assert sha(backup) == old
    restart = stop_owned_instances(target, artifact)
    temporary = target.with_name(".aha-v051-" + uuid4().hex + ".tmp")
    try:
        shutil.copy2(executable, temporary)
        assert sha(temporary) == info["executable"]["sha256"]
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    desktop_check = artifact.verify(target, SOURCE, ROOT / "desktop-verification", with_tray=True)
    write(RESEARCH / "release-v051-desktop-verification.json", desktop_check)
    for data, flags in restart:
        process = subprocess.Popen([str(target), "--data-dir", str(data), *flags],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        descriptor = artifact.wait_descriptor(data / "runtime.json", process)
        assert artifact.Client(descriptor).json("GET", "/api/status")["version"] == "0.5.1"
    result = {"verified": True, "version": "0.5.1", "destination": str(target),
        "source_sha": info["source_sha"], "runtime_sha256": info["runtime_sha256"],
        "executable_sha256": sha(target), "official_published_asset": True,
        "known_folder_checked": True, "backup": str(backup) if backup else None,
        "prior_running_instances_restarted": len(restart), "isolated_desktop_validation_passed": True,
        "completed_at": now()}
    assert sha(target) == info["executable"]["sha256"]
    write(RESEARCH / "release-v051-desktop-delivery.json", result)
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
