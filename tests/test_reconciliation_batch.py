"""Bulk reconciliation works on a snapshot of actual native/legacy evidence."""

from __future__ import annotations

import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import patch

from native_usage_fixtures import CACHED, COST, INPUT, MODEL, OUTPUT, SESSION, START, write_rollout
from test_codex_sessions import STAMP, _context, _header, _response, _snapshot, _tokens
from test_storage_helpers import claim, detail, rollup, source_data

from aha import backup, ledger
from aha.codex_sessions import CodexSource
from aha.domain import AppError, content_hash, record_key
from aha.storage import Store

PAIRED_RESPONSE = "2026-11-24T09:14:02.999999Z"
PAIRED_SNAPSHOT = "2026-11-24T09:14:03.999999Z"


def legacy_native_row(index: int, **changes: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "created_at": int(START.timestamp()) + index,
        "session_id": SESSION,
        "model": MODEL,
        "pricing_model": MODEL,
        "input_tokens": INPUT,
        "output_tokens": OUTPUT,
        "cache_read_tokens": CACHED,
        "cache_creation_tokens": 0,
        "total_cost_usd": COST,
    }
    return detail(f"legacy-{index}", **(fields | changes))


class ReconciliationBatchTests(unittest.TestCase):
    def setUp(self) -> None:
        folder = self.enterContext(TemporaryDirectory())
        self.root = Path(folder)
        self.source = self.root / "codex"
        self.store = Store(self.root / "ledger")
        self.addCleanup(self.store.close)

    def sync_native(self) -> None:
        self.store.sync_codex(CodexSource("windows", str(self.source)), "windows")

    def seed_matched(self, count: int) -> None:
        self.store.sync_data(source_data([legacy_native_row(index) for index in range(count)]))
        write_rollout(self.source, count)
        self.sync_native()

    def write_paired_rollout(self, response_at: str, snapshot_at: str, extra: bytes = b"") -> None:
        directory = self.source / "sessions"
        directory.mkdir(parents=True)
        (directory / "rollout-paired.jsonl").write_bytes(
            _header() + _context(stamp=response_at) + _response("paired", 1, response_at)
            + _snapshot(1, snapshot_at) + extra
        )

    def seed_paired(
        self, response_at: str = PAIRED_RESPONSE, snapshot_at: str = PAIRED_SNAPSHOT,
        *, cost_usd: str = COST,
    ) -> dict[str, Any]:
        history_second = int(datetime.fromisoformat(snapshot_at).timestamp())
        legacy = legacy_native_row(0, created_at=history_second, total_cost_usd=cost_usd)
        self.store.sync_data(source_data([legacy]))
        self.write_paired_rollout(response_at, snapshot_at)
        self.sync_native()
        page = self.store.reconciliation_page({})
        self.assertEqual((page["total"], page["eligible_count"]), (1, 1))
        return page

    def request_batch(
        self, page: dict[str, Any], filters: dict[str, str], **selection: Any
    ) -> tuple[dict[str, Any], int]:
        basis = {"filters": filters, **selection}
        preview = self.store.preview_reconciliation_batch({**basis, "version": page["version"]})
        return {
            **basis, "preview_hash": preview["preview_hash"],
            "reason": "依照历史与原生用量的一一对应核对",
            "idempotency_key": "reconciliation-fixture-request",
        }, preview["count"]

    def test_cross_page_filtered_all_recomputes_once_and_preserves_frozen_history(self) -> None:
        count = 1003
        rows = [legacy_native_row(index) for index in range(count)]
        rows[0]["total_cost_usd"] += "00"  # The same amount with a stored higher scale.
        rows[-1]["total_cost_usd"] = "0.9"
        rows[-2]["input_tokens"] = INPUT + 1
        rows[-2]["cache_read_tokens"] = CACHED + 1
        self.store.sync_data(source_data(rows))
        analysis = self.store.analyze("2026-10-26", "2026-10-26")
        batch = self.store.create_batch(analysis, claim(), "fixture-frozen-legacy-claim")
        package, _ = self.store.download(batch["id"], batch["version"])
        original_package = package.read_bytes()

        write_rollout(self.source, count)
        self.sync_native()
        self.assertEqual(self.store.reconciliation_summary(), {"total": count})
        filters = {"source_id": "windows", "start_date": "2026-10-26", "end_date": "2026-10-26",
                   "eligibility": "batch", "type": "identity"}
        page = self.store.reconciliation_page(filters, size=200)
        self.assertEqual((page["total"], page["eligible_count"]), (count - 2, count - 2))
        self.assertEqual(len(page["cases"]), 200)
        self.assertTrue(all(case["batch_eligible"] for case in page["cases"]))
        self.assertNotIn("current_summary", page["cases"][0])
        evidence = self.store.reconciliation_detail(page["cases"][0]["id"])
        self.assertEqual(evidence["current_summary"]["cache_read_tokens"], CACHED)
        self.assertEqual(evidence["choices"], ["same", "independent"])
        self.assertEqual(page["sources"], [{"id": "windows", "name": "Windows Codex"}])
        self.assertEqual(self.store.reconciliation_page({"source_id": "wsl"})["total"], 0)
        self.assertEqual(self.store.reconciliation_page({"end_date": "2026-10-25"})["total"], 0)
        self.assertEqual(self.store.reconciliation_page({"eligibility": "manual"})["total"], 2)

        ids = [case["id"] for case in page["cases"]]
        cursor = page["next_cursor"]
        while cursor:
            next_page = self.store.reconciliation_page(filters, size=200, cursor=cursor)
            ids.extend(case["id"] for case in next_page["cases"])
            cursor = next_page["next_cursor"]
        self.assertEqual(len(ids), count - 2)
        self.assertEqual(len(set(ids)), count - 2)

        request, expected_count = self.request_batch(page, filters)
        self.assertEqual(expected_count, count - 2)
        revisions = self.store.revisions()
        with (
            patch.object(ledger, "reclassify", wraps=ledger.reclassify) as reclassify,
            patch.object(ledger, "refresh_availability", wraps=ledger.refresh_availability)
            as refresh,
        ):
            result = self.store.apply_reconciliation_batch(request)
            self.assertEqual(self.store.apply_reconciliation_batch(request), result)
        reclassify.assert_not_called()
        refresh.assert_called_once()
        self.assertEqual(result["data_revision"], revisions["data_revision"] + 1)
        self.assertEqual(result["claim_revision"], revisions["claim_revision"])
        self.assertEqual(result["classification_revision"], revisions["classification_revision"])
        self.assertEqual((result["resolved_count"], result["open_count"]), (count - 2, 2))
        self.assertEqual(self.store.download(batch["id"], batch["version"])[0].read_bytes(),
                         original_package)
        with self.store.read_connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM usage_claims").fetchone()[0],
                             count)
            self.assertEqual(
                connection.execute(
                    "SELECT choice,reason,COUNT(*) FROM reconciliation_events GROUP BY 1,2"
                ).fetchone()[:],
                ("same", request["reason"], count - 2),
            )

        with self.assertRaises(AppError) as stale:
            self.store.reconciliation_page(filters, cursor=page["next_cursor"])
        self.assertEqual(stale.exception.code, "invalid_cursor")
        with self.assertRaises(AppError) as conflict:
            self.store.apply_reconciliation_batch({**request, "reason": "不同说明"})
        self.assertEqual(conflict.exception.code, "idempotency_conflict")

    def test_manual_identity_details_show_the_canonical_history_after_another_confirmation(
        self,
    ) -> None:
        original = legacy_native_row(0, total_cost_usd="0.1")
        intermediate = legacy_native_row(1, total_cost_usd="0.2")
        candidate = legacy_native_row(2, total_cost_usd="0.3")
        self.store.sync_data(source_data([original, intermediate, candidate]))
        original_key, intermediate_key, candidate_key = map(
            record_key, (original, intermediate, candidate),
        )
        with self.store._transaction():
            connection = self.store._db
            first_case = ledger.create_case(
                connection, "identity", "核对历史身份", {"other_record_key": original_key},
                key=intermediate_key,
            )
            remaining_case = ledger.create_case(
                connection, "identity", "核对历史身份", {"other_record_key": intermediate_key},
                key=candidate_key,
            )

        self.store.resolve_reconciliation(first_case, "same", "采用原始历史")
        evidence = self.store.reconciliation_detail(remaining_case)
        self.assertEqual(evidence["current_summary"]["total_cost_usd"], "0.1")
        self.assertEqual(evidence["candidate_summary"]["total_cost_usd"], "0.3")
        self.store.resolve_reconciliation(remaining_case, "same", "与上述历史相同",
                                          evidence["generation"])
        with self.store.read_connection() as connection:
            self.assertEqual(ledger.canonical_record_key(connection, candidate_key), original_key)

    def test_same_second_distinct_native_events_are_kept_for_individual_review(self) -> None:
        older = legacy_native_row(0, created_at=int(datetime.fromisoformat(STAMP).timestamp()))
        self.store.sync_data(source_data([older]))
        directory = self.source / "sessions"
        directory.mkdir(parents=True)
        (directory / "rollout-fixture.jsonl").write_bytes(
            _header() + _context() + _response("first", 1) + _response("second", 2)
        )
        self.sync_native()
        filters = {"type": "identity"}
        page = self.store.reconciliation_page(filters)
        self.assertEqual((page["total"], page["eligible_count"]), (2, 0))
        first = page["cases"][0]
        self.store.resolve_reconciliation(
            first["id"], "independent", "核对为两个原生事件", first["generation"]
        )
        page = self.store.reconciliation_page(filters)
        self.assertEqual((page["total"], page["eligible_count"]), (1, 0))
        with self.assertRaises(AppError) as no_batch:
            self.request_batch(page, filters)
        self.assertEqual(no_batch.exception.code, "empty_reconciliation_batch")
        item = self.store.reconciliation_detail(page["cases"][0]["id"])
        self.assertEqual(item["type"], "identity")

    def test_ingested_pair_crosses_beijing_midnight_and_preserves_exact_utc_second(self) -> None:
        # Fractions at the end of a second must not be rounded by SQLite's date parser.
        before = "2026-11-24T15:59:59.999999Z"
        after = "2026-11-24T16:00:00.999999Z"
        page = self.seed_paired(before, after)
        case = self.store.reconciliation_detail(page["cases"][0]["id"])
        self.assertEqual(case["current_summary"]["created_at"],
                         int(datetime.fromisoformat(after).timestamp()))
        self.assertEqual(case["candidate_summary"]["created_at"],
                         int(datetime.fromisoformat(before).timestamp()))
        self.assertEqual(page["cases"][0]["date"], "2026-11-24")
        request, expected = self.request_batch(page, {})
        self.assertEqual(expected, 1)

        # Older saved evidence can spell the same UTC instant with Z.
        with self.store._transaction():
            self.store._db.execute(
                "UPDATE codex_event_evidence SET evidence_json="
                "json_set(evidence_json,'$.timestamp',?,'$.snapshot_timestamp',?)",
                (before, after),
            )

        result = self.store.apply_reconciliation_batch(request)
        self.assertEqual((result["resolved_count"], result["open_count"]), (1, 0))
        history = self.store.analyze("2026-11-25", "2026-11-25")
        response = self.store.analyze("2026-11-24", "2026-11-24")
        self.assertEqual(history["summary"]["total_cost_usd"], COST)
        self.assertEqual(response["summary"]["record_count"], 0)

    def test_skew_requires_paired_current_response_and_matching_thread(self) -> None:
        self.seed_paired()
        with self.store.read_connection() as connection:
            saved = connection.execute(
                "SELECT event_id,evidence_json FROM codex_event_evidence",
            ).fetchone()
        evidence = json.loads(saved["evidence_json"])
        for changes in (
            {"snapshot_timestamp": None}, {"snapshot_timestamp": "2026-11-31T09:14:03Z"},
            {"snapshot_id": ""}, {"response_id": ""}, {"thread_id": "other-thread"},
            {"timestamp": "2026-11-24T09:14:01.999999Z"}, {"kind": "snapshot"},
            {"pending_reason": "snapshot_receipt_mismatch"},
        ):
            with self.subTest(changes=changes):
                modified = evidence | changes
                if changes == {"snapshot_timestamp": None}:
                    modified.pop("snapshot_timestamp")
                with self.store._transaction():
                    self.store._db.execute("UPDATE codex_event_evidence SET evidence_json=?",
                                           (json.dumps(modified),))
                page = self.store.reconciliation_page({})
                self.assertEqual((page["total"], page["eligible_count"]), (1, 0))

        with self.store._transaction():
            self.store._db.execute(
                "UPDATE codex_event_evidence SET evidence_json=?,event_id='other-event'",
                (saved["evidence_json"],),
            )
        self.assertEqual(self.store.reconciliation_page({})["eligible_count"], 0)

    def test_conflicting_paired_observations_and_changed_proofs_expire_a_preview(self) -> None:
        page = self.seed_paired()
        request, _ = self.request_batch(page, {})
        with self.store._transaction():
            connection = self.store._db
            connection.execute("""
                INSERT INTO codex_event_evidence
                SELECT version_id,source_id,'duplicate-fixture-observation',event_id,run_id,
                       pricing_basis,evidence_json FROM codex_event_evidence
            """)
        self.assertEqual(self.store.reconciliation_page({})["eligible_count"], 1)
        with self.store._transaction():
            self.store._db.execute("""
                UPDATE codex_event_evidence SET evidence_json=json_set(
                    evidence_json,'$.snapshot_timestamp','2026-11-24T09:14:03.100000Z'
                ) WHERE evidence_hash='duplicate-fixture-observation'
            """)
        self.assertEqual(self.store.reconciliation_page({})["eligible_count"], 0)
        with self.assertRaises(AppError) as ambiguous:
            self.store.apply_reconciliation_batch(request)
        self.assertEqual(ambiguous.exception.code, "stale_reconciliation_batch")

        with self.store._transaction():
            self.store._db.execute(
                "DELETE FROM codex_event_evidence "
                "WHERE evidence_hash!='duplicate-fixture-observation'"
            )
        current = self.store.reconciliation_page({})
        self.assertEqual(current["version"], page["version"])
        self.assertEqual(current["eligible_count"], 1)
        with self.assertRaises(AppError) as changed:
            self.store.apply_reconciliation_batch(request)
        self.assertEqual(changed.exception.code, "stale_reconciliation_batch")
        self.assertEqual(self.store.reconciliation_summary(), {"total": 1})

    def assert_distinct_native_blocks_paired(
        self, response_at: str, snapshot_at: str | None = None, *, total: int = 2,
    ) -> None:
        first = self.seed_paired()["cases"][0]["id"]
        (self.source / "sessions" / "rollout-other.jsonl").write_bytes(
            _header() + _context(stamp=response_at) + _response("other", total, response_at)
            + (_snapshot(total, snapshot_at) if snapshot_at is not None else b"")
        )
        self.sync_native()
        cases = self.store.list_reconciliations()
        for other in cases:
            if other["id"] != first:
                self.store.resolve_reconciliation(
                    other["id"], "independent", "已核对为独立响应", other["generation"],
                )
        page = self.store.reconciliation_page({})
        self.assertEqual((page["total"], page["eligible_count"]), (1, 0))
        self.assertEqual(page["cases"][0]["id"], first)

    def test_independent_response_at_native_second_blocks_the_paired_case(self) -> None:
        self.assert_distinct_native_blocks_paired(PAIRED_RESPONSE)

    def test_independent_response_at_snapshot_second_blocks_the_paired_case(self) -> None:
        self.assert_distinct_native_blocks_paired(PAIRED_SNAPSHOT)

    def test_independent_saved_pair_with_another_id_at_snapshot_second_blocks_case(self) -> None:
        self.assert_distinct_native_blocks_paired("2026-11-24T09:14:01Z", PAIRED_SNAPSHOT)

    def test_another_response_with_the_same_pair_id_blocks_case_across_times(self) -> None:
        self.assert_distinct_native_blocks_paired("2026-11-24T09:14:15Z", total=1)

    def test_history_at_both_response_and_snapshot_seconds_stays_manual(self) -> None:
        page = self.seed_paired()
        response = int(datetime.fromisoformat(PAIRED_RESPONSE).timestamp())
        snapshot = int(datetime.fromisoformat(PAIRED_SNAPSHOT).timestamp())
        self.store.sync_data(source_data([
            legacy_native_row(0, created_at=snapshot), legacy_native_row(1, created_at=response),
        ]))
        current = self.store.reconciliation_page({})
        self.assertEqual((current["total"], current["eligible_count"]), (1, 0))
        self.assertEqual(current["cases"][0]["id"], page["cases"][0]["id"])

    def test_adopt_paired_cost_keeps_logical_key_manual_override_and_frozen_packages(self) -> None:
        historical_cost = "0.123456789012345678901234567890123456"
        historic = legacy_native_row(
            0, created_at=int(datetime.fromisoformat(PAIRED_SNAPSHOT).timestamp()),
            total_cost_usd=historical_cost,
        )
        native_time = int(datetime.fromisoformat(PAIRED_RESPONSE).timestamp())
        equal_time = "2026-11-24T09:14:20Z"
        equal = legacy_native_row(
            1, created_at=int(datetime.fromisoformat(equal_time).timestamp()),
            total_cost_usd=COST + "00",
        )
        archived = legacy_native_row(2, session_id="archived-other-session")
        history = source_data([historic, equal, archived])
        self.store.sync_data(history)
        key = record_key(historic)
        project = self.store.save_project(None, "保留的人工项目", "", [])["project"]["id"]
        self.store.assign_keys([key], project)
        old_analysis = self.store.analyze("2026-10-26", "2026-10-26")
        old_batch = self.store.create_batch(old_analysis, claim(), "fixture-other-claim")
        old_package = self.store.download(old_batch["id"], old_batch["version"])[0].read_bytes()
        self.write_paired_rollout(
            PAIRED_RESPONSE, PAIRED_SNAPSHOT, _response("equal", 2, equal_time),
        )
        self.sync_native()
        with self.store.read_connection() as connection:
            origin = connection.execute(
                "SELECT version_id,scope_key FROM usage_records WHERE record_key=?", (key,),
            ).fetchone()
            equal_version = connection.execute(
                "SELECT version_id FROM usage_records WHERE record_key=?", (record_key(equal),),
            ).fetchone()[0]
        page = self.store.reconciliation_page({}, size=1)
        preview = self.store.preview_reconciliation_batch({
            "filters": {}, "version": page["version"],
        })
        self.assertEqual(preview["count"], 2)
        self.assertEqual(preview["candidate_count"], 1)
        self.assertEqual(preview["current_cost_usd"], historical_cost)
        self.assertEqual(preview["candidate_cost_usd"], COST)
        request, _ = self.request_batch(page, {})
        before = self.store.revisions()
        with patch.object(ledger, "refresh_availability", wraps=ledger.refresh_availability) as run:
            result = self.store.apply_reconciliation_batch(request)
            self.assertEqual(self.store.apply_reconciliation_batch(request), result)
        run.assert_called_once()
        self.assertEqual(result["data_revision"], before["data_revision"] + 1)
        self.assertEqual(result["classification_revision"], before["classification_revision"])
        self.assertEqual((result["resolved_count"], result["open_count"]), (2, 0))
        with self.store.read_connection() as connection:
            adopted = connection.execute(
                """SELECT r.event_time,r.version_id,r.suppressed,r.total_cost_usd,r.scope_key,
                          r.project_id,r.content_hash,o.content_hash AS override_hash,
                          v.record_key AS raw_key
                   FROM usage_records r JOIN usage_versions v ON v.id=r.version_id
                   JOIN overrides o ON o.record_key=r.record_key WHERE r.record_key=?""",
                (key,),
            ).fetchone()
            self.assertEqual(adopted["event_time"], native_time)
            self.assertEqual(adopted["total_cost_usd"], COST)
            self.assertEqual(adopted["project_id"], project)
            self.assertEqual(adopted["content_hash"], adopted["override_hash"])
            self.assertEqual(adopted["suppressed"], 0)
            self.assertNotEqual(adopted["raw_key"], key)
            self.assertEqual(ledger.canonical_record_key(connection, adopted["raw_key"]), key)
            self.assertEqual(
                connection.execute(
                    "SELECT suppressed FROM usage_records WHERE record_key=?",
                    (adopted["raw_key"],),
                ).fetchone()[0], 1,
            )
            self.assertEqual(run.call_args.args[1], {origin["scope_key"], adopted["scope_key"]})
            self.assertEqual(
                connection.execute(
                    "SELECT version_id FROM usage_records WHERE record_key=?", (record_key(equal),),
                ).fetchone()[0], equal_version,
            )
            audit = connection.execute("""
                SELECT c.info_json,e.choice,e.reason FROM reconciliation_events e
                JOIN reconciliation_cases c ON c.id=e.case_id WHERE c.record_key=?
            """, (adopted["raw_key"],)).fetchone()
            self.assertEqual((audit["choice"], audit["reason"]),
                             (ledger.SAME_CANDIDATE, request["reason"]))
            evidence = json.loads(audit["info_json"])
            self.assertEqual(evidence["current_version_id"], origin["version_id"])
            self.assertEqual(evidence["candidate_version_id"], adopted["version_id"])
            self.assertEqual(evidence["current_cost_usd"], historical_cost)
            self.assertEqual(evidence["candidate_cost_usd"], COST)
        with self.assertRaises(AppError) as stale:
            self.store.reconciliation_detail(page["cases"][0]["id"])
        self.assertEqual(stale.exception.code, "stale_case")

        native_source = CodexSource("windows", str(self.source))
        native_replay = self.store.sync_codex(native_source, "native-second-source")
        historic_replay = self.store.sync_data(history)
        self.assertEqual((native_replay["new_count"], native_replay["pending_count"]), (0, 0))
        self.assertEqual((historic_replay["new_count"], historic_replay["pending_count"]), (0, 0))
        self.assertEqual(self.store.reconciliation_summary(), {"total": 0})

        with self.store._transaction():
            ledger.reclassify(self.store._db)
            ledger.refresh_availability(self.store._db)
        analysis = self.store.analyze("2026-11-24", "2026-11-24", project)
        self.assertEqual(analysis["summary"]["total_cost_usd"], COST)
        found = self.store.analysis_details(analysis)["rows"][0]
        self.assertEqual((found["record_key"], found["assignment_origin"]), (key, "manual"))
        new_batch = self.store.create_batch(analysis, claim(), "fixture-adopted-claim")
        new_package = self.store.download(new_batch["id"], new_batch["version"])[0].read_bytes()

        archive = self.root / "adopted.aha-backup"
        backup.create_backup(self.store.data_dir, archive)
        restored_path = self.root / "restored"
        backup.restore_backup(archive, restored_path)
        restored = Store(restored_path)
        self.addCleanup(restored.close)
        for batch, package in ((old_batch, old_package), (new_batch, new_package)):
            self.assertEqual(restored.download(batch["id"], batch["version"])[0].read_bytes(),
                             package)
        self.assertEqual(restored.analyze(
            "2026-11-24", "2026-11-24", project, availability_mode="all",
        )["summary"]["total_cost_usd"], COST)
        self.assertEqual(restored.analyze(
            "2026-11-24", "2026-11-24", project,
        )["summary"]["record_count"], 0)

    def test_paired_amount_diff_becomes_manual_after_claim_and_keeps_frozen_cost(self) -> None:
        historic_cost = "0.44550001"
        page = self.seed_paired(cost_usd=historic_cost)
        request, _ = self.request_batch(page, {})
        analysis = self.store.analyze("2026-11-24", "2026-11-24")
        self.assertEqual(analysis["summary"]["total_cost_usd"], historic_cost)
        frozen = self.store.create_batch(analysis, claim(), "fixture-claimed-historical-cost")
        package, _ = self.store.download(frozen["id"], frozen["version"])
        original_bytes = package.read_bytes()
        self.assertEqual(self.store.reconciliation_page({})["eligible_count"], 0)
        with self.assertRaises(AppError) as stale:
            self.store.apply_reconciliation_batch(request)
        self.assertEqual(stale.exception.code, "stale_reconciliation_batch")
        historic_case = page["cases"][0]
        self.store.resolve_reconciliation(
            historic_case["id"], "same", "单笔确认入账历史", historic_case["generation"],
        )
        self.assertEqual(self.store.analyze(
            "2026-11-24", "2026-11-24", availability_mode="all",
        )["summary"]["total_cost_usd"], historic_cost)
        self.assertEqual(self.store.download(frozen["id"], frozen["version"])[0].read_bytes(),
                         original_bytes)

    def test_legacy_projection_rollup_does_not_block_confirming_paired_details(self) -> None:
        historic_cost = "0.335501"
        page = self.seed_paired(cost_usd=historic_cost)
        request, _ = self.request_batch(page, {})
        history = legacy_native_row(
            0, created_at=int(datetime.fromisoformat(PAIRED_SNAPSHOT).timestamp()),
            total_cost_usd=historic_cost,
        )
        self.store.sync_data(source_data([history], [rollup(
            date="2026-11-24", model=MODEL, pricing_model=MODEL, request_model="other-model",
        )]))
        current = self.store.reconciliation_page({})
        self.assertEqual((current["total"], current["eligible_count"]), (1, 1))
        self.store.apply_reconciliation_batch(request)

    def test_adopted_fact_detects_detached_snapshot_and_late_native_revision(self) -> None:
        page = self.seed_paired(cost_usd="0.62344")
        request, _ = self.request_batch(page, {})
        self.store.apply_reconciliation_batch(request)
        history = legacy_native_row(
            0, created_at=int(datetime.fromisoformat(PAIRED_SNAPSHOT).timestamp()),
        )
        key = record_key(history)
        (self.source / "sessions" / "rollout-detached.jsonl").write_bytes(
            _header() + _context(stamp=PAIRED_SNAPSHOT) + _snapshot(1, PAIRED_SNAPSHOT),
        )
        self.sync_native()
        cases = self.store.list_reconciliations()
        self.assertEqual(len(cases), 1)
        self.assertTrue(cases[0]["native_snapshot_pair"])
        self.assertEqual(cases[0]["other_record_key"], key)
        self.store.resolve_reconciliation(
            cases[0]["id"], "same", "相同响应的快照", cases[0]["generation"],
        )
        self.assertEqual(
            self.store.analyze("2026-11-24", "2026-11-24")["summary"]["total_cost_usd"], COST,
        )

        other_usage = _tokens() | {"output_tokens": OUTPUT + 1, "total_tokens": INPUT + OUTPUT + 1}
        (self.source / "sessions" / "rollout-revised.jsonl").write_bytes(
            _header() + _context(stamp=PAIRED_RESPONSE)
            + _response("paired", 1, PAIRED_RESPONSE, usage=other_usage),
        )
        self.sync_native()
        changes = self.store.list_reconciliations()
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["type"], "revision")
        self.assertEqual(changes[0]["current_summary"]["total_cost_usd"], COST)
        with self.store.read_connection() as connection:
            self.assertEqual(connection.execute(
                "SELECT record_key FROM reconciliation_cases WHERE id=?",
                (changes[0]["id"],),
            ).fetchone()[0], key)

    def test_candidate_cost_refreshes_both_days_when_response_crosses_midnight(self) -> None:
        before = "2026-11-24T15:59:59.999999Z"
        after = "2026-11-24T16:00:00.999999Z"
        page = self.seed_paired(before, after, cost_usd="0.5")
        request, _ = self.request_batch(page, {})
        self.store.apply_reconciliation_batch(request)
        native_day = self.store.analyze("2026-11-24", "2026-11-24")["summary"]
        history_day = self.store.analyze("2026-11-25", "2026-11-25")["summary"]
        self.assertEqual((native_day["record_count"], native_day["total_cost_usd"]), (1, COST))
        self.assertEqual(history_day["record_count"], 0)

    def test_accepted_pair_blocks_a_later_conflicting_response_through_alias(self) -> None:
        old_cost = "0.2"
        page = self.seed_paired(cost_usd=old_cost)
        request, _ = self.request_batch(page, {})
        self.store.apply_reconciliation_batch(request)
        instant = "2026-11-24T09:14:01Z"
        before = legacy_native_row(
            0, created_at=int(datetime.fromisoformat(PAIRED_SNAPSHOT).timestamp()),
            total_cost_usd=old_cost,
        )
        next_history = legacy_native_row(
            1, created_at=int(datetime.fromisoformat(instant).timestamp()),
        )
        self.store.sync_data(source_data([before, next_history]))
        (self.source / "sessions" / "rollout-competing-pair.jsonl").write_bytes(
            _header() + _context(stamp=instant) + _response("different-response", 2, instant)
            + _snapshot(2, PAIRED_SNAPSHOT),
        )
        self.sync_native()
        current = self.store.reconciliation_page({})
        self.assertEqual((current["total"], current["eligible_count"]), (1, 0))
        self.assertEqual(current["cases"][0]["type"], "identity")

    def test_previous_commit_can_replay_its_original_signature(self) -> None:
        old = {"resolved_count": 1, "open_count": 0, **self.store.revisions()}
        filters = {"eligibility": "all"}
        preview = "a" * 64
        reason = "使用以前的确认结果"
        key = "previous-committed-reconciliation"
        signature = content_hash(["batch_same", filters, None, preview, reason])
        with self.store._transaction():
            self.store._db.execute("INSERT INTO reconciliation_idempotency VALUES(?,?,?)", (
                key, signature, self.store._encode(old),
            ))
        self.assertEqual(self.store.apply_reconciliation_batch({
            "filters": filters, "preview_hash": preview, "idempotency_key": key, "reason": reason,
        }), old)

    def test_apply_rechecks_evidence_and_unwinds_a_failure_after_writing(self) -> None:
        self.seed_matched(3)
        page = self.store.reconciliation_page({}, size=1)
        second = self.store.reconciliation_page({}, cursor=page["next_cursor"], size=1)
        selected = [page["cases"][0]["id"], second["cases"][0]["id"]]
        request, expected = self.request_batch(page, {}, ids=selected)
        self.assertEqual(expected, 2)
        with self.store._transaction():
            self.store._db.execute(
                "UPDATE codex_event_evidence SET pricing_basis=NULL WHERE version_id=("
                "SELECT r.version_id FROM usage_records r JOIN reconciliation_cases c "
                "ON r.record_key=c.record_key WHERE c.id=?)",
                (selected[1],),
            )
        self.assertEqual(self.store.reconciliation_page({})["version"], page["version"])
        with self.assertRaises(AppError) as stale:
            self.store.apply_reconciliation_batch(request)
        self.assertEqual(stale.exception.code, "stale_reconciliation_batch")
        self.assertEqual(self.store.reconciliation_summary()["total"], 3)
        with self.store._transaction():
            self.store._db.execute(
                "UPDATE codex_event_evidence SET pricing_basis='synthetic-evidence-restored' "
                "WHERE pricing_basis IS NULL"
            )

        with (
            patch.object(ledger, "refresh_availability", side_effect=AppError("injected", "失败")),
            self.assertRaises(AppError),
        ):
            self.store.apply_reconciliation_batch(request)
        self.assertEqual(self.store.reconciliation_summary()["total"], 3)
        with self.store.read_connection() as connection:
            for table in ("record_aliases", "reconciliation_events", "reconciliation_idempotency"):
                self.assertEqual(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0],
                                 0)
        result = self.store.apply_reconciliation_batch(request)
        self.assertEqual((result["resolved_count"], result["open_count"]), (2, 1))

    def test_two_store_connections_replay_the_same_operation(self) -> None:
        self.seed_matched(2)
        page = self.store.reconciliation_page({})
        request, _ = self.request_batch(page, {})
        other = Store(self.root / "ledger")
        self.addCleanup(other.close)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda store: store.apply_reconciliation_batch(request),
                                    (self.store, other)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0]["resolved_count"], 2)
        with self.assertRaises(AppError) as stale:
            other.apply_reconciliation_batch({
                **request, "idempotency_key": "distinct-operation-id",
            })
        self.assertEqual(stale.exception.code, "stale_reconciliation_batch")
        with self.store.read_connection() as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM reconciliation_events").fetchone()[0], 2,
            )
