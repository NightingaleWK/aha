"""Versioned schema guards, runtime gating and retirement of legacy facts."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from test_storage_helpers import detail, rollup, source_data

from aha import backup, ledger, migrations
from aha.decimal_sql import register
from aha.domain import AppError, record_key, row_fingerprint
from aha.migrations import SCHEMA_VERSION, initialize_query_indexes, sqlite_wal_safe
from aha.storage import Store


def _downgrade_to_schema_five(connection: sqlite3.Connection) -> None:
    connection.execute("DROP TRIGGER usage_records_detail_insert")
    connection.execute("DROP TRIGGER usage_records_detail_update")
    connection.execute("DROP INDEX usage_claim_archived_day")
    connection.execute(migrations.LEGACY_ROLLUP_INDEX)
    migrations.initialize_source_observations(connection)
    connection.execute("PRAGMA user_version=5")


class FreshSchemaTests(unittest.TestCase):
    def test_new_empty_database_uses_current_schema_and_reopens(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = Store(root)
            self.assertEqual(store._db.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
            names = {
                row[0]
                for row in store._db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            self.assertNotIn("captures", names)
            self.assertNotIn("legacy_holds", names)
            self.assertIn("usage_versions", names)
            indexes = {row[0] for row in store._db.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            )}
            query_indexes = {"stats_excluded_day_model_state",
                             "stats_excluded_project_day_model_state"}
            self.assertTrue(query_indexes.issubset(indexes))
            for name in query_indexes:
                store._db.execute(f"DROP INDEX {name}")
            initialize_query_indexes(store._db)
            initialize_query_indexes(store._db)
            rebuilt = {row[0] for row in store._db.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            )}
            self.assertTrue(query_indexes.issubset(rebuilt))
            store.close()
            Store(root).close()

    def test_trial_and_unknown_databases_refused_without_data_changes(self) -> None:
        for version in (1, 2, 9, 0):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                path = root / "aha.sqlite3"
                connection = sqlite3.connect(path)
                connection.execute("CREATE TABLE trial(value TEXT)")
                connection.execute("INSERT INTO trial VALUES('preserve')")
                connection.execute(f"PRAGMA user_version={version}")
                connection.commit()
                connection.close()
                before = hashlib.sha256(path.read_bytes()).hexdigest()
                with self.assertRaises(AppError) as error:
                    Store(root)
                self.assertEqual(error.exception.code, "unsupported_store")
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)

    def test_wal_fix_branches_are_explicit_not_just_python_version(self) -> None:
        for version in ((3, 46, 1), (3, 51, 2), (3, 50, 6), (3, 44, 5), (3, 45, 9)):
            self.assertFalse(sqlite_wal_safe(version))
        for version in ((3, 51, 3), (3, 53, 1), (3, 50, 7), (3, 44, 6)):
            self.assertTrue(sqlite_wal_safe(version))

    def test_retires_legacy_facts_atomically_and_restores_detail_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "old"
            original = detail()
            store = Store(root)
            self.addCleanup(store.close)
            store.sync_data(source_data([original]))
            store.close()
            with closing(sqlite3.connect(root / "aha.sqlite3")) as db, db:
                db.row_factory = sqlite3.Row
                register(db)
                db.execute("PRAGMA foreign_keys=ON")
                _downgrade_to_schema_five(db)
                current = dict(db.execute("SELECT * FROM usage_records").fetchone())
                legacy = rollup(date=current["day"])
                retired = record_key(legacy, "rollup")
                source, run, now = db.execute(
                    "SELECT source_id,id,completed_at FROM sync_runs"
                ).fetchone()
                fingerprint = row_fingerprint(legacy, "rollup")
                version = db.execute(
                    "INSERT INTO usage_versions(record_key,content_hash,payload_json,"
                    "created_at,source_id) VALUES(?,?,?,?,?) RETURNING id",
                    (retired, fingerprint, json.dumps(legacy), now, source),
                ).fetchone()[0]
                fact = {
                    **current, "record_key": retired, "kind": "rollup", "version_id": version,
                    "session_id": None, "content_hash": fingerprint, "total_cost_usd": "19.123",
                    "request_count": "14",
                }
                db.execute(
                    "INSERT INTO usage_records(" + ",".join(fact) + ") VALUES("
                    + ",".join("?" for _ in fact) + ")", tuple(fact.values())
                )
                db.execute("INSERT INTO record_evidence VALUES(?,?,?)", (version, source, run))
                db.execute(
                    """INSERT INTO record_project_links(record_key,basis,basis_json,
                    created_at,updated_at) VALUES(?,'unassigned','{}',?,?)""",
                    (retired, now, now),
                )
                db.execute("UPDATE coverage_groups SET basis='rollup'")
                db.execute("UPDATE usage_records SET suppressed=1 WHERE kind='detail'")
                case_id = ledger.create_case(
                    db, "coverage", "旧汇总覆盖核对。", {}, coverage_key=current["coverage_key"],
                )
                db.execute(
                    "UPDATE reconciliation_cases SET state='resolved' WHERE id=?", (case_id,)
                )
                db.execute(
                    "INSERT INTO reconciliation_idempotency VALUES(?,?,?)",
                    ("retired-test-replay", "signature", json.dumps({"id": case_id})),
                )
                ledger.refresh_daily(db)
                migrations.validate_structure(db, 5)

            retire = migrations._retire_rollups

            def interrupted(connection: sqlite3.Connection) -> None:
                retire(connection)
                raise AppError("synthetic_failure", "测试迁移中断。")

            with (
                patch.object(migrations, "_retire_rollups", interrupted),
                self.assertRaises(AppError),
            ):
                Store(root)
            with closing(sqlite3.connect(root / "aha.sqlite3")) as db:
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 5)
                self.assertEqual(db.execute(
                    "SELECT kind,suppressed FROM usage_records ORDER BY kind"
                ).fetchall(), [("detail", 1), ("rollup", 0)])
                migrations.validate_structure(db, 5)
            archive, = (root / "backups").glob("*.aha-backup")
            restored = base / "restored"
            self.assertEqual(backup.restore_backup(archive, restored)["store_schema_version"], 6)

            for target in (root, restored):
                with self.subTest(target=target.name):
                    upgraded = Store(target)
                    try:
                        with upgraded.read_connection() as db:
                            migrations.validate_structure(db, SCHEMA_VERSION)
                            self.assertEqual(
                                [tuple(row) for row in db.execute(
                                    "SELECT kind,suppressed,total_cost_usd FROM usage_records"
                                )], [("detail", 0, current["total_cost_usd"])]
                            )
                            for table in ("usage_versions", "record_project_links"):
                                self.assertIsNone(db.execute(
                                    f"SELECT 1 FROM {table} WHERE record_key=?", (retired,)
                                ).fetchone())
                            self.assertIsNone(db.execute(
                                "SELECT 1 FROM reconciliation_idempotency WHERE key=?",
                                ("retired-test-replay",),
                            ).fetchone())
                            for table in ("daily_usage_stats", "monthly_usage_stats"):
                                self.assertEqual(tuple(db.execute(
                                    f"SELECT kind, row_count, total_cost_usd FROM {table}"
                                ).fetchone()), ("detail", 1, current["total_cost_usd"]))
                            self.assertIsNone(db.execute("PRAGMA foreign_key_check").fetchone())
                    finally:
                        upgraded.close()

    def test_rechecks_retired_rollup_overlap_against_retained_detail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = datetime(2026, 10, 27, 15, 59, 59, tzinfo=UTC)
            history = detail(created_at=int(snapshot.timestamp()))
            store = Store(root)
            try:
                store.sync_data(source_data([history]))
                with store._transaction():
                    db = store._db
                    source_id, run_id, now = db.execute(
                        "SELECT source_id,id,completed_at FROM sync_runs"
                    ).fetchone()
                    paired = {
                        **history, "request_id": "with-retained-history",
                        "data_source": "codex_native", "created_at": history["created_at"] + 1,
                    }
                    standalone = {**paired, "request_id": "rollup-overlap-only", "session_id": "s2"}
                    cases = {}
                    for candidate in (paired, standalone):
                        key = record_key(candidate)
                        fingerprint = row_fingerprint(candidate)
                        version = db.execute(
                            "INSERT INTO usage_versions(record_key,content_hash,payload_json,"
                            "created_at,source_id) VALUES(?,?,?,?,?) RETURNING id",
                            (key, fingerprint, json.dumps(candidate), now, source_id),
                        ).fetchone()[0]
                        ledger.set_current(db, version)
                        cases[key] = ledger.create_case(
                            db, "native_overlap", "旧汇总覆盖核对。",
                            {"pending_reason": "historical_rollup"}, key=key, source_id=source_id,
                        )
                        if candidate is paired:
                            evidence = {
                                "kind": "response", "snapshot_timestamp": snapshot.isoformat(),
                            }
                            db.execute("INSERT INTO codex_event_evidence VALUES(?,?,?,?,?,?,?)", (
                                version, source_id, "verified-receipt", "event", run_id, None,
                                json.dumps(evidence),
                            ))
                    ledger.refresh_availability(db)
                    _downgrade_to_schema_five(db)
            finally:
                store.close()

            upgraded = Store(root)
            try:
                with upgraded.read_connection() as db:
                    self.assertEqual(
                        [tuple(row) for row in db.execute("""
                            SELECT id,json_extract(info_json,'$.pending_reason')
                            FROM reconciliation_cases WHERE state='open'
                        """)],
                        [(cases[record_key(paired)], "historical_usage_unverified")],
                    )
                    self.assertEqual(
                        dict(db.execute("SELECT record_key,availability_state FROM usage_records")),
                        {
                            record_key(history): "available",
                            record_key(paired): "pending",
                            record_key(standalone): "available",
                        },
                    )
            finally:
                upgraded.close()
