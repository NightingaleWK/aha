"""Install the reviewed native cp315 wheel into the task's private release QA venv."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import sqlite3
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path


WHEEL_SHA = "a1c09646b16f6c5c3dfbd6d2074bbe5bdb6cac88d1566762b6ad2d7b4003e178"
RUNTIME_SHA = "2d64ab084e0aa6c3d8ffab874ef7a08fd35b4fbf452dc1353e89d06dc7ea8642"


def require(condition, code):
    if not condition:
        raise RuntimeError(code)


def main():
    source = Path(__file__).resolve().parents[4]
    research = Path(__file__).resolve().parent
    task = Path(os.environ["AHA_RELEASE_QA_ROOT"]).resolve()
    marker = json.loads((task / "task-ownership.json").read_text(encoding="utf-8"))
    require(marker.get("task") == "project-record-continuity" and marker.get("purpose") == "release-v050",
            "task_ownership_mismatch")
    require(sys.platform == "win32" and Path(sys.base_prefix).resolve() == task / "runtime315-sqlite3534"
            and sqlite3.sqlite_version_info == (3, 53, 4) and tuple(sys.version_info[:3]) == (3, 15, 2),
            "private_production_matched_runtime_required")
    require(Path(os.environ["USERPROFILE"]).resolve().is_relative_to(task), "synthetic_profile_required")
    trusted = json.loads((research / "release-trusted-wheel.json").read_text(encoding="utf-8"))
    wheel = task / "trusted-zstd-wheel/zstandard-0.25.0-cp315-cp315-win_amd64.whl"
    provenance = json.loads((wheel.parent / "provenance.json").read_text(encoding="utf-8"))
    require(trusted.get("verified") is True and trusted["provenance"] == provenance
            and provenance["workflow_run_id"] == "43178376925"
            and provenance["wheel"]["sha256"] == WHEEL_SHA
            and provenance["wheel"]["tags"] == ["cp315-cp315-win_amd64"]
            and provenance["verified_native_import_and_roundtrip"] is True,
            "unreviewed_native_wheel_provenance")
    require(hashlib.sha256(wheel.read_bytes()).hexdigest() == WHEEL_SHA, "trusted_wheel_bytes_changed")
    require(hashlib.sha256((source / "scripts/requirements-build.txt").read_bytes()).hexdigest()
            == provenance["requirements_build_sha256"], "wheel_recipe_mismatch")
    log = research / "release-wheel-install.log"
    with log.open("w", encoding="utf-8") as stream:
        installed = subprocess.run([sys.executable, "-X", "utf8", "-m", "pip", "install",
                                   "--disable-pip-version-check", "--no-index", "--no-deps", str(wheel)],
                                  cwd=task, stdout=stream, stderr=subprocess.STDOUT)
        require(installed.returncode == 0, "trusted_wheel_install_failed")
        pinned = subprocess.run([sys.executable, "-X", "utf8", "-m", "pip", "install",
                                "--disable-pip-version-check", "--no-index", "-r",
                                str(source / "scripts/requirements-build.txt")],
                               cwd=task, stdout=stream, stderr=subprocess.STDOUT)
        require(pinned.returncode == 0, "fixed_requirements_validation_failed")
    import zstandard
    import zstandard.backend_c

    require(zstandard.__version__ == "0.25.0" and zstandard.backend == "cext", "native_zstandard_backend_required")
    sample = b"aha synthetic release compression roundtrip\x00" * 4096
    compressed = zstandard.ZstdCompressor().compress(sample)
    require(zstandard.ZstdDecompressor().decompress(compressed) == sample, "native_zstandard_roundtrip_failed")
    backend = Path(zstandard.backend_c.__file__).resolve()
    require(backend.is_relative_to(task / "qa315/Lib/site-packages"), "unexpected_zstandard_provider")
    with zipfile.ZipFile(wheel) as archive:
        members = [name for name in archive.namelist() if name.endswith("backend_c.cp315-win_amd64.pyd")]
        require(len(members) == 1 and hashlib.sha256(backend.read_bytes()).hexdigest()
                == hashlib.sha256(archive.read(members[0])).hexdigest(), "installed_native_backend_bytes_mismatch")
    packages = {}
    for line in (source / "scripts/requirements-build.txt").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            name, separator, version = line.partition("==")
            require(separator and importlib.metadata.version(name) == version, "fixed_package_metadata_drift")
            packages[name.lower().replace("_", "-")] = version
    sys.path.insert(0, str(source / "scripts"))
    import platform
    import release
    import struct

    runtime = {"python": list(sys.version_info[:3]), "sqlite": list(sqlite3.sqlite_version_info),
               "sqlite_version": sqlite3.sqlite_version, "windows": True, "bits": struct.calcsize("P") * 8,
               "machine": platform.machine(), "packages": packages}
    digest = release.runtime_digest(source, "WORKTREE", runtime)
    require(digest == RUNTIME_SHA, "installed_runtime_differs_from_public_production")
    report = {"verified": True, "completed_at": datetime.now(timezone.utc).isoformat(),
              "wheel_sha256": WHEEL_SHA, "workflow_run_id": provenance["workflow_run_id"],
              "install_returncode": installed.returncode, "fixed_requirements_returncode": pinned.returncode,
              "fixed_build_packages": packages, "build_runtime": runtime,
              "qa_tools": {name: importlib.metadata.version(name)
                           for name in ("ruff", "mypy", "playwright", "pywin32", "pypdf", "pymupdf")},
              "runtime_sha256": digest, "runtime_matches_previous_public": True,
              "native_backend": zstandard.backend, "native_backend_sha256": hashlib.sha256(backend.read_bytes()).hexdigest(),
              "native_import_and_roundtrip_verified": True, "real_profile_used": False}
    (research / "release-installed-runtime.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
