"""Fresh schema guard and strict runtime gating; no legacy business migration."""

from __future__ import annotations

import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from aha.domain import AppError
from aha.migrations import initialize_query_indexes, sqlite_wal_safe
from aha.storage import Store


class FreshSchemaTests(unittest.TestCase):
    def test_new_empty_database_is_schema3_and_reopens(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = Store(root)
            self.assertEqual(store._db.execute("PRAGMA user_version").fetchone()[0], 3)
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
