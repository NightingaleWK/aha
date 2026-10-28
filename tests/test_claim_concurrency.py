from __future__ import annotations

import multiprocessing
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from unittest.mock import patch

from billing_fixtures import frozen_analysis, seed_analysis
from test_storage_helpers import claim, detail, source_data

from aha import decimal_sql
from aha.batches import _prepare_selection
from aha.domain import AppError
from aha.storage import Store


def compete(root: str, analysis: dict, key: str, ready: Any, start: Any, out: Any) -> None:
    store = None
    try:
        store = Store(Path(root))
        ready.put(True)
        if not start.wait(20):
            out.put(("error", "start timeout"))
            return
        saved = store.create_batch(analysis, claim(), key)
        out.put(("ok", saved["id"], saved["version"]))
    except AppError as error:
        out.put(("conflict", error.code))
    except BaseException as error:
        out.put(("error", type(error).__name__ + ": " + str(error)))
    finally:
        if store is not None:
            store.close()


class CommitFailureConnection(sqlite3.Connection):
    fail_revision_commit = False
    revision_written = False

    def execute(self, sql: str, parameters: Any = ()) -> sqlite3.Cursor:
        if sql.startswith("INSERT INTO revisions") and self.fail_revision_commit:
            self.revision_written = True
        if sql == "COMMIT" and self.revision_written:
            self.revision_written = False
            self.fail_revision_commit = False
            raise sqlite3.OperationalError("synthetic final commit failure")
        return super().execute(sql, parameters)


class ClaimConcurrencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_children(self, analysis: dict, same_key: bool = False) -> list[tuple]:
        context = multiprocessing.get_context("spawn")
        ready, output, start = context.Queue(), context.Queue(), context.Event()
        children = [
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
            for child in children:
                child.start()
            for _ in children:
                ready.get(timeout=20)
            start.set()
            results = [output.get(timeout=20) for _ in children]
            for child in children:
                child.join(timeout=20)
                self.assertEqual(child.exitcode, 0)
            return results
        finally:
            start.set()
            for child in children:
                if child.is_alive():
                    child.terminate()
                    child.join(timeout=5)
            ready.close()
            output.close()

    def test_two_connections_have_one_winner_for_distinct_requests(self) -> None:
        first, second = Store(self.root), Store(self.root)
        try:
            preview = seed_analysis(first)

            def save(pair: tuple[Store, str]) -> tuple:
                try:
                    return ("ok", pair[0].create_batch(preview, claim(), pair[1])["id"])
                except AppError as error:
                    return ("conflict", error.code)

            with ThreadPoolExecutor(max_workers=2) as pool:
                result = list(pool.map(save, ((first, "one"), (second, "two"))))
            self.assertEqual(sum(item[0] == "ok" for item in result), 1, result)
            self.assertEqual(len(first.list_batches()), 1)
            self.assertEqual(
                first._db.execute("SELECT COUNT(*) FROM usage_claims").fetchone()[0], 1
            )
        finally:
            first.close()
            second.close()

    def test_two_processes_have_one_winner_for_distinct_requests(self) -> None:
        store = Store(self.root)
        try:
            preview = seed_analysis(store)
        finally:
            store.close()
        result = self.run_children(preview)
        self.assertEqual(sum(item[0] == "ok" for item in result), 1, result)
        self.assertTrue(all(item[0] in {"ok", "conflict"} for item in result), result)
        reopened = Store(self.root)
        try:
            self.assertEqual(len(reopened.list_batches()), 1)
            self.assertEqual(
                reopened._db.execute("SELECT COUNT(*) FROM usage_claims").fetchone()[0], 1
            )
        finally:
            reopened.close()

    def test_same_key_processes_return_same_persisted_version(self) -> None:
        store = Store(self.root)
        try:
            preview = seed_analysis(store)
        finally:
            store.close()
        result = self.run_children(preview, same_key=True)
        self.assertEqual(result[0], result[1], result)
        self.assertEqual(result[0][0], "ok")

    def test_same_request_committed_between_replay_check_and_freezing_is_replayed(self) -> None:
        first, second = Store(self.root), Store(self.root)
        winner = None
        try:
            analysis = seed_analysis(first)

            def prepare(store, *args):
                nonlocal winner
                if store is first:
                    winner = second.create_batch(analysis, claim(), "same-request-race")
                return _prepare_selection(store, *args)

            with patch("aha.batches._prepare_selection", side_effect=prepare):
                replayed = first.create_batch(analysis, claim(), "same-request-race")
            self.assertEqual(replayed, winner)
            self.assertEqual(len(first.list_batches()), 1)
            self.assertEqual(
                first._db.execute("SELECT COUNT(*) FROM usage_claims").fetchone()[0], 1
            )
        finally:
            first.close()
            second.close()

    def test_failed_final_commit_preserves_old_version_claims_and_original_zip(self) -> None:
        store = Store(self.root)
        try:
            initial = seed_analysis(
                store,
                source_data(
                    [
                        detail(),
                        detail("r2", created_at=detail()["created_at"] + 1),
                    ]
                ),
            )
            first = store.create_batch(initial, claim(), "first")
            original_path, _ = store.download(first["id"], 1)
            original = original_path.read_bytes()
            revision = frozen_analysis(store, first["id"])
            store._db.close()
            connection = sqlite3.connect(
                self.root / "aha.sqlite3",
                factory=CommitFailureConnection,
                isolation_level=None,
                check_same_thread=False,
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            decimal_sql.register(connection)
            store._db = connection
            connection.fail_revision_commit = True
            with self.assertRaises(AppError):
                store.create_batch(
                    revision,
                    claim(purpose="修改"),
                    "failed",
                    first["id"],
                    expected_generation=first["generation"],
                    expected_active_version=1,
                )
            history = store.batch_detail(first["id"])
            self.assertEqual(history["active_version"], 1)
            self.assertEqual(len(history["revisions"]), 1)
            self.assertEqual(
                store._db.execute("SELECT COUNT(*) FROM usage_claims").fetchone()[0], 2
            )
            self.assertIsNone(
                store._db.execute("SELECT 1 FROM idempotency WHERE key='failed'").fetchone()
            )
            self.assertEqual(original_path.read_bytes(), original)
            self.assertEqual(len(list((self.root / "packages").iterdir())), 1)
        finally:
            store.close()
