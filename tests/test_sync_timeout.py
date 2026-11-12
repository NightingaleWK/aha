"""Source snapshots, local staging budgets and failure isolation."""

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

from test_sources import database
from test_storage_helpers import claim, detail, source_data

from aha import sources, sync
from aha.domain import AppError, record_key
from aha.storage import Store
from aha.sync import _Stager


class SnapshotStagingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = Store(self.root / "data")
        self.enterContext(patch(
            "aha.source_bindings.installation_id", return_value="synthetic-timeout-installation"
        ))
        self.store.sync_data(source_data(), trust="live")
        analysis = self.store.analyze("2026-10-01", "2026-10-31")
        batch = self.store.create_batch(analysis, claim(), "snapshot-existing-package")
        self.package, _ = self.store.download(batch["id"], batch["version"])
        self.package_sha = hashlib.sha256(self.package.read_bytes()).hexdigest()
        self.before = self.store.ledger_status()
        self.source = self.root / "synthetic-source.sqlite"

    def tearDown(self) -> None:
        self.store.close()
        self.temporary.cleanup()

    def make_source(self, count: int = 1) -> None:
        with closing(database(self.source, [detail(f"new-{n}") for n in range(count)])):
            pass

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

    def test_source_writer_commits_during_slow_local_processing_of_prior_snapshot(self) -> None:
        self.make_source()
        staging, committed = threading.Event(), threading.Event()
        original_add = _Stager.add
        first = True

        def slow_add(stager, table, row):
            nonlocal first
            if first:
                first = False
                staging.set()
                self.assertTrue(committed.wait(3), "source writer was blocked by a read lock")
                time.sleep(5.1)  # Exceeds the old source-plus-processing budget.
            return original_add(stager, table, row)

        def update_source():
            self.assertTrue(staging.wait(3))
            with closing(sqlite3.connect(self.source, timeout=1)) as connection:
                connection.execute("UPDATE proxy_request_logs SET output_tokens=77")
                connection.commit()
            committed.set()

        with ThreadPoolExecutor(max_workers=2) as pool, patch.object(_Stager, "add", slow_add):
            writer = pool.submit(update_source)
            run = pool.submit(self.store.sync_sqlite, self.source)
            result = run.result(timeout=15)
            writer.result(timeout=3)

        self.assertEqual(result["state"], "completed")
        self.assertGreater(result["timings_ms"]["local_staging_ms"], 5000)
        self.assertLess(result["timings_ms"]["source_scan_ms"], 5000)
        with self.store.read_connection() as connection:
            output = connection.execute(
                "SELECT output_tokens FROM usage_records WHERE record_key=?",
                (record_key(detail("new-0")),),
            ).fetchone()[0]
        self.assertEqual(output, "10")
        with closing(sqlite3.connect(self.source)) as connection:
            self.assertEqual(connection.execute(
                "SELECT output_tokens FROM proxy_request_logs"
            ).fetchone()[0], 77)
        self.assertEqual(list((self.store.data_dir / "temporary").iterdir()), [])

    def test_source_timeout_remains_distinct_and_cleans_snapshot(self) -> None:
        self.make_source()
        original = sources.canonical_bytes

        def slow_projection(value):
            time.sleep(0.02)
            return original(value)

        with patch.object(sources, "SNAPSHOT_TIMEOUT", 0.005), patch.object(
            sources, "canonical_bytes", slow_projection
        ):
            with self.assertRaises(AppError) as error:
                self.store.sync_sqlite(self.source)
        self.assertEqual(error.exception.code, "source_busy")
        self.assert_failed_without_publication("source_busy")
        with closing(sqlite3.connect(self.source, timeout=1)) as connection:
            connection.execute("UPDATE proxy_request_logs SET output_tokens=11")
            connection.commit()

    def test_last_batch_commit_must_finish_within_local_budget(self) -> None:
        self.make_source()
        original = _Stager.flush
        committed = []

        def slow_commit(stager):
            original(stager)
            committed.append(True)
            time.sleep(0.6)

        with patch("aha.sync.LOCAL_STAGING_TIMEOUT", 0.5), patch.object(
            _Stager, "flush", slow_commit
        ):
            with self.assertRaises(AppError) as error:
                self.store.sync_sqlite(self.source)
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
            "aha.sync.LOCAL_STAGING_TIMEOUT", 0.1
        ), patch.object(_Stager, "flush", waiting_flush):
            writer = pool.submit(hold_writer)
            with self.assertRaises(AppError) as error:
                self.store.sync_sqlite(self.source)
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
                        self.store.sync_sqlite(self.source)
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
                    self.store.sync_sqlite(self.source)
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
                self.store.sync_sqlite(self.source)
        self.assertEqual(recovery_error.exception.code, "storage_write_failed")
        with self.store.read_connection() as connection:
            self.assertEqual(connection.execute(
                "SELECT state FROM sync_runs WHERE id=?", (failed_run,)
            ).fetchone()[0], "running")
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM sync_stage WHERE run_id=?", (failed_run,)
            ).fetchone()[0], 512)

        self.assertEqual(self.store.sync_sqlite(self.source)["state"], "completed")
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
                    result = pool.submit(self.store.sync_sqlite, self.source)
                    with self.assertRaises(AppError) as error:
                        result.result(timeout=3)
                    self.assertEqual(error.exception.code, "store_busy")
                    self.assertLess(time.monotonic() - started, 3)
                    self.assertFalse(writer.done())
            finally:
                release.set()
            writer.result(timeout=5)
        self.assertEqual(self.store.sync_sqlite(self.source)["state"], "completed")
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
        self.assertEqual(self.store.sync_sqlite(self.source)["state"], "completed")
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
            self.store.sync_sqlite(self.source)
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
                self.store.sync_sqlite(self.source)
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
        original = sources.scan_sqlite
        for signal in ("explicit", "store"):
            with self.subTest(signal=signal):
                external = threading.Event()

                def cancel_after_first_row(path, sink, **kwargs):
                    def interrupted_sink(table, row):
                        sink(table, row)
                        (external if signal == "explicit" else self.store._sync_cancel).set()
                    return original(path, interrupted_sink, **kwargs)

                try:
                    with patch.object(sources, "scan_sqlite", cancel_after_first_row):
                        with self.assertRaises(AppError) as error:
                            self.store.sync_sqlite(self.source, cancel=external)
                    self.assertEqual(error.exception.code, "sync_cancelled")
                    self.assert_failed_without_publication("sync_cancelled")
                finally:
                    self.store._sync_cancel.clear()

    def test_both_cancellation_signals_interrupt_partial_local_staging(self) -> None:
        self.make_source(520)
        original = _Stager.add
        for signal in ("explicit", "store"):
            with self.subTest(signal=signal):
                external = threading.Event()
                added = 0

                def cancel_after_batch(stager, table, row):
                    nonlocal added
                    added += 1
                    if added == 513:  # One full batch has been committed to staging.
                        (external if signal == "explicit" else self.store._sync_cancel).set()
                    return original(stager, table, row)

                try:
                    with patch.object(_Stager, "add", cancel_after_batch):
                        with self.assertRaises(AppError) as error:
                            self.store.sync_sqlite(self.source, cancel=external)
                    self.assertEqual(error.exception.code, "sync_cancelled")
                    self.assert_failed_without_publication("sync_cancelled")
                finally:
                    self.store._sync_cancel.clear()

    def test_both_cancellation_signals_interrupt_source_query_progress(self) -> None:
        self.make_source()
        original = sources._validate_schema
        for signal in ("explicit", "store"):
            with self.subTest(signal=signal):
                external = threading.Event()

                def interrupt_query(connection):
                    version = original(connection)
                    (external if signal == "explicit" else self.store._sync_cancel).set()
                    connection.execute(
                        "WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL "
                        "SELECT x+1 FROM n WHERE x<100000) SELECT SUM(x) FROM n"
                    ).fetchone()
                    return version

                try:
                    with patch.object(sources, "_validate_schema", interrupt_query):
                        with self.assertRaises(AppError) as error:
                            self.store.sync_sqlite(self.source, cancel=external)
                    self.assertEqual(error.exception.code, "sync_cancelled")
                    self.assert_failed_without_publication("sync_cancelled")
                finally:
                    self.store._sync_cancel.clear()

    def test_temporary_write_and_replay_failures_close_file_and_remove_staging(self) -> None:
        self.make_source(520)
        original = tempfile.TemporaryFile
        for failure in ("write", "short_write", "replay", "unexpected"):
            with self.subTest(failure=failure):
                opened = []

                class FailingProjection:
                    def __init__(self, *args, **kwargs):
                        self.file = original(*args, **kwargs)
                        opened.append(self.file)

                    def __enter__(self):
                        return self

                    def __exit__(self, *args):
                        self.file.close()

                    def write(self, value):
                        if failure == "write":
                            raise OSError("private temporary path")
                        if failure == "short_write":
                            return self.file.write(value[:-1])
                        return self.file.write(value)

                    def seek(self, *args):
                        return self.file.seek(*args)

                    def __iter__(self):
                        for index, line in enumerate(self.file):
                            if index == 513:  # The first 512 rows have already been staged.
                                if failure == "unexpected":
                                    raise RuntimeError("private temporary path")
                                raise OSError("private temporary path")
                            yield line

                with patch("aha.sync.tempfile.TemporaryFile", FailingProjection):
                    with self.assertRaises(AppError) as error:
                        self.store.sync_sqlite(self.source)
                self.assertEqual(error.exception.code, "sync_failed")
                self.assertEqual(len(opened), 1)
                self.assertTrue(opened[0].closed)
                self.assert_failed_without_publication("sync_failed")
                with closing(sqlite3.connect(self.source, timeout=1)) as connection:
                    connection.execute("UPDATE proxy_request_logs SET output_tokens=11")
                    connection.commit()

    def test_temporary_creation_failure_preserves_local_data(self) -> None:
        self.make_source()
        with patch("aha.sync.tempfile.TemporaryFile", side_effect=OSError("private path")):
            with self.assertRaises(AppError) as error:
                self.store.sync_sqlite(self.source)
        self.assertEqual(error.exception.code, "sync_failed")
        self.assert_failed_without_publication("sync_failed")
        with closing(sqlite3.connect(self.source, timeout=1)) as connection:
            connection.execute("UPDATE proxy_request_logs SET output_tokens=11")
            connection.commit()


if __name__ == "__main__":
    unittest.main()
