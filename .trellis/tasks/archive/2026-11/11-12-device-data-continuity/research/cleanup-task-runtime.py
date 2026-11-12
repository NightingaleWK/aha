"""Remove this task's explicitly inventoried QA files using a base interpreter."""

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import time
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    source = Path(__file__).resolve().parents[4]
    research = source / ".trellis/tasks/11-12-device-data-continuity/research"
    delivery = json.loads((research / "delivery.json").read_text(encoding="utf-8"))
    continuation = json.loads((research / "primary-continuation.json").read_text(encoding="utf-8"))
    assert delivery["desktop_started_and_verified"] and continuation["verified"]
    local = Path(os.environ["LOCALAPPDATA"])
    root = local / "Temp/aha-device-continuity-20261112"
    assert root.resolve() == root and not root.is_symlink() and not root.is_junction()
    assert root not in Path(sys.executable).resolve().parents
    assert json.loads((root / "task-ownership.json").read_text())["task"] == "device-data-continuity"
    expected = {
        "build", "mypy-backup", "mypy-backup-review", "mypy-final-check",
        "mypy-http-ui", "mypy-source", "mypy-verifier", "qa", "qa-profile", "qa312",
        "real-copy-182a68e7cf", "real-frozen-restored-37826fb7",
        "real-size-transfer-a51927b9.aha-backup", "task-ownership.json",
        "verify-desktop-final", "verify-directory", "verify-directory-final",
        "verify-onefile", "verify-onefile-final",
    }
    assert {p.name for p in root.iterdir()} == expected, "Unexpected task-root content"
    command = (
        "$r=Join-Path $env:LOCALAPPDATA 'Temp\\aha-device-continuity-20261112'; "
        "@(Get-CimInstance Win32_Process | Where-Object { "
        "($_.ExecutablePath -and $_.ExecutablePath.StartsWith($r,[System.StringComparison]::OrdinalIgnoreCase)) "
        "-or ($_.CommandLine -and $_.CommandLine.Contains($r)) } | "
        "Select-Object Name,ProcessId,ExecutablePath) | ConvertTo-Json -Compress"
    )
    processes = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    assert not processes or json.loads(processes) == [], "A process still uses the QA root"
    files, total = 0, 0
    junctions = []
    for current, directories, names in os.walk(root, followlinks=False):
        for name in list(directories) + names:
            item = Path(current) / name
            assert not item.is_symlink(), "Unexpected symbolic cleanup boundary"
            if item.is_junction():
                assert item.relative_to(root).as_posix() == (
                    "qa-profile/AppData/Local/Microsoft/Windows/INetCache/Content.IE5"
                ), "Unexpected junction boundary"
                assert item.resolve() == item.parent / "IE", "Cache junction left QA root"
                junctions.append(item)
                if name in directories:
                    directories.remove(name)
        for name in names:
            files += 1
            total += (Path(current) / name).stat().st_size
    protected = {
        "desktop": (Path(delivery["desktop"]), delivery["executable_sha256"]),
        "existing_program": (Path(delivery["existing_program"]), delivery["executable_sha256"]),
        "old_program": (Path(delivery["old_executable"]),
                        "0c25c25da9df56f7b82e7fe4cbce9f20613e1e82172c2ac9b620c2b77b0e8f58"),
        "before_backup": (Path(continuation["fresh_prechange_backup"]["archive_path"]),
                          continuation["fresh_prechange_backup"]["sha256"]),
        "after_backup": (Path(continuation["after_backup"]["path"]),
                         continuation["after_backup"]["sha256"]),
    }
    for label, (path, expected_hash) in protected.items():
        assert root not in path.resolve().parents and sha256(path) == expected_hash, label
        if label.endswith("backup"):
            with zipfile.ZipFile(path) as archive:
                assert archive.testzip() is None
    sys.path.insert(0, str(source / "scripts"))
    from verify_windows_artifact import Client
    data = local / "aha"
    descriptor = json.loads((data / "runtime.json").read_text(encoding="utf-8"))
    client = Client(descriptor)
    assert client.json("GET", "/api/instance")["state"] == "ready"
    assert Path(client.json("GET", "/api/status")["data_directory"]).resolve() == data.resolve()
    inventory = {
        "root": str(root), "ownership_verified": True,
        "entries": sorted(expected), "file_count": files, "logical_bytes": total,
        "note": "A previous pass stopped on a read-only object in a synthetic release-test Git fixture. Earlier removed bytes are not counted.",
    }
    (research / "cleanup-inventory.json").write_bytes(
        (json.dumps(inventory, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    )

    def remove_readonly(function, path, error):
        info = os.stat(path, follow_symlinks=False)
        if (isinstance(error, PermissionError)
                and info.st_file_attributes & stat.FILE_ATTRIBUTE_READONLY):
            os.chmod(path, stat.S_IWRITE)
            function(path)
        else:
            raise error

    started = time.monotonic()
    for junction in junctions:
        junction.rmdir()  # Remove the known cache link itself without following it.
    shutil.rmtree(root, onexc=remove_readonly)
    assert not root.exists()
    for label, (path, expected_hash) in protected.items():
        assert sha256(path) == expected_hash, label
    assert client.json("GET", "/api/instance")["state"] == "ready"
    assert not client.json("GET", "/api/source/binding")["required"]
    ledger = client.json("GET", "/api/ledger")
    assert ledger["counts"]["detail_count"] >= continuation["ledger"]["counts"]["detail_count"]
    result = {
        "verified": True,
        "completed_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        "removed_root": str(root),
        "removed_entries": sorted(expected),
        "removed_file_count": files,
        "removed_logical_bytes_lower_bound": total,
        "earlier_partial_cleanup_unmeasured": True,
        "deletion_seconds": round(time.monotonic() - started, 3),
        "processes_using_root": [],
        "cache_junctions_unlinked_without_following": [str(p) for p in junctions],
        "protected_files_verified": {label: str(path) for label, (path, _) in protected.items()},
        "primary_service_ready": True,
        "primary_source_bound": True,
        "primary_counts": ledger["counts"],
        "base_interpreter_preserved": sys.executable,
    }
    (research / "cleanup.json").write_bytes(
        (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
