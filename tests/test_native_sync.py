"""Native source publication, replay, and migration against isolated ledger files."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from test_storage_helpers import claim, detail, metadata, rollup, source_data

from aha import backup
from aha.codex_sessions import CodexSource
from aha.domain import AppError, record_key
from aha.native_sync import NativeBatch
from aha.storage import Store

LOCAL = CodexSource("windows", "/fixture/windows")
WSL = CodexSource("wsl", "/fixture/wsl", "FixtureDistro")
PATH = "sessions/fixture.jsonl"


def usage(event_id: str, file_path: str = PATH, *, priced: bool = True, **changes):
    row = detail(event_id, data_source="codex_native", **changes)
    if not priced:
        for field in ("input", "output", "cache_read", "cache_creation", "total"):
            row[f"{field}_cost_usd"] = "0"
    return SimpleNamespace(
        event_id=event_id, row=row, relative_path=file_path,
        session={"session_id": "s1", "cwd": "/work/a", "status": "matched", "parent_id": None},
        pricing_basis="fixture-rates-v1" if priced else None,
        price=source_data()["pricing"][0] if priced else None,
        evidence={"kind": "response", "response_id": event_id, "thread_id": "s1",
                  "timestamp": "2026-10-25T17:00:00Z", "unrelated": "never stored"},
    )


class NativeSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(temporary)
        self.store = Store(self.root / "data")
        self.addCleanup(self.store.close)

    def sync(
        self, events=(), *, source=LOCAL, expected_cursor=None, offset=100, coverage="complete",
        since=None, source_id=None,
    ):
        def scan(selected, load_cursor, on_event, on_cursor, *, cancel):
            self.assertEqual(selected, source)
            self.assertFalse(cancel.is_set())
            self.assertEqual(load_cursor(PATH), expected_cursor)
            for event in events:
                on_event(event)
            timestamps = [event.row["created_at"] for event in events]
            on_cursor(PATH, {"offset": offset})
            return {
                "files": 1, "bytes_read": offset, "events": len(events), "coverage": coverage,
                "issues": {"tail": 1} if coverage == "partial" else {},
                "first_at": min(timestamps, default=None), "last_at": max(timestamps, default=None),
            }

        with patch("aha.native_sync.scan_source", side_effect=scan):
            return self.store.sync_codex(source, source_id or source.kind, since=since)

    def query(self, mode: str = "available") -> dict:
        return self.store.analyze("2026-10-24", "2026-10-26", availability_mode=mode)

    def test_copies_and_resume_preserve_distinct_same_second_claimable_events(self) -> None:
        first = usage("event-1")
        capture = self.sync([first, usage("event-1", "archived_sessions/same.jsonl.zst")])
        self.assertEqual(capture["new_count"], 1)
        claim_one = self.store.create_batch(self.query(), claim(), "claim-same-second-first")
        result = self.sync([first, usage("event-2", priced=False)], source=WSL, offset=200)
        self.assertEqual((result["new_count"], result["unchanged_count"]), (1, 1))
        self.assertEqual(result["pending_count"], 0)
        self.assertEqual(self.query()["summary"]["record_count"], 1)
        self.assertEqual(self.query()["summary"]["unpriced_count"], 1)
        self.assertEqual(self.query("all")["summary"]["record_count"], 2)
        repeated = self.sync(expected_cursor={"offset": 100}, offset=100)
        self.assertEqual(repeated["new_count"], 0)
        self.assertEqual(repeated["state"], "completed")
        self.assertEqual(repeated["first_at"], first.row["created_at"])
        with self.store.read_connection() as database:
            evidence = database.execute(
                "SELECT source_id,pricing_basis,evidence_json FROM codex_event_evidence"
            ).fetchall()
            self.assertEqual(len(evidence), 4)
            self.assertNotIn("never stored", "".join(row["evidence_json"] for row in evidence))
            self.assertEqual(
                database.execute("SELECT COUNT(*) FROM usage_versions").fetchone()[0], 2
            )
            self.assertEqual(database.execute("SELECT COUNT(*) FROM usage_claims").fetchone()[0], 1)
        self.store.download(claim_one["id"], claim_one["version"])

    def test_failed_second_source_does_not_commit_its_event_or_cursor(self) -> None:
        self.sync([usage("first")])
        original = NativeBatch.publish

        def fail(batch, stager, scopes, counts):
            original(batch, stager, scopes, counts)
            raise AppError("fixture_failure", "fixture only")

        with patch.object(NativeBatch, "publish", fail), self.assertRaises(AppError):
            self.sync([usage("second")], source=WSL)
        self.assertEqual(self.query()["summary"]["record_count"], 1)
        self.assertEqual(self.store.sync_status()["state"], "failed")
        with self.store.read_connection() as database:
            for table in ("codex_file_progress", "codex_event_evidence"):
                self.assertEqual(database.execute(f"SELECT source_id FROM {table}").fetchone()[0],
                                 "windows")
        retry = self.sync([usage("second")], source=WSL, coverage="partial")
        self.assertEqual(retry["state"], "needs_review")
        self.assertEqual(self.query()["summary"]["record_count"], 2)
        continued = self.sync(source=WSL, expected_cursor={"offset": 100})
        self.assertEqual(continued["state"], "completed")

    def test_native_history_candidates_do_not_reprice_or_suppress_saved_history(self) -> None:
        self.store.sync_data(source_data(rollups=[rollup()]), metadata(), trust="live")
        self.sync([usage("legacy-same", total_cost_usd="7.12")])
        self.assertEqual(self.query()["summary"]["total_cost_usd"], "1.12345671")
        case = self.store.list_reconciliations()[0]
        self.assertEqual(case["type"], "identity")
        self.store.resolve_reconciliation(case["id"], "same", "已核对历史")
        self.assertEqual(self.store.list_reconciliations(), [])
        self.sync([usage("legacy-same", total_cost_usd="9.13")], source=WSL)
        self.assertEqual(self.store.list_reconciliations(), [])
        self.assertEqual(self.query()["summary"]["total_cost_usd"], "1.12345671")
        on_rollup = int(detail()["created_at"]) - 2 * 86400
        self.sync(
            [usage("rollup-candidate", created_at=on_rollup)], expected_cursor={"offset": 100}
        )
        case = self.store.list_reconciliations()[0]
        self.assertEqual(case["type"], "native_overlap")
        self.assertEqual(self.query()["summary"]["total_cost_usd"], "1.12345671")
        self.store.resolve_reconciliation(case["id"], "current", "保留历史日汇总")
        self.assertEqual(self.query()["summary"]["total_cost_usd"], "1.12345671")

    def test_native_lower_level_evidence_survives_restore_and_positions_restart(self) -> None:
        event = usage("one")
        accepted = self.sync([event])
        archive = self.root / "example.aha-backup"
        backup.create_backup(self.store.data_dir, archive)
        recovered = self.root / "recovered"
        backup.restore_backup(archive, recovered)
        self.store.close()
        self.store = Store(recovered)
        self.addCleanup(self.store.close)
        replayed = self.sync([event])
        self.assertEqual(replayed["unchanged_count"], 1)
        self.assertEqual(replayed["data_revision"], accepted["data_revision"])
        with self.store.read_connection() as database:
            resolved = database.execute("SELECT record_key FROM usage_records").fetchone()[0]
            self.assertEqual(resolved, record_key(event.row))
            self.assertEqual(
                database.execute("SELECT COUNT(*) FROM codex_event_evidence").fetchone()[0], 1
            )

    def test_uncertain_counts_remain_outside_aggregate_until_verified(self) -> None:
        provisional = usage("uncertain")
        provisional.evidence["pending_reason"] = "cumulative_baseline_unconfirmed"
        first = self.sync([provisional], coverage="partial")
        self.assertEqual(first["state"], "needs_review")
        self.assertEqual(self.query("all")["summary"]["record_count"], 0)
        case = self.store.list_reconciliations()[0]
        self.assertEqual(case["choices"], ["current"])
        self.assertEqual(case["pending_reason"], "cumulative_baseline_unconfirmed")
        confirmed = usage("uncertain", output_tokens=15)
        second = self.sync([confirmed], source=WSL)
        self.assertEqual(second["state"], "completed")
        self.assertEqual(self.store.list_reconciliations(), [])
        self.assertEqual(self.query()["summary"]["record_count"], 1)
        self.assertEqual(self.query()["summary"]["output_tokens"], 15)

    def test_matching_snapshot_formats_need_confirmation_without_combining_amounts(self) -> None:
        response = usage("response")
        response.evidence["snapshot_id"] = "same-snapshot"
        self.sync([response])
        snapshot = usage("snapshot", total_cost_usd="9")
        snapshot.evidence.update(kind="snapshot", snapshot_id="same-snapshot")
        self.sync([snapshot], source=WSL)
        self.assertEqual(self.query("all")["summary"]["total_cost_usd"], "0.1234567")
        case = self.store.list_reconciliations()[0]
        self.assertTrue(case["native_snapshot_pair"])
        self.store.resolve_reconciliation(case["id"], "same", "已核对同一调用")
        self.assertEqual(self.store.list_reconciliations(), [])
        self.assertEqual(self.query("all")["summary"]["total_cost_usd"], "0.1234567")

    def test_expanding_cutover_replays_outside_the_original_beijing_day(self) -> None:
        boundary = int(detail()["created_at"]) - 3600
        earlier = usage("before-midnight", created_at=boundary - 1)
        current = usage("at-midnight", created_at=boundary)
        first = self.sync([earlier, current], since="2026-10-26")
        self.assertEqual((first["first_at"], first["last_at"]), (boundary, boundary))
        self.assertEqual((first["events"], first["new_count"]), (1, 1))
        repeated = self.sync(since="2026-10-26", expected_cursor={"offset": 100})
        self.assertEqual(repeated["first_at"], boundary)
        expanded = self.sync([earlier, current], since="2026-10-25", source_id="expanded")
        self.assertEqual((expanded["first_at"], expanded["last_at"]), (boundary - 1, boundary))
        self.assertEqual((expanded["new_count"], expanded["unchanged_count"]), (1, 1))
        self.assertEqual(self.query()["summary"]["record_count"], 2)

    def test_legacy_price_table_does_not_assign_a_basis_to_unpriced_native_events(self) -> None:
        self.store.sync_data(source_data(), metadata(), trust="live")
        self.sync([usage("latest", created_at=int(detail()["created_at"]) + 10, priced=False)])
        analysis = self.query()
        self.assertEqual(analysis["summary"]["record_count"], 2)
        self.assertEqual(analysis["summary"]["unpriced_count"], 1)
        self.assertEqual(analysis["summary"]["total_cost_usd"], "0.1234567")

    def test_confirmed_receipt_checks_history_using_exact_paired_snapshot_second(self) -> None:
        historic = detail()
        self.store.sync_data(source_data([historic]), metadata(), trust="live")
        receipt = usage("same-model-call", created_at=int(historic["created_at"]) + 1)
        receipt.evidence.update(
            snapshot_id="same-model-call-paired", snapshot_timestamp="2026-10-25T17:00:00Z",
        )
        self.sync([receipt])
        case = self.store.list_reconciliations()[0]
        self.assertEqual(case["type"], "identity")
        self.assertEqual(case["current_summary"]["created_at"], historic["created_at"])
        self.assertEqual(self.query("all")["summary"]["total_cost_usd"], "0.1234567")
