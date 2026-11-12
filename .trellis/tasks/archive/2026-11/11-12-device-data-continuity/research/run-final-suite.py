"""Persist the final isolated native unittest result without truncating its log."""

import json
import sqlite3
import sys
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


def main() -> None:
    started = time.monotonic()
    output = Path(__file__).resolve().parent
    source = Path(__file__).resolve().parents[4]
    # A file entry point starts with research/ on sys.path; match `python -m unittest`
    # so tests can import the repository's scripts namespace in spawned processes.
    sys.path.insert(0, str(source))
    pattern = sys.argv[1] if len(sys.argv) > 1 else "test*.py"
    suffix = "" if pattern == "test*.py" else "-" + Path(pattern).stem
    suite = unittest.defaultTestLoader.discover(str(source / "tests"), pattern=pattern)
    print(f"Collected {suite.countTestCases()} tests using {sys.version.split()[0]}", flush=True)
    with (output / ("python-test" + suffix + "-log.txt")).open("w", encoding="utf-8") as stream:
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    report = {
        "verified": result.wasSuccessful(),
        "tests_run": result.testsRun,
        "failures": [{"test": str(test), "traceback": trace} for test, trace in result.failures],
        "errors": [{"test": str(test), "traceback": trace} for test, trace in result.errors],
        "skipped": [{"test": str(test), "reason": reason} for test, reason in result.skipped],
        "python": sys.version,
        "sqlite": sqlite3.sqlite_version,
        "duration_seconds": round(time.monotonic() - started, 3),
        "completed_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
    }
    (output / ("python-test" + suffix + "-result.json")).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["verified"] else 1)


if __name__ == "__main__":
    main()
