"""Reproduce only the isolated cloud artifact verification with safe stack metadata."""

import json
import os
import sys
import traceback
from pathlib import Path
from uuid import uuid4


def main():
    source = Path(__file__).resolve().parents[4]
    research = Path(__file__).resolve().parent
    task = Path(os.environ["AHA_QA_ROOT"])
    assert task.name == "aha-release-v050-20261112"
    assert json.loads((task / "task-ownership.json").read_text())["purpose"] == "release-v050"
    sys.path.insert(0, str(source / "scripts"))
    from verify_windows_artifact import verify

    case = task / ("verify-cloud-onefile-observed-" + uuid4().hex[:8])
    try:
        result = verify((task / "cloud-v050-assets/aha-0.5.0-windows-x64.exe").resolve(strict=True),
                        source.resolve(strict=True), case.resolve(), with_tray=False)
        (research / "release-cloud-onefile-verification.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        report = {"verified": True, "case": str(case), "result_report": "release-cloud-onefile-verification.json"}
    except Exception as error:
        report = {"verified": False, "case": str(case), "error_type": type(error).__name__,
                  "errno": getattr(error, "errno", None), "winerror": getattr(error, "winerror", None),
                  "stack": [{"file": Path(frame.filename).name, "line": frame.lineno, "function": frame.name}
                            for frame in traceback.extract_tb(error.__traceback__)]}
    (research / "release-cloud-verifier-observation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
