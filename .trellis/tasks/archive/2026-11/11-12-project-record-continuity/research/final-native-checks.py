"""Collect final native checks with return codes and platform-local caches."""

import json
import os
import sqlite3
import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


def main():
    source = Path(__file__).resolve().parents[4]
    research = source / ".trellis/tasks/11-12-project-record-continuity/research"
    task = Path(os.environ["AHA_QA_ROOT"])
    sys.path.insert(0, str(source / "tests"))
    sys.path.insert(0, str(source / "src"))
    sys.path.insert(0, str(source))
    report = {"verified": False, "python": list(sys.version_info[:3]), "sqlite": sqlite3.sqlite_version,
              "started_at": datetime.now(timezone(timedelta(hours=8))).isoformat()}
    with (research / "python-final.log").open("w", encoding="utf-8") as stream:
        suite = unittest.defaultTestLoader.discover(str(source / "tests"))
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    report.update(tests_run=result.testsRun, failures=len(result.failures), errors=len(result.errors),
                  skipped=len(result.skipped), python_tests_passed=result.wasSuccessful())
    commands = [
        ("ruff", [sys.executable, "-m", "ruff", "check", "src", "tests", "scripts"]),
        ("mypy", [sys.executable, "-m", "mypy", "src/aha", "--cache-dir", str(task / "mypy-final-win"), "--no-incremental"]),
        ("compileall", [sys.executable, "-X", "pycache_prefix=" + str(task / "compiled-source"), "-m", "compileall", "-q", "src/aha"]),
    ]
    for name, command in commands:
        checked = subprocess.run(command, cwd=source, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True, encoding="utf-8", errors="replace")
        (research / (name + "-final.log")).write_text(checked.stdout, encoding="utf-8")
        report[name] = {"returncode": checked.returncode, "passed": checked.returncode == 0}
    report["verified"] = report["python_tests_passed"] and all(report[name]["passed"] for name, _ in commands)
    report["completed_at"] = datetime.now(timezone(timedelta(hours=8))).isoformat()
    (research / "python-final.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
