"""Confirm the delivered program remains self-contained after task cleanup.

Uses only the retained base native interpreter and stdlib verifier Client.
Launch addresses/authentication stay in memory and are never recorded.
"""

import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import zipfile
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path


def helper(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def audit_recovered_history(data, delivery, snapshots, links):
    # Normal UI startup has imported new consumption since the repair snapshot.
    # Compare the fixed historical keys rather than rejecting legitimate growth.
    with tempfile.TemporaryDirectory(prefix="aha-project-continuity-final-audit-") as temporary:
        workspace = Path(temporary)
        (workspace / "task-ownership.json").write_text(
            '{"task":"project-record-continuity","purpose":"readonly-post-sync-history-audit"}\n',
            encoding="utf-8")
        archived = workspace / "aha.sqlite3"
        with zipfile.ZipFile(delivery["backup_after"]["archive_path"]) as package:
            member = package.getinfo("aha.sqlite3")
            assert member.file_size < 256 * 1024 * 1024
            with package.open(member) as origin, archived.open("xb") as target:
                shutil.copyfileobj(origin, target, 1024 * 1024)
        expected = snapshots.facts(archived)
        assert expected["counts"] == delivery["counts_after"]
        assert expected["assigned"] == delivery["assigned_after"]
        expected_links = links.relationships(archived, snapshots.digest_rows)
        assert expected_links == delivery["relationships_after"]
        with closing(sqlite3.connect((data / "aha.sqlite3").as_uri() + "?mode=ro", uri=True)) as db:
            db.execute("ATTACH DATABASE ? AS audit", (archived.as_uri() + "?mode=ro",))
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN")
            columns = ("record_key,kind,version_id,content_hash,request_count,fresh_input_tokens,"
                       "output_tokens,cache_read_tokens,cache_creation_tokens,total_tokens,total_cost_usd,suppressed")
            selected = ",".join("current." + field for field in columns.split(","))
            fact_hash = snapshots.digest_rows(db.execute(
                "SELECT " + selected + " FROM main.usage_records current "
                "JOIN audit.usage_records original ON current.record_key=original.record_key "
                "ORDER BY current.record_key"))
            assert fact_hash == expected["fact_identity_content"]["sha256"]
            versions = snapshots.digest_rows(db.execute(
                "SELECT current.* FROM main.usage_versions current JOIN audit.usage_versions original "
                "ON current.id=original.id ORDER BY current.id"))
            assert versions == expected["versions"]["sha256"]
            projection = snapshots.digest_rows(db.execute(
                "SELECT current.record_key,current.project_id,current.assignment_origin,current.cwd "
                "FROM main.usage_records current JOIN audit.usage_records original "
                "ON current.record_key=original.record_key ORDER BY current.record_key"))
            assert projection == expected_links["projection"]
            for table, key in (("record_project_links", "record_key"),
                               ("session_project_bindings", "session_id"),
                               ("project_assignment_events", "id")):
                value = snapshots.digest_rows(db.execute(
                    f"SELECT current.* FROM main.{table} current JOIN audit.{table} original "
                    f"ON current.{key}=original.{key} ORDER BY current.{key}"))
                assert value == expected_links[table], table
            current_count = db.execute("SELECT COUNT(*) FROM usage_records").fetchone()[0]
            old_count = expected["counts"]["usage_records"]
            assert current_count >= old_count
            db.rollback()
        result = {"historical_physical_rows_verified": old_count,
                  "current_physical_rows_at_audit": current_count,
                  "new_physical_rows_since_repair": current_count - old_count,
                  "historical_facts_cost_tokens_versions_and_relationships_unchanged": True,
                  "temporary_readonly_audit_directory": str(workspace)}
    result["temporary_readonly_audit_directory_removed"] = not workspace.exists()
    assert result["temporary_readonly_audit_directory_removed"]
    return result


def main():
    research = Path(__file__).resolve().parent
    source = research.parents[3]
    sys.path.insert(0, str(source / "scripts"))
    from verify_windows_artifact import Client, digest

    delivery = json.loads((research / "delivery.json").read_text(encoding="utf-8"))
    cleanup = json.loads((research / "cleanup.json").read_text(encoding="utf-8"))
    assert delivery["verified"] and cleanup["verified"]
    assert not Path(cleanup["removed_root"]).exists()
    desktop = Path(delivery["desktop_executable"])
    data = Path(os.environ["LOCALAPPDATA"]) / "aha"
    assert data.resolve() == Path(delivery["actual_data_directory"]).resolve()
    assert digest(desktop) == delivery["executable_sha256"]
    assert digest(Path(delivery["existing_program"]["path"])) == delivery["executable_sha256"]
    for backup in (delivery["backup_before"], delivery["backup_after"]):
        assert digest(Path(backup["archive_path"])) == backup["sha256"]
    for relative, expected in delivery["gate_sha256"].items():
        assert digest(research / relative) == expected
    descriptor = json.loads((data / "runtime.json").read_text(encoding="utf-8"))
    client = Client(descriptor)
    status = client.json("GET", "/api/status")
    assert Path(status["data_directory"]).resolve() == data.resolve()
    snapshots = helper(research / "prepare-real-copy.py", "post_cleanup_snapshots")
    links = helper(research / "verify-real-associations.py", "post_cleanup_links")
    state = snapshots.facts(data / "aha.sqlite3")
    assert state["schema"] == 4 and state["assigned"] >= delivery["assigned_after"]
    for field in ("projects", "claims", "revisions", "coverage"):
        assert state[field] == delivery["immutable_fact_hashes"][field]
    audit = audit_recovered_history(data, delivery, snapshots, links)
    process = subprocess.Popen([str(desktop), "--no-browser"], cwd=desktop.parent,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    assert process.wait(timeout=45) == 0
    repeated = json.loads((data / "runtime.json").read_text(encoding="utf-8"))
    assert all(repeated[key] == descriptor[key] for key in ("pid", "run_id", "profile_id"))
    assert client.json("GET", "/api/instance")["state"] == "ready"
    report = {"verified": True, "task_temporary_root_absent": True,
              "retained_base_native_interpreter": sys.executable,
              "desktop_and_existing_program_sha256": delivery["executable_sha256"],
              "persistent_before_and_after_backups_verified": True,
              "historical_gate_reports_byte_unchanged": True,
              "default_service_ready_after_qa_environment_removed": True,
              "default_reopen_reuses_same_service_after_cleanup": True,
              "primary_historical_facts_and_recovered_links_unchanged_after_cleanup": True,
              "normal_sync_additions_observed": audit["new_physical_rows_since_repair"] > 0,
              "post_sync_historical_audit": audit,
              "current_assigned_detail_count_before_browser_open": state["assigned"],
              "physical_desktop_input": False,
              "browser_open_requested": False,
              "completed_at": datetime.now(timezone(timedelta(hours=8))).isoformat()}
    # Ordinary launch is authorized desktop delivery. This asks the existing
    # native app to show its normal browser, without exposing private URL data.
    launch = subprocess.Popen([str(desktop)], cwd=desktop.parent,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    report["browser_open_requested"] = launch.wait(timeout=45) == 0
    assert report["browser_open_requested"]
    report["browser_window_visually_verified"] = False
    report["subsequent_normal_ui_startup_may_sync_new_consumption"] = True
    (research / "final-native-state.json").write_bytes(
        (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    retained = Path(delivery["backup_after"]["archive_path"]).parent / "acceptance-records"
    (retained / "final-native-state.json").write_bytes((research / "final-native-state.json").read_bytes())
    print(json.dumps({"verified": True, "task_temporary_root_absent": True,
                      "default_service_ready": True, "browser_open_requested": True}))


if __name__ == "__main__":
    main()
