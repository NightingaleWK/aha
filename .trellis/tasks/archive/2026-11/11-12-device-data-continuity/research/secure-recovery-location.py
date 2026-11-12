"""Keep a verified pre-change archive outside packaged-app virtual AppData."""

import hashlib
import json
import shutil
from pathlib import Path


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def copy_verified(source, target, expected):
    assert sha(source) == expected, "Input changed"
    if target.exists():
        assert sha(target) == expected, "Unknown existing destination"
    else:
        with source.open("rb") as first, target.open("xb") as second:
            shutil.copyfileobj(first, second, length=1024 * 1024)
        assert sha(target) == expected, "Delivery copy differs"


source_root = Path(__file__).resolve().parents[4]
research = source_root / ".trellis/tasks/11-12-device-data-continuity/research"
verified = json.loads((research / "real-copy-verification.json").read_text(encoding="utf-8"))
assert verified["verified"] and verified["original_ledger_unchanged"]
root = Path("D:/aha-backups/20261112-device-continuity")
marker = root / "recovery-ownership.json"
if root.exists():
    assert marker.is_file() and json.loads(marker.read_text())["task"] == "device-data-continuity"
else:
    root.mkdir(parents=True, exist_ok=False)
    marker.write_text(json.dumps({"task": "device-data-continuity", "purpose": "persistent recovery; never temporary cleanup"}), encoding="utf-8")
archive = root / "aha-before-continuity-20261112.aha-backup"
old_exe = root / "aha-0.4.1-before-continuity.exe"
copy_verified(Path(verified["backup"]["archive_path"]), archive, verified["backup"]["sha256"])
copy_verified(Path("D:/Program Files/aha.exe"), old_exe,
              "0c25c25da9df56f7b82e7fe4cbce9f20613e1e82172c2ac9b620c2b77b0e8f58")
result = {"archive": str(archive.resolve()), "archive_sha256": sha(archive),
           "archive_bytes": archive.stat().st_size, "old_executable": str(old_exe.resolve()),
           "old_executable_sha256": sha(old_exe), "permanent": True}
(research / "persistent-recovery.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(result, ensure_ascii=False, indent=2))
