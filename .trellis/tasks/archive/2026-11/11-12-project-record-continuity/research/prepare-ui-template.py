"""Keep a reusable synthetic schema3 archive for source and final artifact UI checks."""

import json
import os
import sys
from pathlib import Path


def main():
    task = Path(os.environ["AHA_QA_ROOT"])
    sys.path.insert(0, str(task / "baseline-source/src"))
    from aha.backup import create_backup
    fixture = json.loads((task / "association-fixture-info.json").read_text(encoding="utf-8"))
    destination = task / "association-ui-schema3.aha-backup"
    assert not destination.exists()
    result = create_backup(Path(fixture["data_directory"]), destination)
    fixture["archive"] = str(destination)
    fixture["archive_sha256"] = result["sha256"]
    (task / "association-fixture-info.json").write_text(json.dumps(fixture, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"schema": result["store_schema_version"], "synthetic_archive_size": result["size"], "sha256": result["sha256"]}))


if __name__ == "__main__":
    main()
