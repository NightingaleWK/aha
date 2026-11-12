"""Deliver only verified, matching native artifacts; preserve the recognized old EXE."""

import ctypes
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import sqlite3
import struct
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from uuid import uuid4


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def copy_atomic(source, target, expected, allowed_existing):
    assert sha(source) == expected
    if target.exists():
        assert sha(target) in allowed_existing, "Unrecognized existing program"
        if sha(target) == expected:
            return
    temporary = target.with_name(".aha-delivery-" + uuid4().hex + ".tmp")
    try:
        with source.open("rb") as first, temporary.open("xb") as second:
            shutil.copyfileobj(first, second, 1024 * 1024)
            second.flush()
            os.fsync(second.fileno())
        assert sha(temporary) == expected
        os.replace(temporary, target)
        assert sha(target) == expected
    finally:
        temporary.unlink(missing_ok=True)


def main():
    assert sys.platform == "win32"
    source_root = Path(__file__).resolve().parents[4]
    research = source_root / ".trellis/tasks/11-12-device-data-continuity/research"
    tests = json.loads((research / "python-test-result.json").read_text(encoding="utf-8"))
    assert tests["verified"] and tests["tests_run"] >= 317, "Final test gate is incomplete"
    directory = json.loads((research / "directory-verification.json").read_text(encoding="utf-8"))
    onefile = json.loads((research / "onefile-verification.json").read_text(encoding="utf-8"))
    assert directory["verified"] and onefile["verified"]
    for kind, artifact in (("directory-ui-final", directory), ("onefile-ui-final", onefile)):
        report = json.loads((source_root / ".aha-data/device-continuity" / kind / "ui-office-report.json").read_text(encoding="utf-8"))
        assert report["verified"] and report["excel"]["all_cells_match"]
        assert report["print"]["precise_amount_preserved"] and not report["console_errors"]
        assert report["executable_sha256"] == artifact["executable_sha256"]
    fingerprints = json.loads((research / "source-fingerprints.json").read_text())
    assert fingerprints == json.loads((research / "source-fingerprints-after-onefile.json").read_text())
    preserved = json.loads((research / "persistent-recovery.json").read_text(encoding="utf-8"))
    assert sha(Path(preserved["archive"])) == preserved["archive_sha256"]
    assert sha(Path(preserved["old_executable"])) == preserved["old_executable_sha256"]
    task_root = Path(os.environ["LOCALAPPDATA"]) / "Temp" / "aha-device-continuity-20261112"
    executable = task_root / "build/release/portable/aha.exe"
    expected = onefile["executable_sha256"]
    assert sha(executable) == expected
    buffer = ctypes.create_unicode_buffer(32768)
    assert ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buffer) == 0
    desktop = Path(buffer.value)
    assert desktop.is_dir()
    targets = [desktop / "aha.exe", Path("D:/Program Files/aha.exe")]
    for target in targets:
        assert target.parent.is_dir()
        copy_atomic(executable, target, expected, {expected, preserved["old_executable_sha256"]})
    runtime = {"windows": True, "isolated": sys.prefix != sys.base_prefix,
               "bits": struct.calcsize("P") * 8, "python": list(sys.version_info[:3]),
               "machine": platform.machine(), "sqlite": list(sqlite3.sqlite_version_info),
               "sqlite_version": sqlite3.sqlite_version, "packages": {}}
    for line in (source_root / "scripts/requirements-build.txt").read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        name, wanted = line.split("==")
        assert importlib.metadata.version(name) == wanted
        runtime["packages"][name] = wanted
    canonical = lambda value: (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    runtime_fields = {key: value for key, value in runtime.items() if key != "isolated"}
    result = {"delivered_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
               "version": onefile["version"], "executable_sha256": expected,
               "source_ref": "WORKTREE", "source_fingerprints": fingerprints,
               "runtime": runtime, "runtime_sha256": hashlib.sha256(canonical(runtime_fields)).hexdigest(),
               "desktop": str(targets[0]), "existing_program": str(targets[1]),
               "recovery_archive": preserved["archive"], "old_executable": preserved["old_executable"],
               "desktop_started_and_verified": False}
    (research / "delivery.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    shutil.copyfile(task_root / "build/runtime-versions.json", research / "build-runtime-versions.json")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
