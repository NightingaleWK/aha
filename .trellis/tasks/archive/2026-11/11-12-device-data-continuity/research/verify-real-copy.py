"""Validate recovery and continuation on an independent copy of the user's ledger."""

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from aha import backup
from aha.storage import Store


def read(path):
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    connection.execute("PRAGMA query_only=ON")
    connection.execute("BEGIN")
    return connection


def digest_rows(rows):
    digest = hashlib.sha256()
    for row in rows:
        digest.update(json.dumps(list(row), ensure_ascii=False, separators=(",", ":")).encode())
        digest.update(b"\n")
    return digest.hexdigest()


def summary(path):
    connection = read(path)
    try:
        tables = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        result = {}
        for table in tables:
            columns = [row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')]
            selected = ",".join('"' + name + '"' for name in columns)
            result[table] = {"count": connection.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0],
                             "sha256": digest_rows(connection.execute(
                                 f'SELECT {selected} FROM "{table}" ORDER BY {selected}'))}
        return result
    finally:
        connection.rollback()
        connection.close()


def old_facts(path):
    connection = read(path)
    try:
        # Availability/pricing status can legitimately change as new evidence arrives.
        columns = [row[1] for row in connection.execute('PRAGMA table_info(usage_records)')
                   if row[1] not in {"availability_state", "usage_reason", "pricing_status"}]
        selected = ",".join(columns)
        return columns, {row[0]: list(row) for row in connection.execute(
            "SELECT " + selected + " FROM usage_records ORDER BY record_key")}
    finally:
        connection.rollback()
        connection.close()


def main():
    source_root = Path(__file__).resolve().parents[4]
    local = Path(os.environ["LOCALAPPDATA"])
    data = local / "aha"
    ccs = Path.home() / ".cc-switch" / "cc-switch.db"
    owner = local / "Temp" / "aha-device-continuity-20261112"
    assert json.loads((owner / "task-ownership.json").read_text())["task"] == "device-data-continuity"
    stamp = datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d-%H%M%S")
    archive = local / "aha-recovery" / ("aha-before-continuity-" + stamp + ".aha-backup")
    restored = owner / ("real-copy-" + uuid4().hex[:10])
    original = summary(data / "aha.sqlite3")
    _, baseline = old_facts(data / "aha.sqlite3")
    report = {"verified": False, "original_counts": {k: v["count"] for k, v in original.items()}}
    report["backup"] = backup.create_backup(data, archive)
    report["restore"] = backup.restore_backup(archive, restored)
    assert summary(restored / "aha.sqlite3") == original, "Restored logical snapshot changed"
    report["all_tables_identical_after_restore"] = True
    store = Store(restored)
    try:
        history = store.analyze("2026-06-17", "2026-11-12")
        report["historical_summary"] = {k: history["summary"].get(k) for k in
                                         ("record_count", "detail_count", "rollup_record_count")}
        assert history["summary"]["record_count"] == 74846
        with store.read_connection() as c:
            projects_before = digest_rows(c.execute("SELECT * FROM projects ORDER BY id"))
            sessions_before = digest_rows(c.execute("SELECT id,cwd,status FROM sessions ORDER BY id"))
        store.refresh_metadata([owner / "nonexistent-old-computer-sessions"])
        with store.read_connection() as c:
            assert projects_before == digest_rows(c.execute("SELECT * FROM projects ORDER BY id"))
            assert sessions_before == digest_rows(c.execute("SELECT id,cwd,status FROM sessions ORDER BY id"))
        report["missing_old_sessions_preserves_all_directories_and_projects"] = True
        # An audit-only installation identity is scoped to this independent restored copy.
        with patch("aha.source_bindings.installation_id", return_value="a" * 32):
            assert store.source_binding_status(ccs)["required"]
            store.bind_source(ccs, "隔离副本验收：旧电脑已格式化，仅新电脑接续，保留全部现存历史。")
            result = store.sync_sqlite(ccs, [Path.home() / ".codex"])
            report["continuation"] = {k: result.get(k) for k in
                                       ("state", "new_count", "revised_count", "unchanged_count",
                                        "pending_count", "source_schema_version", "observed", "timings")}
            _, current = old_facts(restored / "aha.sqlite3")
            assert all(current.get(key) == row for key, row in baseline.items()), "Old fact changed"
            report["all_original_facts_and_project_assignments_preserved"] = True
            again = store.sync_sqlite(ccs, [Path.home() / ".codex"])
            report["repeat_sync"] = {k: again.get(k) for k in
                                      ("state", "new_count", "revised_count", "pending_count")}
            report["ledger"] = {k: store.ledger_status().get(k) for k in ("counts", "coverage")}
            report["open_case_types"] = sorted({case["type"] for case in store.list_reconciliations()})
    finally:
        store.close()
    assert summary(data / "aha.sqlite3") == original, "Original ledger changed during copy validation"
    report["original_ledger_unchanged"] = True
    report["verified"] = True
    report["completed_at"] = datetime.now(timezone(timedelta(hours=8))).isoformat()
    output = source_root / ".trellis/tasks/11-12-device-data-continuity/research/real-copy-verification.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
