"""Independently construct schema3, then verify protected and lossless association upgrades."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from test_storage_helpers import detail

from aha import backup, batches, ledger, migrations
from aha.decimal_sql import register
from aha.domain import AppError, canonical_bytes, content_hash, record_key, row_fingerprint
from aha.storage import Store


def legacy_fixture(root: Path, *, missing: bool = False) -> dict:
    root.mkdir()
    with closing(sqlite3.connect(root / "aha.sqlite3")) as connection:
        connection.row_factory = sqlite3.Row
        register(connection)
        connection.executescript(migrations.SCHEMA_V3)
        migrations.initialize_monthly(connection)
        migrations.initialize_source_observations(connection)
        migrations.initialize_query_indexes(connection)
        batches.initialize_schema(connection)
        connection.execute("PRAGMA user_version=3")
        now = "2026-10-28T00:00:00+00:00"
        connection.execute(
            "INSERT INTO projects VALUES('legacy-project','旧项目','',?)",
            (json.dumps(["/old/repo"]),),
        )
        connection.execute(
            "INSERT INTO source_profiles VALUES('legacy','sql','合成来源',NULL,?,?,NULL)",
            ("preserved", now),
        )
        row = detail()
        connection.execute(
            "INSERT INTO usage_versions(record_key,content_hash,payload_json,created_at,source_id) "
            "VALUES(?,?,?,?,'legacy')",
            (record_key(row), row_fingerprint(row), canonical_bytes(row).decode(), now),
        )
        ledger.set_current(connection, 1)
        known = {"cwd": "/old/repo", "status": "matched", "parent_id": None}
        absent = {"cwd": None, "status": "missing", "parent_id": None}
        current = absent if missing else known
        connection.execute(
            "INSERT INTO sessions(id,cwd,status,parent_id,content_hash) VALUES(?,?,?,?,?)",
            ("s1", current["cwd"], current["status"], None, content_hash(current)),
        )
        connection.execute(
            "INSERT INTO session_metadata_versions("
            "session_id,content_hash,payload_json,created_at) "
            "VALUES('s1',?,?,?)",
            (content_hash(known), canonical_bytes(known).decode(), now),
        )
        if missing:
            connection.execute(
                "INSERT INTO session_metadata_versions("
                "session_id,content_hash,payload_json,created_at) "
                "VALUES('s1',?,?,?)",
                (content_hash(absent), canonical_bytes(absent).decode(), now),
            )
        else:
            connection.execute(
                "UPDATE usage_records SET project_id='legacy-project',"
                "assignment_origin='directory_rule',cwd='/old/repo'"
            )
        ledger.refresh_availability(connection)
        connection.commit()
        return {
            "usage": [tuple(r) for r in connection.execute("SELECT * FROM usage_records")],
            "daily": [tuple(r) for r in connection.execute("SELECT * FROM daily_usage_stats")],
            "monthly": [tuple(r) for r in connection.execute("SELECT * FROM monthly_usage_stats")],
        }


class AssignmentMigrationTests(unittest.TestCase):
    def test_open_schema3_preserves_a_complete_backup_and_current_facts_before_upgrading(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "legacy"
            before = legacy_fixture(root)
            store = Store(root)
            try:
                self.assertEqual(store._db.execute("PRAGMA user_version").fetchone()[0], 4)
                for key, table in (
                    ("usage", "usage_records"),
                    ("daily", "daily_usage_stats"),
                    ("monthly", "monthly_usage_stats"),
                ):
                    self.assertEqual(
                        [tuple(r) for r in store._db.execute(f"SELECT * FROM {table}")], before[key]
                    )
                self.assertIsNotNone(store.migration_backup)
                self.assertEqual(store.migration_backup["store_schema_version"], 3)
                self.assertEqual(
                    store._db.execute("SELECT project_id FROM record_project_links").fetchone()[0],
                    "legacy-project",
                )
                store.save_project("legacy-project", "旧项目", "", [])
                store.refresh_metadata([Path(directory) / "without-old-logs"])
                self.assertEqual(
                    store.analyze("2026-10-01", "2026-10-31", "legacy-project")["summary"][
                        "record_count"
                    ],
                    1,
                )
            finally:
                store.close()
            self.assertEqual(len(list((root / "backups").glob("before-schema4-*.aha-backup"))), 1)
            Store(root).close()
            self.assertEqual(len(list((root / "backups").glob("before-schema4-*.aha-backup"))), 1)

    def test_schema3_backup_is_validated_then_upgraded_only_in_new_restore_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, restored = Path(directory) / "legacy", Path(directory) / "restored"
            before = legacy_fixture(root, missing=True)
            archive = Path(directory) / "schema3.aha-backup"
            result = backup.create_backup(root, archive)
            self.assertEqual(result["store_schema_version"], 3)
            archive_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
            original_hash = hashlib.sha256((root / "aha.sqlite3").read_bytes()).hexdigest()
            restored_result = backup.restore_backup(archive, restored)
            self.assertEqual(restored_result["store_schema_version"], 4)
            self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), archive_hash)
            self.assertEqual(
                hashlib.sha256((root / "aha.sqlite3").read_bytes()).hexdigest(), original_hash
            )
            store = Store(restored)
            try:
                self.assertIsNone(store.migration_backup)
                self.assertEqual(
                    [tuple(r) for r in store._db.execute("SELECT * FROM usage_records")],
                    before["usage"],
                )
                preview = store.preview_associations({"action": "recover"})
                store.apply_associations(
                    preview["preview_id"], "按已有依据恢复", "restored-history-test"
                )
                self.assertEqual(
                    store.analyze("2026-10-01", "2026-10-31", "legacy-project")["summary"][
                        "record_count"
                    ],
                    1,
                )
            finally:
                store.close()

    def test_unknown_schema3_structure_is_rejected_before_backup_or_migration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "legacy"
            legacy_fixture(root)
            with closing(sqlite3.connect(root / "aha.sqlite3")) as connection:
                connection.execute("DROP INDEX usage_time")
                connection.commit()
            before = hashlib.sha256((root / "aha.sqlite3").read_bytes()).hexdigest()
            with self.assertRaises(AppError) as failure:
                Store(root)
            self.assertEqual(failure.exception.code, "invalid_backup")
            self.assertEqual(
                hashlib.sha256((root / "aha.sqlite3").read_bytes()).hexdigest(), before
            )
            self.assertEqual(list((root / "backups").glob("*.aha-backup")), [])

    def test_migration_failure_rolls_back_all_schema_changes_and_keeps_rollback_archive(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "legacy"
            legacy_fixture(root)
            original = migrations.upgrade_schema3

            def fail_after_upgrade(connection, now):
                original(connection, now)
                raise RuntimeError("synthetic migration failure")

            with patch("aha.migrations.upgrade_schema3", side_effect=fail_after_upgrade):
                with self.assertRaises(RuntimeError):
                    Store(root)
            with closing(sqlite3.connect(root / "aha.sqlite3")) as connection:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 3)
                self.assertIsNone(
                    connection.execute(
                        "SELECT name FROM sqlite_master WHERE name=?", ("record_project_links",)
                    ).fetchone()
                )
            self.assertEqual(len(list((root / "backups").glob("*.aha-backup"))), 1)


if __name__ == "__main__":
    unittest.main()
