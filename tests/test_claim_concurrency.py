from __future__ import annotations

import multiprocessing
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from migration_fixtures import legacy_analysis, legacy_store, seed_revision
from test_storage_helpers import analyze_capture, claim, detail, source_data

from aha.domain import AppError
from aha.storage import Store


def compete(root: str, analysis: dict | None, key: str, ready: Any, start: Any, out: Any) -> None:
    store = None
    try:
        store = Store(Path(root))
        ready.put(True)
        if not start.wait(20):
            out.put(("error", "start timeout"))
            return
        if analysis is None:
            out.put(("ok", store._db.execute("PRAGMA user_version").fetchone()[0]))
        else:
            result = store.create_batch(analysis, claim(), key)
            out.put(("ok", result["id"]))
    except AppError as error:
        out.put(("conflict", error.code))
    except BaseException as error:
        out.put(("error", type(error).__name__ + ": " + str(error)))
    finally:
        if store is not None:
            store.close()


class CommitFailureConnection(sqlite3.Connection):
    fail_next_commit = False

    def execute(self, sql: str, parameters: Any = ()) -> sqlite3.Cursor:
        if sql == "COMMIT" and self.fail_next_commit:
            self.fail_next_commit = False
            raise sqlite3.OperationalError("synthetic commit failure")
        return super().execute(sql, parameters)


class ClaimConcurrencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_children(self, analysis: dict | None, same_key: bool = False) -> list[tuple]:
        context = multiprocessing.get_context("spawn")
        ready, output = context.Queue(), context.Queue()
        start = context.Event()
        processes = [
            context.Process(
                target=compete,
                args=(
                    str(self.root),
                    analysis,
                    "same" if same_key else f"process-{index}",
                    ready,
                    start,
                    output,
                ),
            )
            for index in range(2)
        ]
        try:
            for process in processes:
                process.start()
            for _ in processes:
                ready.get(timeout=20)
            start.set()
            results = [output.get(timeout=20) for _ in processes]
            for process in processes:
                process.join(timeout=20)
                self.assertEqual(process.exitcode, 0)
            return results
        finally:
            start.set()
            for process in processes:
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=5)
            ready.close()
            output.close()

    def test_two_independent_connections_only_one_distinct_request_wins(self) -> None:
        first, second = Store(self.root), Store(self.root)
        try:
            analysis = analyze_capture(first)

            def save(pair: tuple[Store, str]) -> tuple:
                try:
                    return ("ok", pair[0].create_batch(analysis, claim(), pair[1])["id"])
                except AppError as error:
                    return ("conflict", error.code)

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(save, [(first, "one"), (second, "two")]))
            self.assertEqual(sum(result[0] == "ok" for result in results), 1)
            self.assertEqual(len(first.list_batches()), 1)
            self.assertEqual(len(first.claim_snapshot()["claims"]), 1)
        finally:
            first.close()
            second.close()

    def test_two_processes_competing_for_one_usage_have_one_winner(self) -> None:
        store = Store(self.root)
        analysis = analyze_capture(store)
        store.close()
        results = self.run_children(analysis)
        self.assertEqual(sum(result[0] == "ok" for result in results), 1, results)
        self.assertTrue(all(result[0] in {"ok", "conflict"} for result in results), results)
        reopened = Store(self.root)
        try:
            self.assertEqual(len(reopened.list_batches()), 1)
            self.assertEqual(len(reopened.claim_snapshot()["claims"]), 1)
        finally:
            reopened.close()

    def test_two_processes_with_one_retry_key_return_the_same_version(self) -> None:
        store = Store(self.root)
        analysis = analyze_capture(store)
        store.close()
        results = self.run_children(analysis, same_key=True)
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0][0], "ok")

    def test_two_processes_upgrade_schema1_once_with_one_backup(self) -> None:
        old = legacy_store(self.root)
        seed_revision(old, "a", 1, 1, legacy_analysis(old))
        old.close()
        results = self.run_children(None)
        self.assertEqual(results, [("ok", 2), ("ok", 2)])
        self.assertEqual(len(list((self.root / "backups").glob("*.sqlite3"))), 1)
        reopened = Store(self.root)
        try:
            self.assertEqual(len(reopened.claim_snapshot()["claims"]), 1)
        finally:
            reopened.close()

    def test_commit_failure_after_all_writes_restores_old_version_and_usage(self) -> None:
        store = Store(self.root)
        try:
            analysis = analyze_capture(
                store, source_data([detail(), detail("r2", created_at=detail()["created_at"] + 1)])
            )
            first = store.create_batch(analysis, claim(), "first")
            original = store.download(first["id"], 1)
            replacement = analyze_capture(
                store, source_data([detail()]), target_batch_id=first["id"]
            )
            store._db.close()
            connection = sqlite3.connect(
                self.root / "aha.sqlite3",
                factory=CommitFailureConnection,
                isolation_level=None,
                check_same_thread=False,
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            store._db = connection
            connection.fail_next_commit = True
            with self.assertRaises(AppError):
                store.create_batch(replacement, claim(purpose="修改"), "failed", first["id"])
            self.assertEqual(store.batch_detail(first["id"])["active_version"], 1)
            self.assertEqual(len(store.batch_detail(first["id"])["revisions"]), 1)
            self.assertEqual(len(store.claim_snapshot()["claims"]), 2)
            self.assertEqual(store.download(first["id"], 1), original)
            self.assertIsNone(
                store._db.execute("SELECT 1 FROM idempotency WHERE key='failed'").fetchone()
            )
        finally:
            store.close()
