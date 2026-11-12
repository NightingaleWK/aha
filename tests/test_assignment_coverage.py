"""Project totals, unassigned work and frozen evidence share an exact selection."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path

from billing_fixtures import frozen_analysis
from test_storage_helpers import claim, detail, rollup, source_data

from aha.decimal_sql import DecimalSum
from aha.domain import AppError, record_key
from aha.migrations import SCHEMA_VERSION
from aha.storage import Store


class AssignmentCoverageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temporary.name))
        self.first = self.store.save_project(None, "项目一", "", [])["project"]["id"]
        self.second = self.store.save_project(None, "项目二", "", [])["project"]["id"]

    def tearDown(self) -> None:
        self.store.close()
        self.temporary.cleanup()

    def seed(self) -> None:
        self.known = detail("known", session_id="known-session", total_cost_usd="1e100",
                            input_tokens=2**63 - 1, input_token_semantics=2)
        self.other = detail("other", session_id="other-session", total_cost_usd="0.00000003")
        self.unknown = detail("unknown", session_id="unknown-session", total_cost_usd="1e-100",
                              input_tokens=2**63 - 1, input_token_semantics=2)
        self.store.sync_data(source_data([self.known, self.other, self.unknown], [rollup()]),
                             trust="live")
        self.store.assign_keys([record_key(self.known)], self.first)
        self.store.assign_keys([record_key(self.other)], self.second)

    def test_project_totals_and_unassigned_conserve_money_and_tokens(self) -> None:
        self.seed()
        results = [self.store.analyze("2026-10-24", "2026-10-26", project)
                   for project in (self.first, self.second, "unassigned")]
        total = self.store.analyze("2026-10-24", "2026-10-26")
        coverage = total["assignment_coverage"]
        self.assertEqual(total["ledger_schema_version"], SCHEMA_VERSION)
        self.assertEqual(coverage["scope"], "period")
        self.assertEqual(coverage["status"], "incomplete")
        self.assertEqual(coverage["unassigned_detail_count"], 1)
        self.assertEqual(coverage["unassigned_rollup_count"], 1)
        self.assertEqual(coverage["unassigned_record_count"], 8)
        amount = DecimalSum()
        amount.step("1e-100")
        amount.step(rollup()["total_cost_usd"])
        self.assertEqual(coverage["unassigned_cost_usd"], amount.finalize())
        self.assertTrue(total["summary_complete"], "assignment is not time/reconciliation coverage")
        self.assertTrue(all(row["assignment_coverage"] == coverage for row in results))
        for key in ("record_count", "detail_count", "rollup_count", "fresh_input_tokens",
                    "output_tokens", "cache_read_tokens", "cache_creation_tokens", "total_tokens"):
            self.assertEqual(sum(row["summary"][key] for row in results), total["summary"][key])
        accumulator = DecimalSum()
        for row in results:
            accumulator.step(row["summary"]["total_cost_usd"])
        self.assertEqual(accumulator.finalize(), total["summary"]["total_cost_usd"])
        self.assertEqual(total["unassigned_count"], coverage["unassigned_record_count"])

    def test_partial_period_omits_rollup_without_counting_its_whole_day_as_unassigned(self) -> None:
        def at(value: str) -> int:
            return int(datetime.fromisoformat(value + "+08:00").timestamp())

        known = detail("known", created_at=at("2026-10-26T10:00:00"), session_id="known")
        unknown = detail("unknown", created_at=at("2026-10-26T10:00:30"),
                         model="unknown-model", session_id="unknown", total_cost_usd="0.00000001")
        outside = detail("outside", created_at=at("2026-10-26T11:00:00"), total_cost_usd="99")
        history = rollup(date="2026-10-26", model="history-model", total_cost_usd="999")
        self.store.sync_data(source_data([known, unknown, outside], [history]), trust="live")
        self.store.assign_keys([record_key(known)], self.first)
        selected = self.store.analyze_time_range({
            "kind": "custom", "start": "2026-10-26T10:00", "end": "2026-10-26T10:00",
            "follow_now": False,
        })
        coverage = selected["assignment_coverage"]
        self.assertEqual(coverage["unassigned_detail_count"], 1)
        self.assertEqual(coverage["unassigned_rollup_count"], 0)
        self.assertEqual(coverage["unassigned_record_count"], 1)
        self.assertEqual(coverage["unassigned_cost_usd"], "0.00000001")
        self.assertFalse(selected["time_coverage"]["complete"])
        self.assertEqual(selected["time_coverage"]["omitted_rollup_count"], 1)
        self.assertEqual(selected["summary"]["record_count"], 2)

    def test_zero_represented_requests_do_not_hide_an_unassigned_rollup(self) -> None:
        self.store.sync_data(source_data([], [rollup(request_count=0, total_cost_usd="0")]),
                             trust="live")
        coverage = self.store.analyze("2026-10-24", "2026-10-24")["assignment_coverage"]
        self.assertEqual(coverage["status"], "incomplete")
        self.assertEqual(coverage["unassigned_rollup_count"], 1)
        self.assertEqual(coverage["unassigned_record_count"], 0)

    def test_available_and_target_exemption_use_the_same_unassigned_members(self) -> None:
        row = detail()
        self.store.sync_data(source_data([row]), trust="live")
        before = self.store.analyze("2026-10-26", "2026-10-26")
        saved = self.store.create_batch(before, claim(), "coverage-own")
        ordinary = self.store.analyze("2026-10-26", "2026-10-26")
        self.assertEqual(ordinary["assignment_coverage"]["unassigned_record_count"], 0)
        for mode in ("available", "all"):
            with self.subTest(mode=mode):
                own = self.store.analyze("2026-10-26", "2026-10-26",
                                         target_batch_id=saved["id"], availability_mode=mode)
                self.assertEqual(own["assignment_coverage"]["availability_mode"], mode)
                self.assertEqual(own["assignment_coverage"]["unassigned_record_count"], 1)
                self.assertEqual(own["assignment_coverage"]["unassigned_cost_usd"],
                                 own["summary"]["total_cost_usd"])

    def test_project_evidence_freezes_counts_without_other_projects_amounts(self) -> None:
        known = detail("known", total_cost_usd="0.1")
        unknown = detail("unknown", session_id="unknown", total_cost_usd="987654321.987654321")
        self.store.sync_data(source_data([known, unknown]), trust="live")
        self.store.assign_keys([record_key(known)], self.first)
        selected = self.store.analyze("2026-10-26", "2026-10-26", self.first)
        coverage = dict(selected["assignment_coverage"])
        selected["assignment_coverage"]["private_path"] = "/private/do-not-share"
        saved = self.store.create_batch(selected, claim(), "coverage-first")
        self.assertEqual(saved["summary"]["record_count"], 1)
        self.assertEqual(saved["summary"]["total_cost_usd"], "0.1")
        original, _ = self.store.download(saved["id"], 1)
        with original.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        with zipfile.ZipFile(original) as package:
            manifest = json.loads(package.read("导出信息.json"))
            shared = manifest["assignment_coverage"]
            self.assertEqual(shared["unassigned_record_count"], 1)
            self.assertNotIn("unassigned_cost_usd", shared)
            self.assertNotIn("private_path", shared)
            self.assertEqual(manifest["ledger"]["schema_version"], SCHEMA_VERSION)
            for name in package.namelist():
                raw = package.read(name)
                self.assertNotIn(b"987654321.987654321", raw)
                self.assertNotIn(b"/private/do-not-share", raw)
            self.assertIn("未归属消费未计入所选项目", package.read("费用说明.html").decode())
        self.store.assign_keys([record_key(unknown)], self.second)
        current = self.store.analyze("2026-10-26", "2026-10-26", self.first,
                                     availability_mode="all")
        self.assertEqual(current["assignment_coverage"]["status"], "complete")
        frozen = frozen_analysis(self.store, saved["id"])
        self.assertEqual(frozen["assignment_coverage"]["unassigned_record_count"],
                         coverage["unassigned_record_count"])
        forged = {**frozen, "assignment_coverage": {**frozen["assignment_coverage"],
                                                   "unassigned_record_count": 0}}
        with self.assertRaises(AppError) as failure:
            self.store.create_batch(forged, claim(purpose="篡改覆盖"), "coverage-forged",
                                    saved["id"])
        self.assertEqual(failure.exception.code, "invalid_analysis")
        revised = self.store.create_batch(frozen, claim(purpose="保留冻结归属说明"),
                                          "coverage-revised", saved["id"])
        self.assertEqual(revised["assignment_coverage"]["unassigned_record_count"], 1)
        unchanged, _ = self.store.download(saved["id"], 1)
        with unchanged.open("rb") as stream:
            self.assertEqual(hashlib.file_digest(stream, "sha256").hexdigest(), digest)

    def test_frozen_record_without_assignment_information_keeps_unknown(self) -> None:
        known = detail()
        self.store.sync_data(source_data([known]), trust="live")
        self.store.assign_keys([record_key(known)], self.first)
        selected = self.store.analyze("2026-10-26", "2026-10-26", self.first)
        selected.pop("assignment_coverage")
        selected.pop("ledger_schema_version")
        saved = self.store.create_batch(selected, claim(), "coverage-legacy")
        self.assertIsNone(saved["assignment_coverage"])
        frozen = frozen_analysis(self.store, saved["id"])
        self.assertIsNone(frozen["assignment_coverage"])
        revised = self.store.create_batch(frozen, claim(purpose="仅补用途"), "legacy-purpose",
                                          saved["id"])
        self.assertIsNone(revised["assignment_coverage"])
        path, _ = self.store.download(revised["id"], revised["version"])
        with zipfile.ZipFile(path) as package:
            self.assertIsNone(json.loads(package.read("导出信息.json"))["assignment_coverage"])
            self.assertIn("原记录未保存同期项目归属覆盖信息",
                          package.read("费用说明.html").decode())

    def test_current_coverage_change_creates_revision_with_stable_member_identity(self) -> None:
        known = detail("known", session_id="known")
        unknown = detail("unknown", session_id="unknown")
        self.store.sync_data(source_data([known, unknown]), trust="live")
        self.store.assign_keys([record_key(known)], self.first)
        selected = self.store.analyze("2026-10-26", "2026-10-26", self.first)
        original = self.store.create_batch(selected, claim(), "coverage-current-original")
        self.assertEqual(original["assignment_coverage"]["unassigned_record_count"], 1)
        package, _ = self.store.download(original["id"], 1)
        with package.open("rb") as stream:
            original_digest = hashlib.file_digest(stream, "sha256").hexdigest()

        self.store.assign_keys([record_key(unknown)], self.second)
        current = self.store.analyze(
            "2026-10-26", "2026-10-26", self.first, target_batch_id=original["id"],
            expected_generation=original["generation"], expected_active_version=1,
        )
        self.assertEqual(current["assignment_coverage"]["status"], "complete")
        revised = self.store.create_batch(current, claim(), "coverage-current-updated",
                                          original["id"])
        self.assertEqual(revised["version"], 2)
        self.assertEqual(revised["assignment_coverage"], current["assignment_coverage"])
        with self.store.read_connection() as connection:
            identities = [tuple(row) for row in connection.execute(
                "SELECT selection_hash,business_hash FROM revisions WHERE batch_id=? "
                "ORDER BY version", (original["id"],),
            )]
        self.assertEqual(len(identities), 2)
        self.assertEqual(identities[0], identities[1], "member/business hash contracts stay stable")
        updated_package, _ = self.store.download(original["id"], 2)
        with zipfile.ZipFile(updated_package) as archive:
            coverage = json.loads(archive.read("导出信息.json"))["assignment_coverage"]
            self.assertEqual(coverage["status"], "complete")
            self.assertEqual(coverage["unassigned_record_count"], 0)
        with package.open("rb") as stream:
            self.assertEqual(hashlib.file_digest(stream, "sha256").hexdigest(), original_digest)

        replay = self.store.create_batch(current, claim(), "coverage-current-updated",
                                         original["id"])
        self.assertEqual(replay["version"], 2)
        unchanged = self.store.analyze(
            "2026-10-26", "2026-10-26", self.first, target_batch_id=original["id"],
            expected_generation=revised["generation"], expected_active_version=2,
        )
        no_op = self.store.create_batch(unchanged, claim(), "coverage-current-noop", original["id"])
        self.assertEqual(no_op["version"], 2)

        frozen = frozen_analysis(self.store, original["id"])
        self.store.assign_keys([record_key(unknown)], None)
        live = self.store.analyze("2026-10-26", "2026-10-26", self.first)
        self.assertEqual(live["assignment_coverage"]["status"], "incomplete")
        frozen_no_op = self.store.create_batch(frozen, claim(), "coverage-frozen-noop",
                                               original["id"])
        self.assertEqual(frozen_no_op["version"], 2)
        self.assertEqual(frozen_no_op["assignment_coverage"]["status"], "complete")


if __name__ == "__main__":
    unittest.main()
