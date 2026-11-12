"""Read bounded project/session metadata and aggregate counts; never initialize Store."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from collections import Counter
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path


@contextmanager
def reader(path: Path):
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=1)) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        db.execute("PRAGMA trusted_schema=OFF")
        db.execute("BEGIN")
        try:
            yield db
        finally:
            db.rollback()


def rows(db, sql, parameters=()):
    return [dict(row) for row in db.execute(sql, parameters)]


def summary(db):
    return {
        "revisions": rows(db, "SELECT key,value FROM settings WHERE key IN "
                          "('revision','data_revision','claim_revision') ORDER BY key"),
        "facts": rows(db, "SELECT kind,assignment_origin,COUNT(*) AS physical_rows,"
                      "SUM(CAST(request_count AS INTEGER)) AS represented_count,"
                      "MIN(day) AS first_day,MAX(day) AS last_day,suppressed,availability_state "
                      "FROM usage_records GROUP BY kind,assignment_origin,suppressed,availability_state"),
        "session_status": rows(db, "SELECT status,COUNT(*) AS n,SUM(cwd IS NOT NULL) AS with_cwd "
                               "FROM sessions GROUP BY status"),
        "project_count": db.execute("SELECT COUNT(*) FROM projects").fetchone()[0],
        "override_count": db.execute("SELECT COUNT(*) FROM overrides").fetchone()[0],
        "claims_count": db.execute("SELECT COUNT(*) FROM usage_claims").fetchone()[0],
        "metadata_versions": rows(db, "SELECT json_extract(payload_json,'$.status') AS status,"
                                  "COUNT(*) AS n,COUNT(DISTINCT session_id) AS sessions "
                                  "FROM session_metadata_versions GROUP BY 1"),
    }


def recovery_preview(db):
    sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))
    from aha.projects import _contains, canonical_path

    projects = rows(db, "SELECT id,name,directories_json FROM projects ORDER BY name,id")
    rules = sorted([(len(canonical_path(d)), canonical_path(d), p["id"], p["name"])
                    for p in projects for d in json.loads(p["directories_json"])], reverse=True)
    totals = Counter()
    per_project = Counter()
    unmatched = Counter()
    metadata_times = Counter()
    for session in db.execute("SELECT id,status FROM sessions WHERE status!='matched' OR cwd IS NULL"):
        versions = rows(db, "SELECT id,payload_json,created_at FROM session_metadata_versions "
                           "WHERE session_id=? ORDER BY id", (session["id"],))
        candidates = {}
        for version in versions:
            payload = json.loads(version["payload_json"])
            if payload.get("status") == "matched" and payload.get("cwd"):
                candidates[canonical_path(payload["cwd"])] = version
            minute = datetime.fromisoformat(version["created_at"]).astimezone(
                timezone(timedelta(hours=8))).isoformat(timespec="minutes")
            metadata_times[(payload.get("status"), minute)] += 1
        totals["unknown_sessions"] += 1
        if len(candidates) != 1:
            totals["ambiguous_or_no_evidence_sessions"] += 1
            continue
        totals["unique_historical_directory_sessions"] += 1
        count = db.execute("SELECT COUNT(*) FROM usage_records WHERE session_id=? AND kind='detail'",
                           (session["id"],)).fetchone()[0]
        totals["unique_historical_directory_rows"] += count
        cwd = next(iter(candidates))
        matches = [rule for rule in rules if _contains(rule[1], cwd)]
        if matches:
            totals["existing_project_sessions"] += 1
            totals["existing_project_rows"] += count
            per_project[(matches[0][3], "sessions")] += 1
            per_project[(matches[0][3], "rows")] += count
        else:
            totals["directory_without_project_sessions"] += 1
            totals["directory_without_project_rows"] += count
            unmatched[cwd] += count
    return {"totals": dict(totals),
            "existing_project_distribution": [{"project": p["name"],
                "sessions": per_project[(p["name"], "sessions")], "rows": per_project[(p["name"], "rows")]}
                for p in projects],
            "unmatched_historical_directories": [{"cwd": cwd, "rows": n}
                                                for cwd, n in unmatched.most_common()],
            "metadata_events": [{"status": status, "created_at": at, "n": n}
                                for (status, at), n in sorted(metadata_times.items())]}


def main():
    local = Path(os.environ["LOCALAPPDATA"])
    path = local / "aha/aha.sqlite3"
    report = {"at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
              "python_sqlite": sqlite3.sqlite_version, "mode": "read-only transactions"}
    with reader(path) as db:
        report["current"] = summary(db)
        report["projects"] = rows(db, "SELECT p.name,p.directories_json,"
                                  "COUNT(r.record_key) AS physical_rows,MIN(r.day) AS first_day,"
                                  "MAX(r.day) AS last_day FROM projects p LEFT JOIN usage_records r "
                                  "ON r.project_id=p.id GROUP BY p.id ORDER BY p.name,p.id")
        report["detail_join"] = rows(db, "SELECT s.status,r.assignment_origin,COUNT(*) AS n,"
                                     "COUNT(DISTINCT r.session_id) AS session_count,MIN(r.day) AS first_day,"
                                     "MAX(r.day) AS last_day FROM usage_records r LEFT JOIN sessions s "
                                     "ON s.id=r.session_id WHERE r.kind='detail' "
                                     "GROUP BY s.status,r.assignment_origin")
        report["unassigned_known_directories"] = rows(db, "SELECT r.cwd,COUNT(*) AS n,"
            "COUNT(DISTINCT r.session_id) AS sessions,MIN(r.day) AS first_day,MAX(r.day) AS last_day "
            "FROM usage_records r WHERE r.project_id='' AND r.cwd IS NOT NULL "
            "GROUP BY r.cwd ORDER BY n DESC LIMIT 30")
        report["unknown_sessions_with_old_matched_version"] = rows(db,
            "SELECT s.status,COUNT(DISTINCT s.id) AS n FROM sessions s "
            "JOIN session_metadata_versions v ON v.session_id=s.id "
            "WHERE (s.status!='matched' OR s.cwd IS NULL) "
            "AND json_extract(v.payload_json,'$.status')='matched' "
            "AND json_extract(v.payload_json,'$.cwd') IS NOT NULL GROUP BY s.status")
        report["open_cases"] = rows(db, "SELECT type,state,COUNT(*) AS n "
                                    "FROM reconciliation_cases GROUP BY type,state")
        report["unassigned_by_day"] = rows(db, "SELECT day,COUNT(*) AS n FROM usage_records "
                                            "WHERE kind='detail' AND project_id='' "
                                            "GROUP BY day ORDER BY day")
        report["unknown_session_usage"] = rows(db,
            "SELECT COUNT(*) AS sessions,MIN(n) AS min_rows,MAX(n) AS max_rows,SUM(n) AS total_rows "
            "FROM (SELECT r.session_id,COUNT(*) AS n FROM usage_records r LEFT JOIN sessions s "
            "ON s.id=r.session_id WHERE r.kind='detail' AND (s.status!='matched' OR s.id IS NULL) "
            "GROUP BY r.session_id)")
        report["recovery_preview"] = recovery_preview(db)
        report["retained_snapshots"] = []
        for candidate in sorted((local / "aha-recovery").glob("device-continuity-20261112-*/aha.sqlite3"))[:4]:
            with reader(candidate) as old:
                saved = summary(old)
                old_facts = {r["record_key"]: tuple(r)[1:] for r in old.execute(
                    "SELECT record_key,content_hash,project_id,assignment_origin,cwd FROM usage_records")}
                now_facts = {r["record_key"]: tuple(r)[1:] for r in db.execute(
                    "SELECT record_key,content_hash,project_id,assignment_origin,cwd FROM usage_records")}
                saved["old_fact_missing_count"] = sum(k not in now_facts for k in old_facts)
                saved["old_fact_content_changed_count"] = sum(
                    k in now_facts and now_facts[k][0] != v[0] for k, v in old_facts.items())
                saved["old_fact_assignment_changed_count"] = sum(
                    k in now_facts and now_facts[k][1:] != v[1:] for k, v in old_facts.items())
                report["retained_snapshots"].append(saved)
        report["current_after"] = summary(db)
    with reader(path) as db:
        report["independent_after"] = summary(db)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
