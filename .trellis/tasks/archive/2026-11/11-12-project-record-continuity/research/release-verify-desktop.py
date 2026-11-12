"""Verify the real delivered file using isolated synthetic data only."""

import json
import os
import sys
import traceback
from pathlib import Path


def main():
    source = Path(__file__).resolve().parents[4]
    research = Path(__file__).resolve().parent
    task = Path(os.environ["AHA_QA_ROOT"])
    assert task.name == "aha-release-v050-20261112"
    sys.path.insert(0, str(source / "scripts"))
    from verify_windows_artifact import digest, verify

    delivery = json.loads((research / "release-desktop-delivery.json").read_text(encoding="utf-8"))
    assert delivery["verified"]
    desktop = Path(delivery["delivery"][0]["path"])
    assert digest(desktop) == delivery["executable_sha256"]
    try:
        result = verify(desktop, source, task / "verify-desktop-v050", with_tray=False)
        result["source_sha"] = delivery["source_sha"]
        result["runtime_sha256"] = delivery["runtime_sha256"]
        result["fingerprints"] = delivery["fingerprints"]
        (research / "release-desktop-verification.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"verified": True, "executable_sha256": result["executable_sha256"]}))
        return 0
    except Exception as error:
        failure = {"verified": False, "error_type": type(error).__name__,
                   "errno": getattr(error, "errno", None), "winerror": getattr(error, "winerror", None),
                   "stack": [{"file": Path(frame.filename).name, "line": frame.lineno, "function": frame.name}
                             for frame in traceback.extract_tb(error.__traceback__)]}
        (research / "release-desktop-verification.json").write_text(
            json.dumps(failure, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(failure))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
