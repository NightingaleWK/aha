"""Native source processing budgets, lease recovery and atomic staging."""

from __future__ import annotations

import hashlib
import sqlite3
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from test_native_sync import usage
from test_storage_helpers import claim, detail, source_data

from aha import sync
from aha.codex_sessions import CodexSource
from aha.domain import AppError
from aha.native_sync import NativeBatch
from aha.storage import Store
from aha.sync import _Stager


class NativeStagingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = Store(self.root / "data")
        self.source = CodexSource("windows", str(self.root / "synthetic-codex"))
        self.enterContext(patch("aha.native_sync.scan_source", side_effect=self.scan_source))
        self.store.sync_data(source_data(), trust="live")
        analysis = self.store.analyze("2026-10-01", "2026-10-31")
        batch = self.store.create_batch(analysis, claim(), "snapshot-existing-package")
        self.package, _ = self.store.download(batch["id"], batch["version"])
        self.package_sha = hashlib.sha256(self.package.read_bytes()).hexdigest()
        self.before = self.store.ledger_status()

    def tearDown(self) -> None:
        self.store.close()
        self.temporary.cleanup()

    def make_source(self, count: int = 1) -> None:
        timestamp = int(detail()["created_at"]) + 86400
        self.events = [usage(f"new-{n}", created_at=timestamp) for n in range(count)]

    def scan_source(self, source, load_cursor, on_event, on_cursor, *, cancel):
        self.assertEqual(source, self.source)
        for event in self.events:
            on_event(event)
            if cancel.is_set():
                raise AppError("sync_cancelled", "同步已取消。", 409)
        on_cursor("sessions/fixture.jsonl", {"offset": 100})
        return {
            "files": 1, "bytes_read": 100, "events": len(self.events), "coverage": "complete",
            "issues": {}, "first_at": self.events[0].row["created_at"],
            "last_at": self.events[-1].row["created_at"],
        }

    def sync_native(self, *, cancel=None):
        return self.store.sync_codex(self.source, "fixture-codex", cancel=cancel)

    def assert_failed_without_publication(self, code: str) -> None:
        after = self.store.ledger_status()
        self.assertEqual(after["last_successful_sync_at"], self.before["last_successful_sync_at"])
        self.assertEqual(after["data_revision"], self.before["data_revision"])
        self.assertEqual(after["counts"], self.before["counts"])
        self.assertEqual(after["last_attempt"]["state"], "failed")
        self.assertEqual(after["last_attempt"]["error_code"], code)
        self.assertNotIn(str(self.root), after["last_attempt"]["error_message"])
        self.assertEqual(hashlib.sha256(self.package.read_bytes()).hexdigest(), self.package_sha)
        with self.store.read_connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM sync_stage").fetchone()[0], 0)
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM sync_pricing").fetchone()[0], 0
            )
        self.assertEqual(list((self.store.data_dir / "temporary").iterdir()), [])

    def test_last_batch_commit_must_finish_within_local_budget(self) -> None:
        self.make_source()
        original = _Stager.flush
        committed = []

        def slow_commit(stager):
            original(stager)
            committed.append(True)
            time.sleep(0.6)

        with patch("aha.native_sync.LOCAL_STAGING_TIMEOUT", 0.5), patch.object(
            _Stager, "flush", slow_commit
        ):
            with self.assertRaises(AppError) as error:
                self.sync_native()
        self.assertEqual(error.exception.code, "sync_processing_timeout")
        self.assertEqual(committed, [True])
        self.assert_failed_without_publication("sync_processing_timeout")

    def test_waiting_for_local_writer_reports_expired_processing_budget(self) -> None:
        self.make_source()
        flushing, locked = threading.Event(), threading.Event()
        original = _Stager.flush

        def hold_writer():
            self.assertTrue(flushing.wait(3))
            with self.store._lock:
                locked.set()
                time.sleep(0.3)

        def waiting_flush(stager):
            flushing.set()
            self.assertTrue(locked.wait(3))
            return original(stager)

        with ThreadPoolExecutor(max_workers=2) as pool, patch(
            "aha.native_sync.LOCAL_STAGING_TIMEOUT", 0.1
        ), patch.object(_Stager, "flush", waiting_flush):
            writer = pool.submit(hold_writer)
            with self.assertRaises(AppError) as error:
                self.sync_native()
            writer.result(timeout=3)
        self.assertEqual(error.exception.code, "sync_processing_timeout")
        self.assert_failed_without_publication("sync_processing_timeout")

    def test_external_writer_defers_failure_cleanup_until_same_store_retry(self) -> None:
        self.make_source(520)
        trigger, locked, release = threading.Event(), threading.Event(), threading.Event()
        original_flush = _Stager.flush
        flushes = 0

        def hold_database_writer():
            self.assertTrue(trigger.wait(5))
            with closing(sqlite3.connect(self.store.data_dir / "aha.sqlite3")) as connection:
                connection.execute("BEGIN IMMEDIATE")
                locked.set()
                try:
                    self.assertTrue(release.wait(10))
                finally:
                    connection.rollback()

        def blocked_flush(stager):
            nonlocal flushes
            flushes += 1
            if flushes == 1:
                original_flush(stager)
                # Include a staged pricing row to verify both deferred cleanup tables.
                with self.store._transaction():
                    self.store._db.execute(
                        "INSERT INTO sync_pricing VALUES(?,?,?)", (stager.run_id, "fixture", "{}")
                    )
                return
            trigger.set()
            self.assertTrue(locked.wait(5))
            return original_flush(stager)

        with ThreadPoolExecutor(max_workers=1) as pool:
            writer = pool.submit(hold_database_writer)
            try:
                started = time.monotonic()
                with patch.object(_Stager, "flush", blocked_flush):
                    with self.assertRaises(AppError) as error:
                        self.sync_native()
                self.assertEqual(error.exception.code, "store_busy")
                self.assertLess(time.monotonic() - started, 3)
                self.assertFalse(writer.done(), "failure waited for the competing writer")
                after = self.store.ledger_status()
                failed_run = after["last_attempt"]["id"]
                self.assertEqual(after["last_attempt"]["state"], "running")
                self.assertEqual(
                    after["last_successful_sync_at"], self.before["last_successful_sync_at"]
                )
                self.assertEqual(after["counts"], self.before["counts"])
                self.assertEqual(
                    hashlib.sha256(self.package.read_bytes()).hexdigest(), self.package_sha
                )
                with self.store.read_connection() as connection:
                    self.assertEqual(connection.execute(
                        "SELECT COUNT(*) FROM sync_stage WHERE run_id=?", (failed_run,)
                    ).fetchone()[0], 512)
                    self.assertEqual(connection.execute(
                        "SELECT COUNT(*) FROM sync_pricing WHERE run_id=?", (failed_run,)
                    ).fetchone()[0], 1)
                self.assertEqual(list((self.store.data_dir / "temporary").iterdir()), [])
                started = time.monotonic()
                with self.assertRaises(AppError) as retry_while_locked:
                    self.sync_native()
                self.assertEqual(retry_while_locked.exception.code, "store_busy")
                self.assertLess(time.monotonic() - started, 3)
            finally:
                release.set()
            writer.result(timeout=5)

        # A failed recovery must roll back the changes and retain its in-memory intent.
        record_failure = sync._record_failure

        def broken_recovery(store, run_id, code, message):
            record_failure(store, run_id, code, message)
            raise sqlite3.OperationalError("synthetic recovery failure")

        with patch.object(sync, "_record_failure", broken_recovery):
            with self.assertRaises(AppError) as recovery_error:
                self.sync_native()
        self.assertEqual(recovery_error.exception.code, "storage_write_failed")
        with self.store.read_connection() as connection:
            self.assertEqual(connection.execute(
                "SELECT state FROM sync_runs WHERE id=?", (failed_run,)
            ).fetchone()[0], "running")
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM sync_stage WHERE run_id=?", (failed_run,)
            ).fetchone()[0], 512)

        self.assertEqual(self.sync_native()["state"], "completed")
        with self.store.read_connection() as connection:
            failed = connection.execute(
                "SELECT state,error_code FROM sync_runs WHERE id=?", (failed_run,)
            ).fetchone()
            self.assertEqual(tuple(failed), ("failed", "store_busy"))
            for table in ("sync_stage", "sync_pricing"):
                self.assertEqual(connection.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE run_id=?", (failed_run,)
                ).fetchone()[0], 0)
        self.assertEqual(hashlib.sha256(self.package.read_bytes()).hexdigest(), self.package_sha)

    def test_python_writer_lock_does_not_block_failure_cleanup_forever(self) -> None:
        self.make_source(520)
        trigger, locked, release = threading.Event(), threading.Event(), threading.Event()
        original_flush = _Stager.flush
        flushes = 0

        def hold_python_writer():
            self.assertTrue(trigger.wait(5))
            with self.store._lock:
                locked.set()
                self.assertTrue(release.wait(10))

        def blocked_flush(stager):
            nonlocal flushes
            flushes += 1
            if flushes == 2:
                trigger.set()
                self.assertTrue(locked.wait(5))
            return original_flush(stager)

        with ThreadPoolExecutor(max_workers=2) as pool:
            writer = pool.submit(hold_python_writer)
            try:
                with patch.object(_Stager, "flush", blocked_flush):
                    started = time.monotonic()
                    result = pool.submit(self.sync_native)
                    with self.assertRaises(AppError) as error:
                        result.result(timeout=3)
                    self.assertEqual(error.exception.code, "store_busy")
                    self.assertLess(time.monotonic() - started, 3)
                    self.assertFalse(writer.done())
            finally:
                release.set()
            writer.result(timeout=5)
        self.assertEqual(self.sync_native()["state"], "completed")
        with self.store.read_connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM sync_stage").fetchone()[0], 0)

    def seed_running_with_staging(self, run_id: str, heartbeat: str) -> None:
        with self.store._transaction():
            self.store._db.execute(
                "INSERT INTO sync_runs(id,state,trigger,started_at,heartbeat_at) "
                "VALUES(?,'running','manual',?,?)", (run_id, heartbeat, heartbeat)
            )
            self.store._db.execute(
                "INSERT INTO sync_stage VALUES(?,?,?,?,?)", (run_id, "fixture", "detail", "x", "{}")
            )
            self.store._db.execute(
                "INSERT INTO sync_pricing VALUES(?,?,?)", (run_id, "fixture", "{}")
            )

    def test_expired_lease_recovers_staging_after_store_restart(self) -> None:
        self.make_source()
        self.seed_running_with_staging("expired", "2000-01-01T00:00:00+00:00")
        self.store.close()
        self.store = Store(self.root / "data")
        self.assertEqual(self.sync_native()["state"], "completed")
        with self.store.read_connection() as connection:
            self.assertEqual(tuple(connection.execute(
                "SELECT state,error_code FROM sync_runs WHERE id='expired'"
            ).fetchone()), ("failed", "sync_interrupted"))
            for table in ("sync_stage", "sync_pricing"):
                self.assertEqual(connection.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE run_id='expired'"
                ).fetchone()[0], 0)

    def test_unexpired_other_run_and_its_staging_are_not_recovered(self) -> None:
        self.make_source()
        self.seed_running_with_staging("active", self.store._now())
        with self.assertRaises(AppError) as error:
            self.sync_native()
        self.assertEqual(error.exception.code, "sync_in_progress")
        with self.store.read_connection() as connection:
            self.assertEqual(connection.execute(
                "SELECT state FROM sync_runs WHERE id='active'"
            ).fetchone()[0], "running")
            for table in ("sync_stage", "sync_pricing"):
                self.assertEqual(connection.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE run_id='active'"
                ).fetchone()[0], 1)

    def test_expired_recovery_commits_before_new_competing_run_is_checked(self) -> None:
        self.make_source()
        self.seed_running_with_staging("expired", "2000-01-01T00:00:00+00:00")
        recover = sync._recover_failed_runs

        def start_competing_run(store):
            recover(store)
            self.seed_running_with_staging("active", store._now())

        with patch.object(sync, "_recover_failed_runs", start_competing_run):
            with self.assertRaises(AppError) as error:
                self.sync_native()
        self.assertEqual(error.exception.code, "sync_in_progress")
        with self.store.read_connection() as connection:
            self.assertEqual(connection.execute(
                "SELECT state FROM sync_runs WHERE id='expired'"
            ).fetchone()[0], "failed")
            self.assertEqual(connection.execute(
                "SELECT state FROM sync_runs WHERE id='active'"
            ).fetchone()[0], "running")
            for table in ("sync_stage", "sync_pricing"):
                self.assertEqual(connection.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE run_id='expired'"
                ).fetchone()[0], 0)
                self.assertEqual(connection.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE run_id='active'"
                ).fetchone()[0], 1)

    def test_both_cancellation_signals_interrupt_source_even_when_both_supplied(self) -> None:
        self.make_source()
        original = NativeBatch.observe
        for signal in ("explicit", "store"):
            with self.subTest(signal=signal):
                external = threading.Event()

                def cancel_after_first_row(batch, event):
                    original(batch, event)
                    (external if signal == "explicit" else self.store._sync_cancel).set()

                try:
                    with patch.object(NativeBatch, "observe", cancel_after_first_row):
                        with self.assertRaises(AppError) as error:
                            self.sync_native(cancel=external)
                    self.assertEqual(error.exception.code, "sync_cancelled")
                    self.assert_failed_without_publication("sync_cancelled")
                finally:
                    self.store._sync_cancel.clear()

    def test_both_cancellation_signals_interrupt_partial_local_staging(self) -> None:
        self.make_source(520)
        original = _Stager.add_usage
        for signal in ("explicit", "store"):
            with self.subTest(signal=signal):
                external = threading.Event()
                added = 0

                def cancel_after_batch(stager, kind, row):
                    nonlocal added
                    added += 1
                    if added == 513:  # One full batch has been committed to staging.
                        (external if signal == "explicit" else self.store._sync_cancel).set()
                    return original(stager, kind, row)

                try:
                    with patch.object(_Stager, "add_usage", cancel_after_batch):
                        with self.assertRaises(AppError) as error:
                            self.sync_native(cancel=external)
                    self.assertEqual(error.exception.code, "sync_cancelled")
                    self.assert_failed_without_publication("sync_cancelled")
                finally:
                    self.store._sync_cancel.clear()

    def test_spool_write_and_staged_replay_failure_close_the_temporary_database(self) -> None:
        self.make_source(520)
        connect = sqlite3.connect
        original_add = _Stager.add_usage
        for phase in ("write", "replay"):
            with self.subTest(phase=phase):
                opened = []
                added = 0

                def capture(database, *args, **kwargs):
                    connection = connect(database, *args, **kwargs)
                    if database == "":
                        opened.append(connection)
                    return connection

                def interrupted_replay(stager, kind, row):
                    nonlocal added
                    added += 1
                    if added == 513:
                        raise OSError("private staged data path")
                    return original_add(stager, kind, row)

                effect = (
                    patch.object(NativeBatch, "observe", side_effect=OSError("private path"))
                    if phase == "write" else patch.object(_Stager, "add_usage", interrupted_replay)
                )
                with patch("aha.native_sync.sqlite3.connect", side_effect=capture), effect:
                    with self.assertRaises(AppError) as error:
                        self.sync_native()
                self.assertEqual(error.exception.code, "sync_failed")
                self.assertEqual(len(opened), 1)
                with self.assertRaises(sqlite3.ProgrammingError):
                    opened[0].execute("SELECT 1")
                self.assert_failed_without_publication("sync_failed")

    def test_spool_creation_failure_is_a_failed_run_with_safe_error(self) -> None:
        self.make_source()
        connect = sqlite3.connect

        def fail_temporary(database, *args, **kwargs):
            if database == "":
                raise sqlite3.OperationalError("private temporary directory")
            return connect(database, *args, **kwargs)

        with patch("aha.native_sync.sqlite3.connect", side_effect=fail_temporary):
            with self.assertRaises(AppError) as error:
                self.sync_native()
        self.assertEqual(error.exception.code, "sync_failed")
        self.assert_failed_without_publication("sync_failed")


if __name__ == "__main__":
    unittest.main()
