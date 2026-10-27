from __future__ import annotations

import copy
import hashlib
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from test_storage_helpers import analyze_capture, claim, detail, rollup, source_data

from aha.domain import AppError
from aha.storage import Store


class BatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = Store(self.root)

    def tearDown(self) -> None:
        self.store.close()
        self.temporary.cleanup()

    def test_same_request_reuses_original_version_and_bytes_after_restart(self) -> None:
        result = analyze_capture(self.store)
        first = self.store.create_batch(result, claim(), "key-one")
        raw, filename = self.store.download(first["id"], 1)
        repeated = self.store.create_batch(result, claim(), "key-one")
        self.assertEqual(
            (repeated["id"], repeated["version"], repeated["status"]), (first["id"], 1, "draft")
        )
        self.assertEqual(hashlib.sha256(raw).hexdigest(), first["sha256"])
        self.store.close()
        self.store = Store(self.root)
        self.assertEqual(self.store.download(first["id"], 1), (raw, filename))
        repeated = self.store.create_batch(result, claim(), "key-one")
        self.assertEqual(repeated["id"], first["id"])
        self.assertEqual(len(self.store.batch_detail(first["id"])["revisions"]), 1)
        with self.assertRaises(AppError) as failure:
            self.store.create_batch(result, claim(purpose="changed"), "key-one")
        self.assertEqual(failure.exception.code, "idempotency_conflict")

    def test_new_revision_draft_keeps_old_name_status_analysis_and_original_package(self) -> None:
        project = self.store.save_project(None, "旧项目", "", ["/work/a"])["project"]
        result = analyze_capture(self.store, project_id=project["id"])
        first = self.store.create_batch(result, claim(), "first")
        original = self.store.download(first["id"], 1)
        self.store.set_status(first["id"], 1, "reimbursed")
        self.store.save_project(project["id"], "新项目", "", ["/another"])
        old_analysis = self.store.batch_detail(first["id"])["revisions"][0]["analysis"]
        revised = self.store.create_batch(
            old_analysis, claim(purpose="补充用途"), "revision", first["id"]
        )
        self.assertEqual(
            (revised["id"], revised["version"], revised["status"]), (first["id"], 2, "draft")
        )
        history = self.store.batch_detail(first["id"])
        self.assertEqual(history["latest_version"], 2)
        self.assertEqual(history["revisions"][0]["status"], "reimbursed")
        self.assertEqual(history["revisions"][0]["analysis"]["project_name"], "旧项目")
        self.assertEqual(history["revisions"][1]["analysis"], old_analysis)
        self.assertEqual(self.store.download(first["id"], 1), original)
        self.assertEqual(revised["overlaps"], [])
        self.assertEqual(self.store.list_batches()[0]["status"], "draft")
        self.assertEqual(self.store.list_batches()[0]["latest_version"], 2)

    def test_status_is_manually_correctable_per_version_and_never_changes_zip(self) -> None:
        result = analyze_capture(self.store)
        saved = self.store.create_batch(result, claim(), "state")
        original = self.store.download(saved["id"], 1)
        for status in ("submitted", "reimbursed", "draft"):
            changed = self.store.set_status(saved["id"], 1, status)
            self.assertEqual(changed["status"], status)
            self.assertEqual(self.store.download(saved["id"], 1), original)
        self.assertEqual(len(self.store.batch_detail(saved["id"])["status_history"]), 4)
        with self.assertRaises(AppError):
            self.store.set_status(saved["id"], 1, "paid")

    def test_new_batch_rejects_stale_classification(self) -> None:
        result = analyze_capture(self.store)
        self.store.save_project(None, "新增项目", "", [])
        with self.assertRaises(AppError) as failure:
            self.store.create_batch(result, claim(), "stale")
        self.assertEqual(failure.exception.code, "stale_analysis")
        self.assertEqual(self.store.list_batches(), [])

    def test_package_damage_never_regenerates_or_silently_creates_a_new_revision(self) -> None:
        result = analyze_capture(self.store)
        saved = self.store.create_batch(result, claim(), "damage")
        path = next((self.root / "packages").glob("*.zip"))
        path.write_bytes(b"damaged")
        for action in (
            lambda: self.store.download(saved["id"], 1),
            lambda: self.store.create_batch(result, claim(), "damage"),
        ):
            with self.assertRaises(AppError) as failure:
                action()
            self.assertEqual(failure.exception.code, "package_damaged")
        self.assertEqual(path.read_bytes(), b"damaged")
        self.assertEqual(len(self.store.batch_detail(saved["id"])["revisions"]), 1)
        path.unlink()
        with self.assertRaises(AppError):
            self.store.download(saved["id"], 1)

    def test_failed_package_write_does_not_commit_batch_or_idempotency(self) -> None:
        result = analyze_capture(self.store)
        with patch.object(
            self.store, "_write_immutable", side_effect=AppError("write_failed", "合成失败")
        ):
            with self.assertRaises(AppError):
                self.store.create_batch(result, claim(), "retry-after-failure")
        self.assertEqual(self.store.list_batches(), [])
        saved = self.store.create_batch(result, claim(), "retry-after-failure")
        self.assertEqual(saved["number"], "AHA-000001")

    def test_exact_overlap_ignores_project_and_price_changes_and_distinguishes_status(self) -> None:
        initial = analyze_capture(self.store)
        first = self.store.create_batch(initial, claim(), "batch-a")
        warning = self.store.overlaps(initial)[0]
        self.assertEqual(warning["status"], "draft")
        self.assertIn("草稿", warning["message"])
        self.store.set_status(first["id"], 1, "reimbursed")
        project = self.store.save_project(None, "改归属", "", [])["project"]["id"]
        self.store.assign([detail(total_cost_usd="99")], project)
        changed = analyze_capture(self.store, source_data([detail(total_cost_usd="99")]))
        warning = self.store.overlaps(changed)[0]
        self.assertEqual(warning["status"], "reimbursed")
        self.assertEqual(warning["certain_count"], 1)
        self.assertIn("已报销", warning["message"])
        self.assertIn("detail_identity", warning["types"])
        second = self.store.create_batch(changed, claim(), "batch-b")
        self.assertEqual(second["total_cost_usd"], "99")
        self.assertEqual(second["status"], "draft")
        self.assertTrue(second["overlaps"])

    def test_same_day_disjoint_requests_do_not_imply_duplicate(self) -> None:
        initial = analyze_capture(self.store)
        self.store.create_batch(initial, claim(), "disjoint-first")
        changed = analyze_capture(
            self.store, source_data([detail("other", created_at=detail()["created_at"] + 5)])
        )
        self.assertEqual(self.store.overlaps(changed), [])

    def test_changed_request_key_with_same_semantics_is_only_possible_overlap(self) -> None:
        initial = analyze_capture(self.store)
        self.store.create_batch(initial, claim(), "rebuild-first")
        changed = analyze_capture(self.store, source_data([detail("new-key")]))
        warning = self.store.overlaps(changed)[0]
        self.assertEqual(warning["certain_count"], 0)
        self.assertIn("suspected_rebuild", warning["types"])
        self.assertIn("疑似", warning["message"])

    def test_cross_grain_and_rollup_overlap_are_possible_only_and_exclude_same_batch(self) -> None:
        initial = analyze_capture(self.store)
        first = self.store.create_batch(initial, claim(), "detail-first")
        historical = analyze_capture(self.store, source_data([], [rollup(date="2026-10-26")]))
        warnings = self.store.overlaps(historical)
        self.assertEqual(warnings[0]["certain_count"], 0)
        self.assertIn("cross_grain", warnings[0]["types"])
        self.store.create_batch(historical, claim(), "rollup-first")
        warnings = self.store.overlaps(historical)
        self.assertTrue(any("rollup_scope" in warning["types"] for warning in warnings))
        self.assertTrue(
            all(
                warning["batch_id"] != first["id"]
                for warning in self.store.overlaps(historical, first["id"])
            )
        )
        other_model = copy.deepcopy(historical)
        other_model["members"][0]["model"] = "other-model"
        self.assertEqual(self.store.overlaps(other_model), [])

    def test_concurrent_identical_retry_creates_one_draft(self) -> None:
        result = analyze_capture(self.store)
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(
                pool.map(
                    lambda _: self.store.create_batch(result, claim(), "concurrent"), range(10)
                )
            )
        self.assertEqual(len({item["id"] for item in results}), 1)
        self.assertTrue(all(item["version"] == 1 for item in results))
        self.assertEqual(len(self.store.list_batches()), 1)

    def test_identical_business_content_with_new_preview_and_retry_key_reuses_revision(
        self,
    ) -> None:
        result = analyze_capture(self.store)
        result["analysis_id"] = "first-preview"
        saved = self.store.create_batch(result, claim(), "first-content")
        self.store.set_status(saved["id"], 1, "submitted")
        original = self.store.download(saved["id"], 1)
        same_content = copy.deepcopy(result)
        same_content["analysis_id"] = "another-preview"
        reused = self.store.create_batch(same_content, claim(), "another-key", saved["id"])
        self.assertEqual((reused["version"], reused["status"]), (1, "submitted"))
        self.assertEqual(self.store.download(saved["id"], 1), original)
        self.assertEqual(len(self.store.batch_detail(saved["id"])["revisions"]), 1)
        retry = self.store.create_batch(same_content, claim(), "another-key", saved["id"])
        self.assertEqual(retry["version"], 1)
