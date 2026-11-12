"""Protect the real schema3 ledger using the unchanged committed backup implementation."""

import argparse
import ctypes
import hashlib
import io
import json
import os
import shutil
import sqlite3
import sys
import tarfile
import zipfile
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def inspect(path):
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("PRAGMA trusted_schema=OFF")
        db.execute("BEGIN")
        result = {"schema": db.execute("PRAGMA user_version").fetchone()[0],
                  "business_revisions": dict(db.execute("SELECT key,value FROM settings WHERE key IN "
                                               "('revision','data_revision','claim_revision')"))}
        for table in ("usage_records", "usage_versions", "projects", "sessions", "overrides", "usage_claims", "revisions"):
            result[table] = db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        result["assignments"] = [list(r) for r in db.execute(
            "SELECT kind,assignment_origin,COUNT(*) FROM usage_records GROUP BY 1,2 ORDER BY 1,2")]
        db.rollback()
        return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-ref", required=True)
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[4]
    task = Path(os.environ["LOCALAPPDATA"]) / "Temp/aha-project-record-continuity-20261112"
    assert json.loads((task / "task-ownership.json").read_text())["task"] == "project-record-continuity"
    baseline = task / "baseline-source"
    assert not baseline.exists()
    blob = sys.stdin.buffer.read(4 * 1024 * 1024 + 1)
    assert len(blob) <= 4 * 1024 * 1024
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:") as archive:
        for member in archive.getmembers():
            relative = Path(member.name)
            assert not relative.is_absolute() and ".." not in relative.parts
            if relative.parts == ("src",) and member.isdir():
                continue
            assert relative.parts[:2] == ("src", "aha") and not member.issym() and not member.islnk()
            target = baseline / relative
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                assert target.suffix in {".py", ".js", ".css", ".html", ".svg", ".ico"}
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as stream, target.open("xb") as output:
                    shutil.copyfileobj(stream, output)
    sys.path.insert(0, str(baseline / "src"))
    from aha.backup import create_backup

    data = Path(os.environ["LOCALAPPDATA"]) / "aha"
    before = inspect(data / "aha.sqlite3")
    assert before["schema"] == 3
    stamp = datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d-%H%M%S")
    recovery = Path("D:/aha-backups") / ("project-record-continuity-" + stamp + "-" + uuid4().hex[:6])
    recovery.mkdir(parents=True, exist_ok=False)
    output = recovery / "aha-before-project-associations.aha-backup"
    result = create_backup(data, output)
    buffer = ctypes.create_unicode_buffer(32768)
    assert ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buffer) == 0
    desktop = Path(buffer.value) / "aha.exe"
    expected = "5f34fe26f9efda64c46aed32a8eacb90af4af9c54426650f4b1f48fa5fcef888"
    assert desktop.is_file() and digest(desktop) == expected
    shutil.copy2(desktop, recovery / "aha-before-project-associations.exe")
    with zipfile.ZipFile(output) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["store_schema_version"] == 3
    after = inspect(data / "aha.sqlite3")
    report = {"protected": True, "at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
              "backup_implementation_source": args.source_ref, "baseline_tar_sha256": hashlib.sha256(blob).hexdigest(),
              "archive": str(output), "archive_sha256": digest(output), "archive_size": output.stat().st_size,
              "database": next(f for f in manifest["files"] if f["path"] == "aha.sqlite3"),
              "old_executable": str(recovery / "aha-before-project-associations.exe"),
              "old_executable_sha256": expected, "before": before, "after": after,
              "independent_read_summary_unchanged": before == after}
    assert result["sha256"] == report["archive_sha256"]
    (recovery / "protection.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (source / ".trellis/tasks/11-12-project-record-continuity/research/protection.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("protected", "archive", "archive_size", "archive_sha256", "before", "independent_read_summary_unchanged")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
