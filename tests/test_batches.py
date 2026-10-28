from __future__ import annotations

import copy
import hashlib
import tempfile
import threading
import unittest
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from unittest.mock import patch

from billing_fixtures import frozen_analysis, seed_analysis
from test_storage_helpers import claim, detail, metadata, source_data

from aha import batches
from aha.domain import AppError
from aha.storage import Store


def revision_analysis(store: Store, batch_id: str) -> dict[str, Any]:
    return frozen_analysis(store, batch_id)


class BatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = Store(self.root)

    def tearDown(self) -> None:
        self.store.close()
        self.temporary.cleanup()

    def assert_code(self, expected: str, callback: Callable[[], Any]) -> None:
        with self.assertRaises(AppError) as failure:
            callback()
        self.assertEqual(failure.exception.code, expected)

    def claim_count(self) -> int:
        return self.store._db.execute("SELECT COUNT(*) FROM usage_claims").fetchone()[0]

    def test_persistent_request_replay_and_conflicting_payload(self) -> None:
        analysis = seed_analysis(self.store)
        first = self.store.create_batch(analysis, claim(), "one", request_signature="request")
        path, _ = self.store.download(first["id"], 1)
        original = path.read_bytes()
        self.assertEqual(hashlib.sha256(original).hexdigest(), first["sha256"])
        self.store.close()
        self.store = Store(self.root)
        replayed = self.store.replay_create("one", "request")
        self.assertEqual((replayed["id"], replayed["version"]), (first["id"], 1))
        self.assertEqual(path.read_bytes(), original)
        self.assert_code(
            "idempotency_conflict", lambda: self.store.replay_create("one", "different")
        )
        self.assert_code(
            "idempotency_conflict",
            lambda: self.store.create_batch(analysis, claim(purpose="changed"), "one"),
        )
        self.assertEqual(self.claim_count(), 1)

    def test_nested_data_directory_uses_short_immutable_package_path(self) -> None:
        self.store.close()
        padding = max(1, 170 - len(str(self.root)) - 6)
        self.root = self.root / ("data-" + "x" * padding)
        self.store = Store(self.root)
        saved = self.store.create_batch(seed_analysis(self.store), claim(), "nested")
        path, filename = self.store.download(saved["id"], 1)
        self.assertLessEqual(len(path.name), 40)
        self.assertTrue(filename.endswith("_AHA-000001_v1.zip"))
        original = path.read_bytes()
        self.store.close()
        self.store = Store(self.root)
        reopened, reopened_name = self.store.download(saved["id"], 1)
        self.assertEqual((reopened.read_bytes(), reopened_name), (original, filename))

    def test_frozen_revision_preserves_old_classification_and_package(self) -> None:
        project = self.store.save_project(None, "旧项目", "", ["/work/a"])["project"]
        first = self.store.create_batch(
            seed_analysis(self.store, project_id=project["id"]), claim(), "first"
        )
        old_path, _ = self.store.download(first["id"], 1)
        original = old_path.read_bytes()
        self.store.save_project(project["id"], "新项目", "", ["/another"])
        update = self.store.create_batch(
            frozen_analysis(self.store, first["id"]),
            claim(purpose="补充用途"),
            "revision",
            first["id"],
            expected_generation=first["generation"],
            expected_active_version=1,
        )
        history = self.store.batch_detail(first["id"])
        self.assertEqual((update["version"], history["active_version"]), (2, 2))
        self.assertEqual(history["revisions"][1]["analysis"]["project_name"], "旧项目")
        self.assertFalse(history["revisions"][0]["is_effective"])
        self.assertTrue(history["revisions"][1]["is_effective"])
        self.assertEqual(old_path.read_bytes(), original)
        self.assertEqual(self.claim_count(), 1)
        self.assert_code(
            "inactive_revision", lambda: self.store.set_status(first["id"], 1, "reimbursed")
        )

    def test_cost_revision_keeps_original_zip_and_allows_frozen_purpose_change(self) -> None:
        first = self.store.create_batch(seed_analysis(self.store), claim(), "first")
        path, _ = self.store.download(first["id"], 1)
        original = path.read_bytes()
        self.store.sync_data(
            source_data([detail(total_cost_usd="9.9900000001")]), metadata(), trust="live"
        )
        all_usage = self.store.analyze("2026-10-26", "2026-10-26", availability_mode="all")
        self.assertEqual(all_usage["summary"]["total_cost_usd"], "9.9900000001")
        history = self.store.batch_detail(first["id"])
        self.assertEqual(history["current_difference_count"], 1)
        self.assertEqual(history["summary"]["total_cost_usd"], "0.1234567")
        revised = self.store.create_batch(
            frozen_analysis(self.store, first["id"]),
            claim(purpose="仍按原依据"),
            "revision",
            first["id"],
            expected_generation=first["generation"],
            expected_active_version=1,
        )
        self.assertEqual(revised["summary"]["total_cost_usd"], "0.1234567")
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(self.claim_count(), 1)

    def test_confirmed_alias_cost_revision_can_be_frozen_without_changing_old_package(self) -> None:
        self.store.sync_data(
            source_data(), metadata(), source_id="history-original", trust="backup"
        )
        first = self.store.create_batch(
            self.store.analyze("2026-10-26", "2026-10-26"), claim(), "first"
        )
        old_path, _ = self.store.download(first["id"], 1)
        old_bytes = old_path.read_bytes()
        rebuilt = source_data([detail("rebuilt-key")])
        self.store.sync_data(rebuilt, metadata(), source_id="rebuilt", trust="backup")
        case = next(c for c in self.store.list_reconciliations() if c["type"] == "identity")
        self.store.resolve_reconciliation(
            case["id"], "same", "已核对为会话重建", case["generation"]
        )
        self.store.sync_data(
            source_data([detail("rebuilt-key", total_cost_usd="9.9900000001")]),
            metadata(),
            source_id="rebuilt",
            trust="live",
        )
        query = self.store.analyze("2026-10-26", "2026-10-26", availability_mode="all")
        self.assertEqual(query["summary"]["record_count"], 1)
        self.assertEqual(query["summary"]["total_cost_usd"], "9.9900000001")
        history = self.store.batch_detail(first["id"])
        self.assertEqual(history["current_difference_count"], 1)
        revised = self.store.create_batch(
            frozen_analysis(self.store, first["id"]),
            claim(purpose="保留原冻结事实"),
            "frozen-revision",
            first["id"],
            expected_generation=first["generation"],
            expected_active_version=1,
        )
        self.assertEqual(revised["summary"]["total_cost_usd"], "0.1234567")
        self.assertEqual(old_path.read_bytes(), old_bytes)
        self.store.void_batch(revised["id"], revised["generation"], "改用新事实", "void")
        latest = self.store.create_batch(
            self.store.analyze("2026-10-26", "2026-10-26"), claim(), "latest"
        )
        self.assertEqual(latest["summary"]["total_cost_usd"], "9.9900000001")
        self.assertEqual(self.claim_count(), 1)

    def test_business_no_change_reuses_effective_version_with_a_new_retry_key(self) -> None:
        first = self.store.create_batch(seed_analysis(self.store), claim(), "first")
        reused = self.store.create_batch(
            frozen_analysis(self.store, first["id"]),
            claim(),
            "new-key",
            first["id"],
            expected_generation=first["generation"],
            expected_active_version=1,
        )
        self.assertEqual((reused["version"], reused["sha256"]), (1, first["sha256"]))
        self.assertEqual(len(self.store.batch_detail(first["id"])["revisions"]), 1)
        self.assertEqual(
            self.store._db.execute("SELECT COUNT(*) FROM idempotency").fetchone()[0], 2
        )

    def test_current_revision_can_change_selection_and_release_only_removed_members(self) -> None:
        second = detail("r2", created_at=detail()["created_at"] + 86400)
        first = self.store.create_batch(
            seed_analysis(self.store, source_data([detail(), second])), claim(), "first"
        )
        replacement = self.store.analyze(
            "2026-10-26",
            "2026-10-26",
            target_batch_id=first["id"],
            expected_generation=first["generation"],
            expected_active_version=1,
        )
        revised = self.store.create_batch(
            replacement,
            claim(purpose="只用第一天"),
            "revision",
            first["id"],
            expected_generation=first["generation"],
            expected_active_version=1,
        )
        self.assertEqual((revised["version"], self.claim_count()), (2, 1))
        self.assertEqual(
            self.store.analyze("2026-10-27", "2026-10-27")["summary"]["record_count"], 1
        )

    def test_status_withdraw_paid_void_and_old_void_replay_preserve_new_owner(self) -> None:
        initial = seed_analysis(self.store)
        first = self.store.create_batch(initial, claim(), "first")
        path, _ = self.store.download(first["id"], 1)
        original = path.read_bytes()
        submitted = self.store.set_status(first["id"], 1, "submitted", first["generation"])
        self.assert_code(
            "invalid_transition", lambda: self.store.set_status(first["id"], 1, "draft")
        )
        self.assert_code(
            "reason_required",
            lambda: self.store.withdraw_batch(first["id"], submitted["generation"], "", "withdraw"),
        )
        withdrawn = self.store.withdraw_batch(
            first["id"], submitted["generation"], "退回", "withdraw"
        )
        self.assertEqual((withdrawn["status"], self.claim_count()), ("draft", 1))
        paid = self.store.set_status(first["id"], 1, "reimbursed", withdrawn["generation"])
        self.assertFalse(paid["can_edit"])
        voided = self.store.void_batch(first["id"], paid["generation"], "纠正记录", "void")
        self.assertEqual((voided["lifecycle"], self.claim_count()), ("voided", 0))
        fresh = self.store.create_batch(
            self.store.analyze("2026-10-26", "2026-10-26"), claim(), "new"
        )
        self.store.void_batch(first["id"], paid["generation"], "纠正记录", "void")
        replay = self.store.create_batch(initial, claim(), "first")
        self.assertEqual(replay["lifecycle"], "voided")
        self.assertEqual(self.claim_count(), 1)
        self.assertEqual(
            self.store._db.execute("SELECT batch_id FROM usage_claims").fetchone()[0], fresh["id"]
        )
        self.assertEqual(path.read_bytes(), original)
        self.assert_code(
            "batch_voided", lambda: self.store.set_status(first["id"], 1, "reimbursed")
        )

    def test_empty_all_forged_summary_and_cross_target_are_rejected(self) -> None:
        result = seed_analysis(self.store)
        all_rows = self.store.analyze("2026-10-26", "2026-10-26", availability_mode="all")
        self.assert_code(
            "readonly_analysis", lambda: self.store.create_batch(all_rows, claim(), "all")
        )
        empty = self.store.analyze("2020-01-01", "2020-01-01")
        self.assert_code("empty_usage", lambda: self.store.create_batch(empty, claim(), "empty"))
        forged = copy.deepcopy(result)
        forged["summary"]["record_count"] = 2
        self.assert_code(
            "selection_changed", lambda: self.store.create_batch(forged, claim(), "forged")
        )
        spoof = copy.deepcopy(result)
        spoof["target_batch_id"] = "other"
        self.assert_code(
            "analysis_target_mismatch", lambda: self.store.create_batch(spoof, claim(), "spoof")
        )
        self.assertEqual(self.store.list_batches(), [])
        self.assertEqual(self.claim_count(), 0)

    def test_stale_preview_fails_without_silently_shrinking_selection(self) -> None:
        preview = seed_analysis(self.store)
        first = self.store.create_batch(preview, claim(), "first")
        self.assert_code(
            "availability_changed", lambda: self.store.create_batch(preview, claim(), "stale")
        )
        self.assertEqual((len(self.store.list_batches()), self.claim_count()), (1, 1))
        self.assertEqual(self.store.list_batches()[0]["id"], first["id"])

    def test_failed_package_build_keeps_no_batch_claim_or_registered_material(self) -> None:
        result = seed_analysis(self.store)
        with patch(
            "aha.batches.build_evidence",
            side_effect=AppError("package_write_failed", "合成失败", 500),
        ):
            self.assert_code(
                "package_write_failed", lambda: self.store.create_batch(result, claim(), "failed")
            )
        self.assertEqual(self.store.list_batches(), [])
        self.assertEqual(self.claim_count(), 0)
        self.assertEqual(list((self.root / "packages").iterdir()), [])
        self.assertEqual(list((self.root / "temporary").iterdir()), [])

    def test_queries_continue_while_package_builds_and_changed_basis_aborts_commit(self) -> None:
        preview = seed_analysis(self.store)
        reached, release = threading.Event(), threading.Event()
        original = batches.build_evidence

        def delayed(*args: Any, **kwargs: Any) -> Any:
            reached.set()
            self.assertTrue(release.wait(10))
            return original(*args, **kwargs)

        with patch("aha.batches.build_evidence", side_effect=delayed), ThreadPoolExecutor() as pool:
            pending = pool.submit(self.store.create_batch, preview, claim(), "pending")
            try:
                self.assertTrue(reached.wait(10))
                self.assertEqual(
                    self.store.analyze("2026-10-26", "2026-10-26")["summary"]["record_count"], 1
                )
                self.store.sync_data(
                    source_data([detail(total_cost_usd="2")]), metadata(), trust="live"
                )
            finally:
                release.set()
            with self.assertRaises(AppError) as failure:
                pending.result(timeout=10)
            self.assertIn(failure.exception.code, {"analysis_expired", "stale_analysis"})
        self.assertEqual(self.store.list_batches(), [])
        self.assertEqual(self.claim_count(), 0)
        self.assertEqual(list((self.root / "packages").iterdir()), [])

    def test_corrupt_package_is_reported_and_not_recreated(self) -> None:
        first = self.store.create_batch(seed_analysis(self.store), claim(), "first")
        path, _ = self.store.download(first["id"], 1)
        path.write_bytes(b"corrupt")
        self.assert_code("package_damaged", lambda: self.store.download(first["id"], 1))
        self.assertEqual(path.read_bytes(), b"corrupt")

    def test_invalid_lifecycle_generation_and_request_key_fail_closed(self) -> None:
        first = self.store.create_batch(seed_analysis(self.store), claim(), "first")
        self.assert_code(
            "stale_batch", lambda: self.store.set_status(first["id"], 1, "submitted", 99)
        )
        self.assert_code(
            "reason_required",
            lambda: self.store.void_batch(first["id"], first["generation"], "", "void"),
        )
        self.assert_code(
            "invalid_idempotency_key", lambda: self.store.create_batch({}, claim(), "")
        )
        self.assertEqual(self.claim_count(), 1)
