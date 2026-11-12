"""Record native 3.15 release-preflight checks with their actual process exit codes."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import re
import sqlite3
import struct
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def stamp():
    return datetime.now(timezone.utc).isoformat()


def source_fingerprints(source, release):
    files = {path.relative_to(source).as_posix() for path in (source / "src/aha").rglob("*")
             if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"}
    groups = {name: {} for name in ("full", "tray", "materials", "recipe")}
    for relative in sorted(files | release.RECIPE_FILES):
        digest = hashlib.sha256(release.normalized(relative, (source / relative).read_bytes())).hexdigest()
        groups["full"][relative] = digest
        if relative in release.RECIPE_FILES:
            groups["recipe"][relative] = digest
        elif Path(relative).name in release.TRAY_FILES:
            groups["tray"][relative] = digest
        elif Path(relative).name in release.MATERIAL_FILES:
            groups["materials"][relative] = digest
    return {name: hashlib.sha256(release.canonical(values)).hexdigest() for name, values in groups.items()}


def main():
    source = Path(__file__).resolve().parents[4]
    research = Path(__file__).resolve().parent
    task = Path(os.environ["AHA_RELEASE_QA_ROOT"]).resolve()
    owned = json.loads((task / "task-ownership.json").read_text(encoding="utf-8"))
    if owned.get("task") != "project-record-continuity" or owned.get("purpose") != "release-v050":
        raise RuntimeError("Release QA ownership mismatch.")
    profile = Path(os.environ["USERPROFILE"]).resolve()
    if not profile.is_relative_to(task) or not Path(os.environ["LOCALAPPDATA"]).resolve().is_relative_to(task):
        raise RuntimeError("Only a synthetic task-owned profile may run these checks.")
    if sys.platform != "win32" or sys.prefix == sys.base_prefix:
        raise RuntimeError("Use the isolated native Windows interpreter.")
    sys.path[:0] = [str(source), str(source / "src"), str(source / "tests"), str(source / "scripts")]
    import aha
    import release
    from aha.migrations import sqlite_wal_safe

    if not Path(aha.__file__).resolve().is_relative_to(source / "src"):
        raise RuntimeError("QA imported a stale installed source package.")
    report = {"verified": False, "purpose": "release-v050", "started_at": stamp(),
              "source_ref": sys.argv[1] if len(sys.argv) == 2 else "WORKTREE",
              "python": list(sys.version_info[:3]), "python_full": sys.version,
              "sqlite": sqlite3.sqlite_version, "sqlite_version": sqlite3.sqlite_version,
              "sqlite_version_info": list(sqlite3.sqlite_version_info), "machine": platform.machine(),
              "windows": sys.platform == "win32", "bits": struct.calcsize("P") * 8,
              "isolated": sys.prefix != sys.base_prefix, "source_version": aha.__version__,
              "candidate_build_started": False, "real_profile_used": False,
              "source_directory": str(source), "source_package": str(Path(aha.__file__).resolve()),
              "task_root": str(task), "qa_python": sys.executable,
              "source_fingerprints": source_fingerprints(source, release), "qa_tools": {},
              "fixed_build_packages": {}, "expected_tests": 351}
    if (report["python"] != [3, 15, 2] or report["bits"] != 64
            or report["sqlite_version_info"] != [3, 53, 4]
            or not sqlite_wal_safe(sqlite3.sqlite_version_info)):
        raise RuntimeError("Native release runtime does not meet the fixed recipe gate.")
    for line in (source / "scripts/requirements-build.txt").read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        name, separator, expected = line.partition("==")
        actual = importlib.metadata.version(name)
        if not separator or actual != expected:
            raise RuntimeError("Fixed build dependency does not match the recipe.")
        report["fixed_build_packages"][name.lower().replace("_", "-")] = actual
    for name in ("ruff", "mypy", "playwright", "pywin32", "pypdf", "pymupdf"):
        report["qa_tools"][name] = importlib.metadata.version(name)
    runtime = {"python": report["python"], "sqlite": report["sqlite_version_info"],
               "sqlite_version": report["sqlite"], "windows": report["windows"],
               "bits": report["bits"], "machine": report["machine"],
               "packages": report["fixed_build_packages"]}
    report["runtime_sha256"] = release.runtime_digest(source, "WORKTREE", runtime)
    if report["runtime_sha256"] != "2d64ab084e0aa6c3d8ffab874ef7a08fd35b4fbf452dc1353e89d06dc7ea8642":
        raise RuntimeError("Installed runtime differs from the previously public production recipe.")
    report_path = research / "python315-release.json"

    def save():
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    save()
    commands = [
        ("python_tests", [sys.executable, "-X", "utf8", "-B", "-m", "unittest", "discover", "-s", "tests", "-v"]),
        ("ruff", [sys.executable, "-m", "ruff", "check", "src", "tests", "scripts"]),
        ("mypy", [sys.executable, "-m", "mypy", "src/aha", "--cache-dir", str(task / "mypy-release-win"), "--no-incremental"]),
        ("compileall", [sys.executable, "-X", "pycache_prefix=" + str(task / "compiled-source"), "-m", "compileall", "-q", "src/aha"]),
    ]
    for name, command in commands:
        log = research / ("release-" + name.replace("_", "-") + ".log")
        started_at = stamp()
        with log.open("w", encoding="utf-8") as stream:
            result = subprocess.run(command, cwd=source, stdout=stream, stderr=subprocess.STDOUT)
        report[name] = {"returncode": result.returncode, "passed": result.returncode == 0,
                        "started_at": started_at, "completed_at": stamp(),
                        "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest()}
        if name == "python_tests":
            text = log.read_text(encoding="utf-8")
            counts = re.findall(r"(?m)^Ran (\d+) tests? in ", text)
            report["tests_run"] = int(counts[0]) if len(counts) == 1 else 0
            report["python_tests_passed"] = result.returncode == 0 and report["tests_run"] == 351
            report["failures"] = sum(int(value) for value in re.findall(r"failures=(\d+)", text))
            report["errors"] = sum(int(value) for value in re.findall(r"errors=(\d+)", text))
            report["skipped"] = sum(int(value) for value in re.findall(r"skipped=(\d+)", text))
        save()
    report["source_fingerprints_after"] = source_fingerprints(source, release)
    report["source_unchanged"] = report["source_fingerprints"] == report["source_fingerprints_after"]
    report["verified"] = (report["python_tests_passed"] and report["source_unchanged"]
                          and all(report[name]["passed"] for name, _ in commands))
    report["completed_at"] = stamp()
    save()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
