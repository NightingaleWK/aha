"""Restore the protected schema3 archive with the committed schema3 implementation."""

import hashlib
import json
import os
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path


def digest_rows(rows):
    checksum = hashlib.sha256()
    for row in rows:
        checksum.update(json.dumps(list(row), ensure_ascii=False, separators=(",", ":")).encode())
        checksum.update(b"\n")
    return checksum.hexdigest()


def facts(path):
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("PRAGMA trusted_schema=OFF")
        db.execute("BEGIN")
        result = {"schema": db.execute("PRAGMA user_version").fetchone()[0],
                  "business_revisions": dict(db.execute("SELECT key,value FROM settings WHERE key IN "
                                                        "('revision','data_revision','claim_revision')"))}
        projections = {
            "fact_identity_content": "SELECT record_key,kind,version_id,content_hash,request_count,"
            "fresh_input_tokens,output_tokens,cache_read_tokens,cache_creation_tokens,total_tokens,"
            "total_cost_usd,suppressed FROM usage_records ORDER BY record_key",
            "versions": "SELECT * FROM usage_versions ORDER BY id",
            "projects": "SELECT * FROM projects ORDER BY id",
            "claims": "SELECT * FROM usage_claims ORDER BY record_key",
            "revisions": "SELECT * FROM revisions ORDER BY batch_id,version",
            "coverage": "SELECT * FROM coverage_groups ORDER BY id",
        }
        for name, sql in projections.items():
            result[name] = {"sha256": digest_rows(db.execute(sql))}
        result["counts"] = {table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                            for table in ("usage_records", "usage_versions", "projects", "sessions", "usage_claims", "revisions")}
        result["assigned"] = db.execute("SELECT COUNT(*) FROM usage_records WHERE project_id!=''").fetchone()[0]
        db.rollback()
        return result


def main():
    source = Path(__file__).resolve().parents[4]
    research = source / ".trellis/tasks/11-12-project-record-continuity/research"
    task = Path(os.environ["LOCALAPPDATA"]) / "Temp/aha-project-record-continuity-20261112"
    sys.path.insert(0, str(task / "baseline-source/src"))
    from aha.backup import restore_backup
    protection = json.loads((research / "protection.json").read_text(encoding="utf-8"))
    target = task / "real-schema3-copy"
    assert not target.exists()
    result = restore_backup(Path(protection["archive"]), target)
    snapshot = facts(target / "aha.sqlite3")
    original = facts(Path(os.environ["LOCALAPPDATA"]) / "aha/aha.sqlite3")
    assert snapshot == original, "Protected source and restored snapshot differ"
    report = {"verified": True, "at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
              "destination": str(target), "archive_sha256": protection["archive_sha256"],
              "snapshot": snapshot, "source_logically_equal": True,
              "source_modified": False, "restore_format_version": result["format_version"]}
    (research / "real-copy-baseline.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"verified": True, "schema": snapshot["schema"], "counts": snapshot["counts"],
                      "assigned": snapshot["assigned"], "business_revisions": snapshot["business_revisions"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
