"""Legacy rebuild replay against a confirmed, adopted native version."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from native_usage_fixtures import CACHED, COST, INPUT, MODEL, OUTPUT, SESSION, START, write_rollout
from test_storage_helpers import detail, source_data

from aha.codex_sessions import CodexSource
from aha.domain import record_key
from aha.storage import Store


class UsageAdoptionReplayTests(unittest.TestCase):
    def setUp(self) -> None:
        root = Path(self.enterContext(TemporaryDirectory()))
        self.store = Store(root / "ledger")
        self.addCleanup(self.store.close)
        self.legacy = detail(
            "old-legacy-id", created_at=int(START.timestamp()), session_id=SESSION,
            model=MODEL, pricing_model=MODEL, input_tokens=INPUT, output_tokens=OUTPUT,
            cache_read_tokens=CACHED, cache_creation_tokens=0, total_cost_usd="0.099",
        )
        self.store.sync_data(source_data([self.legacy]), source_id="original-legacy")
        write_rollout(root / "codex", 1)
        self.store.sync_codex(CodexSource("windows", str(root / "codex")), "windows")
        page = self.store.reconciliation_page({})
        preview = self.store.preview_reconciliation_batch({
            "filters": {}, "version": page["version"],
        })
        self.assertEqual(preview["candidate_count"], 1)
        self.store.apply_reconciliation_batch({
            "filters": {}, "preview_hash": preview["preview_hash"],
            "reason": "确认原生计价", "idempotency_key": "native-cost-adoption-fixture",
        })

    def test_rebuilt_legacy_key_remains_pending_and_same_preserves_adopted_cost(self) -> None:
        rebuilt = {**self.legacy, "request_id": "rebuilt-legacy-id"}
        result = self.store.sync_data(source_data([rebuilt]), source_id="rebuilt-legacy")
        self.assertEqual((result["new_count"], result["pending_count"]), (1, 1))
        case, = self.store.list_reconciliations()
        self.assertEqual(case["type"], "identity")
        self.assertEqual(case["other_record_key"], record_key(self.legacy))
        self.assertEqual(case["current_summary"]["total_cost_usd"], COST)

        summary = self.store.analyze("2026-10-26", "2026-10-26")["summary"]
        self.assertEqual((summary["record_count"], summary["total_cost_usd"]), (1, COST))
        self.store.resolve_reconciliation(
            case["id"], "same", "确认旧档重建身份", case["generation"], "confirm-rebuild-fixture"
        )
        self.assertEqual(self.store.reconciliation_summary(), {"total": 0})
        repeated = self.store.sync_data(source_data([rebuilt]), source_id="rebuilt-legacy")
        self.assertEqual((repeated["unchanged_count"], repeated["pending_count"]), (1, 0))
        self.assertEqual(self.store.reconciliation_summary(), {"total": 0})
        after = self.store.analyze("2026-10-26", "2026-10-26")["summary"]
        self.assertEqual((after["record_count"], after["total_cost_usd"]), (1, COST))

    def test_same_source_with_both_legacy_keys_preserves_distinct_rows(self) -> None:
        additional = {**self.legacy, "request_id": "distinct-legacy-id"}
        result = self.store.sync_data(
            source_data([self.legacy, additional]), source_id="original-legacy"
        )
        self.assertEqual((result["new_count"], result["unchanged_count"], result["pending_count"]),
                         (1, 1, 0))
        self.assertEqual(self.store.reconciliation_summary(), {"total": 0})
        summary = self.store.analyze("2026-10-26", "2026-10-26")["summary"]
        self.assertEqual((summary["record_count"], summary["total_cost_usd"]), (2, "0.0991305"))
