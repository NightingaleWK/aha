"""Create a private, consistent recovery snapshot of the sole live aha ledger."""

import hashlib
import json
import os
import shutil
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from uuid import uuid4


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    local = Path(os.environ["LOCALAPPDATA"])
    source = local / "aha"
    stamp = datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d-%H%M%S")
    target = local / "aha-recovery" / ("device-continuity-" + stamp + "-" + uuid4().hex[:8])
    target.mkdir(parents=True, exist_ok=False)
    manifest = {"purpose": "pre-change sole-ledger recovery snapshot", "complete": False,
                "created_at": datetime.now(timezone(timedelta(hours=8))).isoformat(), "files": []}
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    reader = sqlite3.connect((source / "aha.sqlite3").as_uri() + "?mode=ro", uri=True, timeout=3)
    reader.execute("PRAGMA query_only=ON")
    reader.execute("PRAGMA trusted_schema=OFF")
    reader.execute("BEGIN")
    destination = sqlite3.connect(target / "aha.sqlite3")
    try:
        counts = dict(reader.execute("SELECT kind,count(*) FROM usage_records GROUP BY kind"))
        reader.backup(destination, pages=1024)
        check = destination.execute("PRAGMA quick_check").fetchall()
        assert check == [("ok",)], check
        assert not destination.execute("PRAGMA foreign_key_check").fetchall()
        assert dict(destination.execute("SELECT kind,count(*) FROM usage_records GROUP BY kind")) == counts
        references = list(destination.execute("SELECT zip_path,zip_hash FROM revisions"))
    finally:
        destination.close()
        reader.rollback()
        reader.close()
    for name in ("objects", "packages", "backups"):
        original = source / name
        (target / name).mkdir()
        for entry in original.rglob("*"):
            if entry.is_symlink():
                raise RuntimeError("Unexpected symlink; incomplete snapshot retained")
            relative = entry.relative_to(source)
            output = target / relative
            if entry.is_dir():
                output.mkdir(exist_ok=True)
            elif entry.is_file():
                output.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(entry, output)
                assert sha(entry) == sha(output)
    for relative, expected in references:
        original = Path(relative)
        assert len(original.parts) == 2 and original.parts[0] == "packages"
        assert sha(target / original) == expected
    for entry in sorted(target.rglob("*")):
        if entry.is_file() and entry.name != "manifest.json":
            manifest["files"].append({"path": entry.relative_to(target).as_posix(),
                                       "size": entry.stat().st_size, "sha256": sha(entry)})
    manifest.update(complete=True, schema_version=3, counts=counts,
                    quick_check="ok", foreign_key_violations=0, revision_packages=len(references))
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"path": str(target), "manifest": manifest}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
