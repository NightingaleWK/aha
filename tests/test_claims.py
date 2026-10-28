from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from billing_fixtures import seed_analysis
from test_storage_helpers import detail, rollup

from aha.claims import evaluate, indexed_exclusion, member_from_row, scope_key, semantic_key
from aha.domain import AppError
from aha.storage import Store


def owned(member: dict, batch: str = "a", version: int = 1) -> dict:
    return {
        "member": member,
        "owner": {
            "batch_id": batch,
            "number": "AHA-000001",
            "version": version,
            "status": "draft",
            "lifecycle": "active",
        },
    }


class ClaimAlgorithmTests(unittest.TestCase):
    def test_exact_identity_and_explicit_self_exemption(self) -> None:
        row = member_from_row(detail(), "detail")
        snapshot = {"claim_revision": 4, "claims": [owned(row)], "legacy_holds": []}
        excluded = evaluate([row], snapshot)
        self.assertEqual(excluded["available_keys"], [])
        self.assertEqual(excluded["excluded"][0]["reason"], "identity")
        self.assertEqual(excluded["claim_revision"], 4)
        self.assertEqual(evaluate([row], snapshot, "a")["available_keys"], [row["key"]])

    def test_disjoint_details_same_date_model_stay_available(self) -> None:
        first = member_from_row(detail(), "detail")
        second = member_from_row(detail("other", created_at=detail()["created_at"] + 1), "detail")
        snapshot = {"claims": [owned(first)]}
        self.assertEqual(scope_key(first), scope_key(second))
        self.assertEqual(evaluate([second], snapshot)["available_keys"], [second["key"]])

    def test_rebuilt_key_is_ambiguous_but_distinct_keys_are_not_auto_merged(self) -> None:
        first = member_from_row(detail(), "detail")
        second = member_from_row(detail("new-id"), "detail")
        self.assertEqual(semantic_key(first), semantic_key(second))
        self.assertEqual(
            evaluate([second], {"claims": [owned(first)]})["excluded"][0]["reason"],
            "suspected_rebuild",
        )
        self.assertEqual(len(evaluate([first, second], {})["available_keys"]), 2)

    def test_internal_cross_grain_group_excludes_every_affected_member_only(self) -> None:
        first = member_from_row(detail(), "detail")
        history = member_from_row(rollup(date=first["date"]), "rollup")
        separate = member_from_row(detail("separate", model="model-b"), "detail")
        result = evaluate([first, history, separate], {})
        self.assertEqual(result["available_keys"], [separate["key"]])
        self.assertEqual(
            {item["key"] for item in result["excluded"]}, {first["key"], history["key"]}
        )
        self.assertEqual({item["reason"] for item in result["excluded"]}, {"internal_overlap"})

    def test_cross_grain_is_symmetric_and_rollup_scope_blocks_changed_keys(self) -> None:
        first = member_from_row(detail(), "detail")
        history = member_from_row(rollup(date=first["date"]), "rollup")
        self.assertEqual(
            evaluate([history], {"claims": [owned(first)]})["excluded"][0]["reason"], "cross_grain"
        )
        self.assertEqual(
            evaluate([first], {"claims": [owned(history)]})["excluded"][0]["reason"], "cross_grain"
        )
        changed = member_from_row(rollup(date=first["date"], pricing_model="different"), "rollup")
        self.assertEqual(
            evaluate([changed], {"claims": [owned(history)]})["excluded"][0]["reason"],
            "rollup_scope",
        )

    def test_derived_total_tokens_can_exceed_one_source_integer(self) -> None:
        maximum = 2**63 - 1
        member = member_from_row(
            detail(
                input_tokens=maximum,
                output_tokens=maximum,
                cache_read_tokens=maximum,
                cache_creation_tokens=maximum,
                input_token_semantics=2,
            ),
            "detail",
        )
        self.assertEqual(member["total_tokens"], maximum * 4)
        self.assertEqual(evaluate([member], {})["available_keys"], [member["key"]])

    def test_duplicate_or_invalid_members_fail_closed(self) -> None:
        member = member_from_row(detail(), "detail")
        for bad in (
            [member, member],
            [{**member, "date": "invalid"}],
            [{**member, "total_tokens": 0}],
        ):
            with self.assertRaises(AppError):
                evaluate(bad, {})

    def test_indexed_explanations_match_identity_semantic_scope_and_self_rules(self) -> None:
        from test_storage_helpers import claim

        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder))
            try:
                saved = store.create_batch(seed_analysis(store), claim(), "first")
                first = member_from_row(detail(), "detail")
                candidates = [
                    first,
                    member_from_row(detail("new-id"), "detail"),
                    member_from_row(rollup(date=first["date"]), "rollup"),
                    member_from_row(
                        detail("independent", created_at=detail()["created_at"] + 1), "detail"
                    ),
                ]
                snapshot = {"claims": [owned(first, saved["id"])]}
                with store.read_connection() as connection:
                    for candidate in candidates:
                        expected = evaluate([candidate], snapshot)["excluded"]
                        actual = indexed_exclusion(connection, candidate)
                        self.assertEqual(
                            actual["reason"] if actual else None,
                            expected[0]["reason"] if expected else None,
                        )
                        self.assertIsNone(indexed_exclusion(connection, candidate, saved["id"]))
            finally:
                store.close()
