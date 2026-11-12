"""Native Windows read-only aggregate diagnosis; never imports or opens Store."""

import json
import os
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def reader(path):
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=3)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA trusted_schema=OFF")
    connection.execute("BEGIN")
    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()


def rows(connection, sql):
    return [dict(row) for row in connection.execute(sql)]


def main():
    app_dir = Path(os.environ["LOCALAPPDATA"]) / "aha"
    ccs_path = Path.home() / ".cc-switch" / "cc-switch.db"
    result = {"python": sys.version.split()[0], "sqlite": sqlite3.sqlite_version}
    with reader(app_dir / "aha.sqlite3") as c:
        result["aha_schema"] = c.execute("PRAGMA user_version").fetchone()[0]
        result["counts"] = {
            name: c.execute("SELECT count(*) FROM " + name).fetchone()[0]
            for name in ("usage_records", "usage_versions", "projects", "overrides", "sessions",
                         "source_profiles", "source_epochs", "reconciliation_events", "batches",
                         "batch_revisions", "usage_claims", "record_aliases")
            if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
        }
        result["facts"] = rows(c, "SELECT kind,availability_state,suppressed,count(*) AS rows,"
                                "min(day) AS first_day,max(day) AS last_day FROM usage_records "
                                "GROUP BY kind,availability_state,suppressed")
        result["recent_days"] = rows(c, "SELECT day,kind,count(*) AS rows FROM usage_records "
                                      "WHERE day>='2026-11-08' GROUP BY day,kind ORDER BY day")
        result["sessions"] = rows(c, "SELECT status,cwd IS NOT NULL AS has_cwd,count(*) AS rows "
                                   "FROM sessions GROUP BY status,cwd IS NOT NULL")
        result["source_profiles"] = []
        for row in c.execute("SELECT id,kind,location,trust,created_at,last_run_id FROM source_profiles"):
            item = dict(row)
            location = item.pop("location")
            item["matches_current_ccs_path"] = bool(location and os.path.normcase(location) ==
                                                    os.path.normcase(str(ccs_path)))
            item["path_style"] = "windows" if location and ":" in location else "other"
            result["source_profiles"].append(item)
        result["runs"] = []
        for row in c.execute("SELECT id,source_id,state,trigger,started_at,completed_at,error_code,"
                             "result_json FROM sync_runs ORDER BY rowid DESC LIMIT 18"):
            item = dict(row)
            payload = json.loads(item.pop("result_json"))
            item["result"] = {key: payload[key] for key in (
                "observed", "new_count", "revised_count", "unchanged_count", "pending_count",
                "source_schema_version", "data_revision") if key in payload}
            result["runs"].append(item)
        result["cases"] = []
        for row in c.execute("SELECT id,type,state,generation,source_id,info_json FROM "
                             "reconciliation_cases ORDER BY rowid DESC LIMIT 15"):
            item = dict(row)
            info = json.loads(item.pop("info_json"))
            item["info"] = {key: info[key] for key in (
                "observed", "previous", "rollup_request_count_regressed", "date", "model")
                            if key in info}
            result["cases"].append(item)
        result["events"] = rows(c, "SELECT e.choice,e.created_at,c.type,c.state,"
                                 "length(e.reason) AS reason_length FROM reconciliation_events e "
                                 "JOIN reconciliation_cases c ON c.id=e.case_id ORDER BY e.id DESC LIMIT 15")
        result["settings_keys"] = [row[0] for row in c.execute("SELECT key FROM settings ORDER BY key")]
    with reader(ccs_path) as c:
        result["ccs_schema"] = c.execute("PRAGMA user_version").fetchone()[0]
        result["ccs_tables"] = {
            name: rows(c, "PRAGMA table_info(" + name + ")")
            for name in ("proxy_request_logs", "usage_daily_rollups", "model_pricing")
        }
        result["ccs_details"] = rows(c, "SELECT data_source,input_token_semantics,count(*) AS rows,"
                                     "min(created_at) AS first_time,max(created_at) AS last_time "
                                     "FROM proxy_request_logs WHERE app_type='codex' "
                                     "GROUP BY data_source,input_token_semantics")
        result["ccs_detail_days"] = rows(c, "SELECT date(created_at,'unixepoch','+8 hours') AS day,"
                                         "count(*) AS rows FROM proxy_request_logs "
                                         "WHERE app_type='codex' AND data_source='codex_session' "
                                         "GROUP BY day ORDER BY day")
        result["ccs_rollups"] = rows(c, "SELECT count(*) AS rows,min(date) AS first_day,"
                                     "max(date) AS last_day FROM usage_daily_rollups "
                                     "WHERE app_type='codex' AND provider_id='_codex_session'")
    result["aha_files"] = {name: {"file_count": sum(1 for p in (app_dir / name).rglob('*') if p.is_file()),
                                     "bytes": sum(p.stat().st_size for p in (app_dir / name).rglob('*') if p.is_file())}
                             for name in ("packages", "objects", "backups")}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
