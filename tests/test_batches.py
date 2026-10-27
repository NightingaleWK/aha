from __future__ import annotations

import copy
import hashlib
import tempfile
import unittest
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from unittest.mock import patch

from test_storage_helpers import analyze_capture, claim, detail, source_data

from aha.domain import AppError
from aha.storage import Store


def revision_analysis(store: Store, batch_id: str) -> dict:
    history = store.batch_detail(batch_id)
    original = next(row for row in history["revisions"] if row["is_effective"])
    analysis = copy.deepcopy(original["analysis"])
    analysis.update(
        target_batch_id=batch_id,
        claim_revision=store.claim_revision(),
        availability_mode="available",
    )
    return analysis


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

    def test_same_request_and_persistent_http_signature_replay_after_restart(self) -> None:
        result = analyze_capture(self.store)
        first = self.store.create_batch(
            result, claim(), "key-one", request_signature="http-signature"
        )
        original = self.store.download(first["id"], 1)
        repeated = self.store.create_batch(
            result, claim(), "key-one", request_signature="http-signature"
        )
        self.assertEqual((repeated["id"], repeated["version"]), (first["id"], 1))
        self.assertEqual(hashlib.sha256(original[0]).hexdigest(), first["sha256"])
        self.store.close()
        self.store = Store(self.root)
        replayed = self.store.replay_create("key-one", "http-signature")
        self.assertEqual(replayed["id"], first["id"])
        self.assertEqual(self.store.download(first["id"], 1), original)
        self.assert_code(
            "idempotency_conflict", lambda: self.store.replay_create("key-one", "different")
        )
        self.assert_code(
            "idempotency_conflict",
            lambda: self.store.create_batch(result, claim(purpose="changed"), "key-one"),
        )

    def test_only_one_effective_revision_preserves_original_package_and_classification(
        self,
    ) -> None:
        project = self.store.save_project(None, "旧项目", "", ["/work/a"])["project"]
        initial = analyze_capture(self.store, project_id=project["id"])
        first = self.store.create_batch(initial, claim(), "first")
        original = self.store.download(first["id"], 1)
        self.store.save_project(project["id"], "新项目", "", ["/another"])
        revised = self.store.create_batch(
            revision_analysis(self.store, first["id"]),
            claim(purpose="补充用途"),
            "revision",
            first["id"],
            expected_generation=first["generation"],
            expected_active_version=1,
        )
        history = self.store.batch_detail(first["id"])
        self.assertEqual((revised["version"], revised["status"]), (2, "draft"))
        self.assertEqual(history["active_version"], 2)
        self.assertFalse(history["revisions"][0]["is_effective"])
        self.assertTrue(history["revisions"][1]["is_effective"])
        self.assertEqual(history["revisions"][0]["analysis"]["project_name"], "旧项目")
        self.assertEqual(self.store.download(first["id"], 1), original)
        self.assert_code(
            "inactive_revision", lambda: self.store.set_status(first["id"], 1, "reimbursed")
        )
        self.assertEqual(
            {entry["owner"]["version"] for entry in self.store.claim_snapshot()["claims"]}, {2}
        )

    def test_status_withdraw_and_paid_correction_keep_zip_and_claims(self) -> None:
        first = self.store.create_batch(analyze_capture(self.store), claim(), "first")
        original = self.store.download(first["id"], 1)
        submitted = self.store.set_status(first["id"], 1, "submitted", first["generation"])
        self.assert_code(
            "invalid_transition", lambda: self.store.set_status(first["id"], 1, "draft")
        )
        self.assert_code(
            "batch_not_editable",
            lambda: self.store.create_batch(
                revision_analysis(self.store, first["id"]), claim(purpose="x"), "rev", first["id"]
            ),
        )
        withdrawn = self.store.withdraw_batch(
            first["id"], submitted["generation"], "退回修改", "withdraw"
        )
        self.assertEqual(withdrawn["status"], "draft")
        self.assertEqual(len(self.store.claim_snapshot()["claims"]), 1)
        paid = self.store.set_status(first["id"], 1, "reimbursed", withdrawn["generation"])
        self.assertFalse(paid["can_edit"])
        self.assert_code(
            "invalid_transition", lambda: self.store.set_status(first["id"], 1, "draft")
        )
        self.assert_code(
            "batch_not_editable",
            lambda: self.store.create_batch(
                revision_analysis(self.store, first["id"]), claim(purpose="x"), "rev2", first["id"]
            ),
        )
        voided = self.store.void_batch(first["id"], paid["generation"], "已报销填写有误", "void")
        self.assertEqual(voided["lifecycle"], "voided")
        self.assertEqual(voided["status"], "reimbursed")
        self.assertEqual(self.store.download(first["id"], 1), original)
        self.assertEqual(self.store.claim_snapshot()["claims"], [])
        self.assertEqual(
            [event["action"] for event in self.store.batch_detail(first["id"])["claim_history"]],
            ["create", "status", "withdraw", "status", "void"],
        )

    def test_void_retry_and_old_create_retry_never_revive_or_release_new_owner(self) -> None:
        analysis = analyze_capture(self.store)
        first = self.store.create_batch(analysis, claim(), "first", request_signature="http-1")
        self.store.void_batch(first["id"], first["generation"], "取消", "void")
        replacement = self.store.create_batch(analyze_capture(self.store), claim(), "replacement")
        self.store.void_batch(first["id"], first["generation"], "取消", "void")
        replay = self.store.create_batch(analysis, claim(), "first", request_signature="http-1")
        self.assertEqual(replay["lifecycle"], "voided")
        self.assertEqual(self.store.replay_create("first", "http-1")["lifecycle"], "voided")
        self.assertEqual(
            {item["owner"]["batch_id"] for item in self.store.claim_snapshot()["claims"]},
            {replacement["id"]},
        )
        self.assert_code("batch_voided", lambda: self.store.set_status(first["id"], 1, "draft"))
        self.assert_code(
            "batch_voided",
            lambda: self.store.create_batch(
                revision_analysis(self.store, replacement["id"]), claim(), "bad", first["id"]
            ),
        )

    def test_reasons_generation_and_operation_idempotency(self) -> None:
        first = self.store.create_batch(analyze_capture(self.store), claim(), "first")
        self.assert_code(
            "reason_required", lambda: self.store.void_batch(first["id"], 1, " ", "void")
        )
        self.assert_code(
            "stale_batch", lambda: self.store.void_batch(first["id"], 99, "取消", "void")
        )
        self.assert_code(
            "idempotency_conflict", lambda: self.store.void_batch(first["id"], 1, "取消", "first")
        )
        self.store.void_batch(first["id"], 1, "取消", "void")
        self.assert_code(
            "idempotency_conflict",
            lambda: self.store.void_batch(first["id"], 1, "不同原因", "void"),
        )
        self.assert_code(
            "idempotency_conflict",
            lambda: self.store.create_batch(analyze_capture(self.store), claim(), "void"),
        )

    def test_readonly_empty_wrong_subject_and_forged_members_are_rejected(self) -> None:
        data = analyze_capture(self.store)
        readonly = copy.deepcopy(data)
        readonly["availability_mode"] = "all"
        self.assert_code(
            "readonly_analysis", lambda: self.store.create_batch(readonly, claim(), "all")
        )
        empty = analyze_capture(self.store, source_data([]))
        self.assert_code("empty_usage", lambda: self.store.create_batch(empty, claim(), "empty"))
        forged = copy.deepcopy(data)
        forged["members"][0]["key"] = "detail:" + "0" * 64
        self.assert_code(
            "invalid_analysis", lambda: self.store.create_batch(forged, claim(), "forge")
        )
        wrong = copy.deepcopy(data)
        wrong["target_batch_id"] = "another"
        self.assert_code(
            "analysis_target_mismatch", lambda: self.store.create_batch(wrong, claim(), "target")
        )

    def test_new_batch_rejects_stale_classification_and_stale_occupancy(self) -> None:
        data = analyze_capture(self.store)
        self.store.save_project(None, "新项目", "", [])
        self.assert_code("stale_analysis", lambda: self.store.create_batch(data, claim(), "stale"))
        fresh = analyze_capture(self.store)
        saved = self.store.create_batch(fresh, claim(), "first")
        other = analyze_capture(
            self.store, source_data([detail("different", created_at=detail()["created_at"] + 20)])
        )
        self.store.set_status(saved["id"], 1, "submitted")
        self.assert_code(
            "availability_changed", lambda: self.store.create_batch(other, claim(), "old-epoch")
        )

    def test_repeated_source_price_and_project_changes_cannot_reuse_usage(self) -> None:
        first = self.store.create_batch(analyze_capture(self.store), claim(), "first")
        self.store.set_status(first["id"], 1, "reimbursed")
        project = self.store.save_project(None, "改归属", "", [])["project"]["id"]
        self.store.assign([detail(total_cost_usd="99")], project)
        data = analyze_capture(self.store, source_data([detail(total_cost_usd="99")]))
        self.assert_code(
            "usage_claimed", lambda: self.store.create_batch(data, claim(), "duplicate")
        )
        self.assertEqual(self.store.overlaps(data)[0]["certain_count"], 1)
        self.assertEqual(len(self.store.list_batches()), 1)

    def test_same_day_disjoint_requests_can_be_separate_claims(self) -> None:
        self.store.create_batch(analyze_capture(self.store), claim(), "first")
        other = analyze_capture(
            self.store, source_data([detail("other", created_at=detail()["created_at"] + 5)])
        )
        saved = self.store.create_batch(other, claim(), "other")
        self.assertEqual(saved["number"], "AHA-000002")

    def test_same_business_revision_ignores_availability_epoch_and_owner_metadata(self) -> None:
        first = self.store.create_batch(analyze_capture(self.store), claim(), "first")
        self.store.create_batch(
            analyze_capture(
                self.store, source_data([detail("other", created_at=detail()["created_at"] + 5)])
            ),
            claim(),
            "other",
        )
        revision = revision_analysis(self.store, first["id"])
        revision["availability"] = {"claim_revision": 999, "excluded_groups": ["unrelated"]}
        revision["details"][0]["usage_state"] = "claimed"
        revision["details"][0]["usage_owners"] = [{"batch_id": "unrelated"}]
        revision["details"][0]["usage_reason"] = "identity"
        revision["warnings"] = ["当前界面说明已优化"]
        reused = self.store.create_batch(revision, claim(), "same-business", first["id"])
        self.assertEqual(reused["version"], 1)
        self.assertEqual(len(self.store.batch_detail(first["id"])["revisions"]), 1)

    def test_draft_reselection_releases_removed_members_and_failure_keeps_old(self) -> None:
        two = source_data([detail(), detail("r2", created_at=detail()["created_at"] + 5)])
        first = self.store.create_batch(analyze_capture(self.store, two), claim(), "first")
        original = self.store.download(first["id"], 1)
        selected = analyze_capture(self.store, source_data([detail()]), target_batch_id=first["id"])
        with patch.object(
            self.store, "_write_immutable", side_effect=AppError("write_failed", "合成失败")
        ):
            self.assert_code(
                "write_failed",
                lambda: self.store.create_batch(
                    selected, claim(purpose="修改"), "fail", first["id"]
                ),
            )
        self.assertEqual(len(self.store.claim_snapshot()["claims"]), 2)
        self.assertEqual(self.store.batch_detail(first["id"])["active_version"], 1)
        self.assertEqual(self.store.download(first["id"], 1), original)
        changed = self.store.create_batch(selected, claim(purpose="修改"), "change", first["id"])
        self.assertEqual(changed["version"], 2)
        freed = analyze_capture(
            self.store, source_data([detail("r2", created_at=detail()["created_at"] + 5)])
        )
        self.store.create_batch(freed, claim(), "released")

    def test_failed_initial_package_write_has_no_batch_claim_or_retry_entry(self) -> None:
        data = analyze_capture(self.store)
        with patch.object(
            self.store, "_write_immutable", side_effect=AppError("write_failed", "合成失败")
        ):
            self.assert_code(
                "write_failed", lambda: self.store.create_batch(data, claim(), "retry")
            )
        self.assertEqual(self.store.list_batches(), [])
        self.assertEqual(self.store.claim_snapshot()["claims"], [])
        self.assertEqual(self.store.create_batch(data, claim(), "retry")["number"], "AHA-000001")

    def test_package_damage_never_regenerates_or_changes_saved_bytes(self) -> None:
        data = analyze_capture(self.store)
        first = self.store.create_batch(data, claim(), "first", request_signature="http")
        package = next((self.root / "packages").glob("*.zip"))
        package.write_bytes(b"damaged")
        self.assert_code("package_damaged", lambda: self.store.download(first["id"], 1))
        self.assert_code("package_damaged", lambda: self.store.create_batch(data, claim(), "first"))
        self.assert_code("package_damaged", lambda: self.store.replay_create("first", "http"))
        self.assertEqual(package.read_bytes(), b"damaged")
        package.unlink()
        self.assert_code("artifact_missing", lambda: self.store.download(first["id"], 1))

    def test_concurrent_identical_retry_creates_one_draft(self) -> None:
        data = analyze_capture(self.store)
        with ThreadPoolExecutor(max_workers=6) as pool:
            saved = list(
                pool.map(lambda _: self.store.create_batch(data, claim(), "same"), range(12))
            )
        self.assertEqual(len({(item["id"], item["version"]) for item in saved}), 1)
        self.assertEqual(len(self.store.claim_snapshot()["claims"]), 1)
