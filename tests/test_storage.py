"""Fresh row ledger publication, retained history and failure isolation."""

from __future__ import annotations

import copy
import sqlite3
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from test_sources import database
from test_storage_helpers import claim, detail, metadata, rollup, source_data

from aha.domain import AppError, record_key
from aha.storage import Store
from aha.sync import _Stager


class LedgerStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = Store(self.root)

    def tearDown(self) -> None:
        self.store.close()
        self.temporary.cleanup()

    def query(self, mode: str = "available") -> dict:
        return self.store.analyze("2026-10-01", "2026-10-31", availability_mode=mode)

    def test_repeated_sync_has_one_fact_one_content_and_stable_revision(self) -> None:
        first = self.store.sync_data(source_data(), metadata(), trust="live")
        for _ in range(10):
            again = self.store.sync_data(source_data(), metadata(), trust="live")
            self.assertEqual(again["unchanged_count"], 1)
            self.assertEqual(again["data_revision"], first["data_revision"])
        with self.store.read_connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM usage_records").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM usage_versions").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sync_stage").fetchone()[0], 0)
        self.assertEqual(self.query()["summary"]["total_cost_usd"], "0.1234567")

    def test_live_revision_preserves_old_fact_and_old_preview_expires(self) -> None:
        self.store.sync_data(source_data(), metadata(), trust="live")
        before = self.query()
        result = self.store.sync_data(
            source_data([detail(total_cost_usd="2.000000001")]), metadata(), trust="live"
        )
        self.assertEqual(result["revised_count"], 1)
        self.assertEqual(self.query()["summary"]["total_cost_usd"], "2.000000001")
        with self.assertRaises(AppError) as error:
            self.store.analysis_details(before)
        self.assertEqual(error.exception.code, "analysis_expired")
        with self.store.read_connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM usage_versions").fetchone()[0], 2)

    def test_old_backup_cannot_replace_live_value_by_import_time(self) -> None:
        self.store.sync_data(source_data(), metadata(), trust="live")
        backup = source_data([detail(total_cost_usd="0.01")])
        backup["source"]["name"] = "old.sql"
        self.store.sync_data(backup, metadata())
        cases = self.store.list_reconciliations()
        case = next(item for item in cases if item["type"] == "revision")
        self.assertEqual(case["current_cost_usd"], "0.1234567")
        self.assertEqual(case["candidate_cost_usd"], "0.01")
        self.assertEqual(self.query()["pending_count"], 1)
        self.store.resolve_reconciliation(
            case["id"], "current", "核对活库保存值", case["generation"]
        )
        self.assertEqual(self.query()["summary"]["total_cost_usd"], "0.1234567")

    def test_removed_source_and_restart_keep_local_usage(self) -> None:
        self.store.sync_data(source_data(), metadata())
        self.store.close()
        self.store = Store(self.root)
        with patch("aha.sources.scan_sqlite", side_effect=AssertionError("query must stay local")):
            analysis = self.query()
            self.assertEqual(analysis["summary"]["record_count"], 1)
            self.assertEqual(len(self.store.analysis_details(analysis)["rows"]), 1)
            self.assertEqual(self.store.ledger_status()["counts"]["detail_count"], 1)

    def test_invalid_input_and_publish_failure_keep_previous_success(self) -> None:
        self.store.sync_data(source_data(), metadata())
        before = self.store.ledger_status()
        bad = copy.deepcopy(source_data())
        bad["details"][0]["input_tokens"] = -1
        with self.assertRaises(AppError):
            self.store.sync_data(bad)
        with patch("aha.ledger.refresh_availability", side_effect=AppError("injected", "fail")):
            with self.assertRaises(AppError):
                self.store.sync_data(source_data([detail("new-id")]), trust="live")
        after = self.store.ledger_status()
        self.assertEqual(after["data_revision"], before["data_revision"])
        self.assertEqual(after["last_successful_sync_at"], before["last_successful_sync_at"])
        self.assertEqual(after["counts"], before["counts"])
        self.assertEqual(after["last_attempt"]["state"], "failed")
        with self.store.read_connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sync_stage").fetchone()[0], 0)

    def test_duplicate_source_identity_is_rejected_not_silently_dropped(self) -> None:
        data = {"schema_version": 23, "details": [detail(), detail()], "source": {"name": "bad"}}
        with self.assertRaises(AppError) as error:
            self.store.sync_data(data)
        self.assertEqual(error.exception.code, "duplicate_key")
        self.assertEqual(self.store.ledger_status()["counts"]["detail_count"], 0)

    def test_metadata_is_projected_not_conversation_or_private_config(self) -> None:
        data = source_data()
        data["credentials"] = "SECRET"
        data["details"][0]["body"] = "SECRET"
        meta = metadata()
        meta["sessions"]["s1"]["body"] = "SECRET"
        self.store.sync_data(data, meta)
        with self.store.read_connection() as db:
            self.assertNotIn(
                "SECRET", db.execute("SELECT payload_json FROM usage_versions").fetchone()[0]
            )
            self.assertNotIn(
                "SECRET",
                db.execute("SELECT payload_json FROM session_metadata_versions").fetchone()[0],
            )

    def test_consistent_source_cleanup_does_not_delete_local_rows(self) -> None:
        self.store.sync_data(source_data(), trust="live")
        self.store.sync_data(source_data([], [rollup(date="2026-10-26")]), trust="live")
        self.assertEqual(self.store.ledger_status()["counts"]["detail_count"], 1)
        case = self.store.list_reconciliations()[0]
        self.assertEqual(case["type"], "coverage")
        self.assertFalse(self.query()["summary_complete"])
        self.assertEqual(self.query()["summary"]["record_count"], 0)
        self.store.resolve_reconciliation(
            case["id"], "detail", "仅采用已留明细，汇总另作核对", case["generation"]
        )
        self.assertEqual(self.query()["summary"]["record_count"], 1)

    def test_reader_does_not_wait_for_python_writer_lock(self) -> None:
        self.store.sync_data(source_data(), trust="live")
        entered, release = threading.Event(), threading.Event()

        def writer() -> None:
            with self.store._transaction():
                self.store._db.execute("UPDATE settings SET value=value WHERE key='revision'")
                entered.set()
                release.wait(2)

        thread = threading.Thread(target=writer)
        thread.start()
        self.assertTrue(entered.wait(1))
        try:
            self.assertEqual(self.query()["summary"]["record_count"], 1)
        finally:
            release.set()
            thread.join(3)

    def test_startup_identity_is_once_even_after_failed_or_completed_attempt(self) -> None:
        first = self.store.sync_data(source_data(), trigger="startup", startup_id="launch-1")
        second = self.store.sync_data(source_data(), trigger="startup", startup_id="launch-1")
        self.assertEqual(first["run_id"], second["run_id"])
        with self.store.read_connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sync_runs").fetchone()[0], 1)

    def test_repeated_pending_backup_does_not_create_more_versions(self) -> None:
        self.store.sync_data(source_data(), trust="live")
        old = source_data([detail(total_cost_usd="0.001")])
        old["source"]["name"] = "old.sql"
        self.store.sync_data(old)
        revision = self.store.revisions()["data_revision"]
        self.store.sync_data(old)
        self.assertEqual(self.store.revisions()["data_revision"], revision)
        with self.store.read_connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM usage_versions").fetchone()[0], 2)
            count = db.execute("SELECT COUNT(*) FROM reconciliation_cases").fetchone()[0]
            self.assertEqual(count, 1)

    def test_empty_rebuild_observation_keeps_rows_and_requires_confirmation(self) -> None:
        self.store.sync_data(source_data(), trust="live")
        previous_success = self.store.ledger_status()["last_successful_sync_at"]
        run = self.store.sync_data(source_data([]), trust="live")
        self.assertEqual(run["state"], "needs_review")
        self.assertEqual(self.store.ledger_status()["last_successful_sync_at"], previous_success)
        self.assertEqual(self.store.ledger_status()["counts"]["detail_count"], 1)
        case = self.store.list_reconciliations()[0]
        self.assertEqual(case["type"], "source")
        self.assertEqual(self.query()["pending_count"], 1)
        self.store.resolve_reconciliation(
            case["id"], "current", "已核对，保留本地既有事实", case["generation"]
        )
        self.assertEqual(self.query()["summary"]["record_count"], 1)
        recovered = self.store.sync_data(source_data([]), trust="live")
        self.assertEqual(recovered["state"], "completed")
        self.assertEqual(self.store.list_reconciliations(), [])

    def test_rebuilt_identity_can_be_confirmed_alias_without_double_count(self) -> None:
        self.store.sync_data(source_data(), trust="live")
        rebuilt = source_data([detail("rebuilt-key")])
        rebuilt["source"]["name"] = "another.sql"
        self.store.sync_data(rebuilt)
        case = next(c for c in self.store.list_reconciliations() if c["type"] == "identity")
        self.assertIn("current_summary", case)
        self.assertIn("candidate_summary", case)
        self.store.resolve_reconciliation(
            case["id"], "same", "已核对会话重建，属于同一消费", case["generation"]
        )
        self.assertEqual(self.query()["summary"]["record_count"], 1)
        before = self.store.revisions()
        again = self.store.sync_data(rebuilt)
        self.assertEqual(again["unchanged_count"], 1)
        self.assertEqual(self.store.list_reconciliations(), [])
        self.assertEqual(self.store.revisions(), before)

    def test_alias_cost_revision_keeps_canonical_identity_and_can_be_frozen(self) -> None:
        self.store.sync_data(source_data(), trust="live")
        rebuilt = source_data([detail("rebuilt-key")])
        rebuilt["source"]["name"] = "another.sql"
        self.store.sync_data(rebuilt)
        case = self.store.list_reconciliations()[0]
        self.store.resolve_reconciliation(case["id"], "same", "已核对为同一消费")
        rebuilt = copy.deepcopy(rebuilt)
        rebuilt["details"][0]["total_cost_usd"] = "2.000000001"
        self.store.sync_data(rebuilt)
        revision = self.store.list_reconciliations()[0]
        self.assertEqual(revision["type"], "revision")
        self.store.resolve_reconciliation(revision["id"], "candidate", "已核对修订金额")
        analysis = self.query()
        self.assertEqual(analysis["summary"]["record_count"], 1)
        self.assertEqual(analysis["summary"]["total_cost_usd"], "2.000000001")
        row = self.store.analysis_details(analysis)["rows"][0]
        self.assertEqual(row["request_id"], "rebuilt-key")
        self.assertEqual(row["record_key"], record_key(detail()))
        saved = self.store.create_batch(analysis, claim(), "alias-corrected")
        self.assertEqual(saved["version"], 1)
        self.assertEqual(self.query()["summary"]["record_count"], 0)
        self.assertEqual(self.store.canonical_record_key(record_key(detail("rebuilt-key"))),
                         record_key(detail()))

    def test_same_source_equal_size_rebuild_is_not_counted_as_new_consumption(self) -> None:
        self.store.sync_data(source_data(), source_id="same-live", trust="live")
        rebuilt = source_data([detail("new-key")])
        self.store.sync_data(rebuilt, source_id="same-live", trust="live")
        self.assertEqual(self.query()["summary"]["record_count"], 1)
        self.assertEqual(self.query()["pending_count"], 1)
        case = self.store.list_reconciliations()[0]
        self.assertEqual(case["type"], "identity")
        self.store.resolve_reconciliation(case["id"], "same", "核对同路径重建")
        rebuilt["details"][0]["total_cost_usd"] = "2.000000001"
        revised = self.store.sync_data(rebuilt, source_id="same-live", trust="live")
        self.assertEqual(revised["revised_count"], 1)
        self.assertEqual(self.query()["summary"]["record_count"], 1)
        self.assertEqual(self.query()["summary"]["total_cost_usd"], "2.000000001")
        self.assertEqual(self.store.list_reconciliations(), [])

    def test_same_source_coexisting_same_second_requests_stay_independent(self) -> None:
        self.store.sync_data(source_data(), source_id="same-live", trust="live")
        self.store.sync_data(
            source_data([detail(), detail("second")]), source_id="same-live", trust="live"
        )
        self.assertEqual(self.query()["summary"]["record_count"], 2)
        self.assertEqual(self.query()["pending_count"], 0)
        self.assertEqual(self.store.list_reconciliations(), [])

    def test_rollup_request_count_regression_keeps_old_fact_until_source_confirmation(self) -> None:
        self.store.sync_data(source_data([], [rollup(request_count=100)]), trust="live")
        before = self.store.ledger_status()["last_successful_sync_at"]
        regressed = source_data([], [rollup(request_count=10)])
        result = self.store.sync_data(regressed, trust="live")
        self.assertEqual(result["state"], "needs_review")
        self.assertEqual(self.store.ledger_status()["last_successful_sync_at"], before)
        self.assertEqual(self.store._db.execute(
            "SELECT request_count FROM usage_records WHERE kind='rollup'"
        ).fetchone()[0], "100")
        cases = self.store.list_reconciliations()
        self.assertEqual({case["type"] for case in cases}, {"source", "revision"})
        source = next(case for case in cases if case["type"] == "source")
        self.store.resolve_reconciliation(source["id"], "current", "已核对来源重建基线")
        repeated = self.store.sync_data(regressed, trust="live")
        self.assertEqual(repeated["state"], "completed")
        self.assertEqual(self.query()["summary"]["record_count"], 10)
        self.assertEqual(self.store.list_reconciliations(), [])

    def test_rollup_row_loss_is_reviewed_even_when_detail_count_is_unchanged(self) -> None:
        self.store.sync_data(source_data([detail()], [rollup(), rollup(date="2026-10-23")]),
                             trust="live")
        before = self.store.ledger_status()["last_successful_sync_at"]
        reduced = source_data([detail()], [rollup()])
        result = self.store.sync_data(reduced, trust="live")
        self.assertEqual(result["state"], "needs_review")
        self.assertEqual(self.store.ledger_status()["last_successful_sync_at"], before)
        self.assertEqual(self.store._db.execute(
            "SELECT COUNT(*) FROM usage_records WHERE kind='rollup'"
        ).fetchone()[0], 2)
        source = next(
            case for case in self.store.list_reconciliations() if case["type"] == "source"
        )
        self.store.resolve_reconciliation(source["id"], "current", "确认来源窗口变化，保留历史")
        self.assertEqual(self.store.sync_data(reduced, trust="live")["state"], "completed")
        self.assertEqual(self.query()["summary"]["record_count"], 15)

    def test_rollup_cost_correction_without_count_regression_remains_normal_revision(self) -> None:
        self.store.sync_data(source_data([detail()], [rollup(total_cost_usd="10")]), trust="live")
        result = self.store.sync_data(source_data([detail()], [rollup(total_cost_usd="2")]),
                                      trust="live")
        self.assertEqual(result["state"], "completed")
        self.assertEqual(result["revised_count"], 1)
        self.assertEqual(self.store.list_reconciliations(), [])
        self.assertEqual(self.store._db.execute(
            "SELECT total_cost_usd FROM usage_records WHERE kind='rollup'"
        ).fetchone()[0], "2")

    def test_source_read_lock_is_not_held_while_waiting_indefinitely_for_local_writer(self) -> None:
        self.store.sync_data(source_data(), trust="live")
        before = self.store.ledger_status()
        path = self.root / "source.db"
        source = database(path, [detail(str(n)) for n in range(600)])
        source.execute("PRAGMA busy_timeout=1000")
        try:
            for cancelled in (False, True):
                with self.subTest(cancelled=cancelled):
                    flushing, locked, release = (
                        threading.Event(), threading.Event(), threading.Event()
                    )
                    cancel = threading.Event()
                    original_flush = _Stager.flush
                    flush_seconds = []

                    def hold_writer():
                        self.assertTrue(flushing.wait(5))
                        with self.store._lock:
                            locked.set()
                            release.wait(5)

                    def blocked_flush(stager):
                        flushing.set()
                        self.assertTrue(locked.wait(5))
                        started = time.perf_counter()
                        try:
                            return original_flush(stager)
                        finally:
                            flush_seconds.append(time.perf_counter() - started)

                    with ThreadPoolExecutor(max_workers=2) as pool:
                        holder = pool.submit(hold_writer)
                        with patch("aha.sync._Stager.flush", blocked_flush):
                            sync = pool.submit(self.store.sync_sqlite, path, cancel=cancel)
                            try:
                                self.assertTrue(locked.wait(5))
                                if cancelled:
                                    cancel.set()
                                source.execute("UPDATE proxy_request_logs SET output_tokens=11")
                                source.commit()
                            finally:
                                release.set()
                            with self.assertRaises(AppError) as error:
                                sync.result(timeout=5)
                            self.assertEqual(error.exception.code,
                                             "sync_cancelled" if cancelled else "store_busy")
                        holder.result(timeout=5)
                    self.assertLess(max(flush_seconds), 1.0)
                    self.assertEqual(self.store.ledger_status()["last_successful_sync_at"],
                                     before["last_successful_sync_at"])
                    self.assertEqual(self.store.ledger_status()["counts"], before["counts"])
        finally:
            source.close()

    def test_source_staging_sqlite_busy_wait_is_bounded_and_restores_timeout(self) -> None:
        self.store.sync_data(source_data(), trust="live")
        before = self.store.ledger_status()
        path = self.root / "source.db"
        source = database(path, [detail(str(n)) for n in range(600)])
        source.execute("PRAGMA busy_timeout=1000")
        flushing, locked, release = threading.Event(), threading.Event(), threading.Event()
        original_flush = _Stager.flush
        flush_seconds = []

        def external_writer():
            self.assertTrue(flushing.wait(5))
            connection = sqlite3.connect(self.root / "aha.sqlite3", isolation_level=None)
            try:
                connection.execute("BEGIN IMMEDIATE")
                locked.set()
                release.wait(5)
                connection.execute("ROLLBACK")
            finally:
                connection.close()

        def blocked_flush(stager):
            flushing.set()
            self.assertTrue(locked.wait(5))
            started = time.perf_counter()
            try:
                return original_flush(stager)
            finally:
                flush_seconds.append(time.perf_counter() - started)

        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                writer = pool.submit(external_writer)
                with patch("aha.sync._Stager.flush", blocked_flush):
                    sync = pool.submit(self.store.sync_sqlite, path)
                    try:
                        self.assertTrue(locked.wait(5))
                        source.execute("UPDATE proxy_request_logs SET output_tokens=11")
                        source.commit()
                    finally:
                        release.set()
                    with self.assertRaises(AppError) as error:
                        sync.result(timeout=5)
                    self.assertEqual(error.exception.code, "store_busy")
                writer.result(timeout=5)
            self.assertLess(max(flush_seconds), 1.0)
            self.assertEqual(self.store._db.execute("PRAGMA busy_timeout").fetchone()[0], 5000)
            self.assertEqual(self.store.ledger_status()["last_successful_sync_at"],
                             before["last_successful_sync_at"])
            self.assertEqual(self.store.ledger_status()["counts"], before["counts"])
        finally:
            source.close()

    def test_same_source_backup_rebuild_alias_revision_keeps_original_claim(self) -> None:
        self.store.sync_data(source_data(), source_id="same-source", trust="live")
        saved = self.store.create_batch(self.query(), claim(), "before-rebuild")
        path, _ = self.store.download(saved["id"], 1)
        original = path.read_bytes()
        rebuilt = source_data([detail("backup-rebuilt")])
        self.store.sync_data(rebuilt, source_id="same-source", trust="backup")
        identity = self.store.list_reconciliations()[0]
        self.store.resolve_reconciliation(identity["id"], "same", "确认备份重建")
        rebuilt["details"][0]["total_cost_usd"] = "3.000000001"
        self.store.sync_data(rebuilt, source_id="same-source", trust="backup")
        revision = self.store.list_reconciliations()[0]
        self.assertEqual(revision["type"], "revision")
        self.store.resolve_reconciliation(revision["id"], "candidate", "确认补价")
        self.assertEqual(self.query()["summary"]["record_count"], 0)
        self.assertEqual(self.query("all")["summary"]["record_count"], 1)
        self.assertEqual(self.query("all")["summary"]["total_cost_usd"], "3.000000001")
        self.assertEqual(self.store.download(saved["id"], 1)[0].read_bytes(), original)

    def test_failed_or_cancelled_rebuild_does_not_publish_identity_candidates(self) -> None:
        self.store.sync_data(source_data(), source_id="same-live", trust="live")
        before = self.store.ledger_status()
        rebuilt = source_data([detail("new-key")])
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaises(AppError):
            self.store.sync_data(rebuilt, source_id="same-live", trust="live", cancel=cancelled)
        with patch("aha.ledger.refresh_availability", side_effect=AppError("injected", "fail")):
            with self.assertRaises(AppError):
                self.store.sync_data(rebuilt, source_id="same-live", trust="live")
        after = self.store.ledger_status()
        self.assertEqual(self.store.list_reconciliations(), [])
        self.assertEqual(after["counts"], before["counts"])
        self.assertEqual(after["last_successful_sync_at"], before["last_successful_sync_at"])

    def test_alias_revision_keeps_original_claim_and_package(self) -> None:
        self.store.sync_data(source_data(), trust="live")
        saved = self.store.create_batch(self.query(), claim(), "original")
        package, _ = self.store.download(saved["batch_id"], saved["version"])
        original_package = package.read_bytes()
        rebuilt = source_data([detail("rebuilt-key", total_cost_usd="3")])
        rebuilt["source"]["name"] = "another.sql"
        self.store.sync_data(rebuilt)
        identity = next(c for c in self.store.list_reconciliations() if c["type"] == "identity")
        self.store.resolve_reconciliation(identity["id"], "same", "同一消费重建")
        revision = next(c for c in self.store.list_reconciliations() if c["type"] == "revision")
        self.store.resolve_reconciliation(revision["id"], "candidate", "确认修订费用")
        self.assertEqual(self.query()["summary"]["record_count"], 0)
        self.assertEqual(self.query("all")["summary"]["total_cost_usd"], "3")
        with self.store.read_connection() as db:
            keys = [r[0] for r in db.execute("SELECT record_key FROM usage_claims")]
        self.assertEqual(keys, [record_key(detail())])
        retained_package = self.store.download(saved["batch_id"], 1)[0].read_bytes()
        self.assertEqual(retained_package, original_package)

    def test_changed_source_observation_invalidates_old_case_generation(self) -> None:
        original = [detail(str(i), created_at=1792947600 + i) for i in range(4)]
        self.store.sync_data(source_data(original), trust="live")
        self.store.sync_data(source_data(original[:1]), trust="live")
        first = self.store.list_reconciliations()[0]
        self.store.sync_data(source_data([]), trust="live")
        second = self.store.list_reconciliations()[0]
        self.assertGreater(second["generation"], first["generation"])
        with self.assertRaises(AppError) as error:
            self.store.resolve_reconciliation(
                first["id"], "current", "旧观察不应提交", first["generation"]
            )
        self.assertEqual(error.exception.code, "stale_case")

    def test_failed_startup_is_not_silently_retried_by_page_refresh(self) -> None:
        invalid = copy.deepcopy(source_data())
        invalid["details"][0]["input_tokens"] = -1
        with self.assertRaises(AppError):
            self.store.sync_data(invalid, trigger="startup", startup_id="failed-launch")
        result = self.store.sync_data(
            source_data(), trigger="startup", startup_id="failed-launch"
        )
        self.assertEqual(result["state"], "failed")
        self.assertEqual(self.store.ledger_status()["counts"]["detail_count"], 0)
