"""Verify approved recovery on the independent real-size copy; never write the original ledger."""

import importlib.util
import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4


def helpers(path):
    spec = importlib.util.spec_from_file_location("association_snapshot_helpers", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def relationships(path, digest_rows):
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        result = {"projection": digest_rows(db.execute(
            "SELECT record_key,project_id,assignment_origin,cwd FROM usage_records ORDER BY record_key"))}
        for table, order in (("record_project_links", "record_key"),
                             ("session_project_bindings", "session_id"),
                             ("project_assignment_events", "id")):
            result[table] = digest_rows(db.execute(f"SELECT * FROM {table} ORDER BY {order}"))
        db.rollback()
        return result


def main():
    from aha.backup import create_backup, restore_backup
    from aha.storage import Store

    source = Path(__file__).resolve().parents[4]
    research = source / ".trellis/tasks/11-12-project-record-continuity/research"
    task = Path(os.environ["AHA_QA_ROOT"])
    baseline = json.loads((research / "real-copy-baseline.json").read_text(encoding="utf-8"))
    snapshot = helpers(research / "prepare-real-copy.py")
    data = Path(baseline["destination"])
    original = task.parent.parent / "aha/aha.sqlite3"
    assert snapshot.facts(original) == baseline["snapshot"]
    store = None
    report = {"verified": False, "original_written": False, "data_directory": str(data)}
    try:
        store = Store(data)
        migrated = snapshot.facts(data / "aha.sqlite3")
        assert migrated["schema"] == 4
        for key in ("fact_identity_content", "versions", "projects", "claims", "revisions", "coverage", "counts", "assigned"):
            assert migrated[key] == baseline["snapshot"][key], key
        report["migration_preserves_all_facts_current_assignments_claims_and_materials"] = True
        rollback = sorted((data / "backups").glob("*.aha-backup"))
        assert rollback
        report["migration_rollback_archive_count"] = len(rollback)
        before = store.association_status()
        preview = store.preview_associations({"action": "recover", "filters": {"project_id": "unassigned"}})
        report["preview"] = {k: v for k, v in preview["summary"].items() if k != "total_cost_usd"}
        assert preview["summary"]["recovered_sessions"] == 347
        assert preview["summary"]["selected_detail_count"] == 38978
        assert preview["summary"]["changed_count"] == 37165
        assert preview["summary"]["directory_only_sessions"] == 50
        token = "real-copy-" + uuid4().hex
        reason = "隔离真实资料副本验收：按 aha 留存唯一有效历史目录恢复关联，不依赖旧电脑日志。"
        applied = store.apply_associations(preview["preview_id"], reason, token)
        assert applied == store.apply_associations(preview["preview_id"], reason, token)
        after = store.association_status()
        report["counts_before"] = {k: before["summary"][k] for k in (
            "detail_count", "assigned_detail_count", "unassigned_detail_count", "unassigned_rollup_count")}
        report["counts_after"] = {k: after["summary"][k] for k in (
            "detail_count", "assigned_detail_count", "unassigned_detail_count", "unassigned_rollup_count")}
        assert after["summary"]["assigned_detail_count"] == 38665
        assert after["summary"]["unassigned_detail_count"] == 3438
        with store.read_connection() as reader:
            report["matched_sessions_after"] = reader.execute("SELECT COUNT(*) FROM sessions WHERE status='matched'").fetchone()[0]
            assert report["matched_sessions_after"] == 411
            report["durable_links"] = reader.execute("SELECT COUNT(*) FROM record_project_links").fetchone()[0]
        history = store.analyze("2026-06-17", "2026-11-12", "all", availability_mode="all")
        partitions = [store.analyze("2026-06-17", "2026-11-12", p["id"], availability_mode="all")["summary"]
                      for p in store.config()["projects"]]
        partitions.append(store.analyze("2026-06-17", "2026-11-12", "unassigned", availability_mode="all")["summary"])
        summary = history["summary"]
        assert summary["record_count"] == 77603
        assert sum(s["record_count"] for s in partitions) == summary["record_count"]
        assert sum((Decimal(s["total_cost_usd"]) for s in partitions), Decimal(0)) == Decimal(summary["total_cost_usd"])
        for field in ("fresh_input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens", "total_tokens"):
            assert sum(s[field] for s in partitions) == summary[field], field
        report["all_projects_plus_unassigned_conserve_records_amount_and_tokens"] = True
        report["represented_record_count"] = summary["record_count"]
        report["project_detail_counts"] = [p["detail_count"] for p in after["projects"]]
        before_refresh = snapshot.facts(data / "aha.sqlite3")
        links_before_refresh = relationships(data / "aha.sqlite3", snapshot.digest_rows)
        store.refresh_metadata([task / "nonexistent-old-computer-sessions"])
        assert snapshot.facts(data / "aha.sqlite3") == before_refresh
        assert relationships(data / "aha.sqlite3", snapshot.digest_rows) == links_before_refresh
        report["missing_old_logs_do_not_remove_recovered_links"] = True
        final = snapshot.facts(data / "aha.sqlite3")
        for key in ("fact_identity_content", "versions", "projects", "claims", "revisions", "coverage", "counts"):
            assert final[key] == baseline["snapshot"][key], key
        archive = task / "real-copy-after-associations.aha-backup"
        backup = create_backup(data, archive)
        restored = task / "real-copy-after-associations-restored"
        restore_backup(archive, restored)
        assert snapshot.facts(restored / "aha.sqlite3") == final
        assert relationships(restored / "aha.sqlite3", snapshot.digest_rows) == links_before_refresh
        restored_store = Store(restored)
        try:
            assert restored_store.association_status()["summary"] == after["summary"]
        finally:
            restored_store.close()
        report["schema4_full_backup_and_independent_restore_keep_recovered_links"] = True
        report["schema4_archive_sha256"] = backup["sha256"]
        assert snapshot.facts(original) == baseline["snapshot"]
        report["original_logically_unchanged"] = True
        report["verified"] = True
        report["completed_at"] = datetime.now(timezone(timedelta(hours=8))).isoformat()
    finally:
        if store is not None:
            store.close()
        (research / "real-copy-association-verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in {"data_directory", "preview"}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
