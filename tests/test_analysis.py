from __future__ import annotations

import copy
import json
import unittest
from datetime import datetime
from decimal import Decimal
from typing import Any

from test_sources import detail, dump, price, rollup

from aha.analysis import analyze
from aha.domain import AppError, canonical_bytes, record_key, row_fingerprint
from aha.sql_dump import load_sql_dump


def timestamp(value: str) -> int:
    return int(datetime.fromisoformat(value).timestamp())


def current(**changes: Any) -> dict[str, Any]:
    return detail(created_at=timestamp("2026-10-01T12:00:00+08:00"), **changes)


def source(
    details: list[dict[str, Any]] | None = None,
    rollups: list[dict[str, Any]] | None = None,
    pricing: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return load_sql_dump(
        dump(details, rollups, [price()] if pricing is None else pricing), "fixture.sql"
    )


EMPTY_CONFIG: dict[str, Any] = {"revision": 0, "projects": [], "overrides": {}}
EMPTY_METADATA: dict[str, Any] = {
    "sessions": {},
    "matched_sessions": 0,
    "total_sessions": 0,
    "errors": [],
}


class AnalysisTests(unittest.TestCase):
    def test_all_three_token_semantics_and_cache_anomalies(self) -> None:
        rows = [
            current(request_id="legacy", input_token_semantics=0),
            current(request_id="inclusive", input_token_semantics=1),
            current(request_id="fresh", input_token_semantics=2),
            current(request_id="legacy-anomaly", input_token_semantics=0, input_tokens=10),
            current(request_id="inclusive-anomaly", input_token_semantics=1, input_tokens=45),
        ]
        result = analyze(source(rows), EMPTY_METADATA, EMPTY_CONFIG, "2026-10-01", "2026-10-01")
        by_id = {row["request_id"]: row for row in result["details"]}
        self.assertEqual(
            {key: row["fresh_input_tokens"] for key, row in by_id.items()},
            {
                "legacy": 60,
                "inclusive": 50,
                "fresh": 100,
                "legacy-anomaly": 10,
                "inclusive-anomaly": 45,
            },
        )
        self.assertEqual(result["summary"]["fresh_input_tokens"], 265)
        self.assertEqual(result["summary"]["total_tokens"], 540)
        self.assertTrue(by_id["legacy-anomaly"]["token_anomaly"])
        self.assertTrue(by_id["inclusive-anomaly"]["token_anomaly"])
        self.assertFalse(by_id["fresh"]["token_anomaly"])
        self.assertEqual(by_id["legacy"]["input_tokens"], 100)

    def test_saved_costs_are_exact_and_never_multiplied_or_repriced(self) -> None:
        data = source(
            [
                current(request_id="a", total_cost_usd="0.1000001", cost_multiplier="50"),
                current(request_id="b", total_cost_usd="0.2000002", cost_multiplier="0.3"),
            ],
            pricing=[price(input_cost_per_million="1000")],
        )
        result = analyze(data, EMPTY_METADATA, EMPTY_CONFIG, "2026-10-01", "2026-10-01")
        for row in (result["summary"], result["daily"][0], result["models"][0]):
            self.assertEqual(row["total_cost_usd"], "0.3000003")
        self.assertEqual(result["details"][0]["cost_multiplier"], "50")

    def test_decimal_sum_is_independent_of_process_decimal_context(self) -> None:
        data = source(
            [
                current(request_id="a", total_cost_usd="1e80"),
                current(request_id="b", total_cost_usd="1e-80"),
            ]
        )
        result = analyze(data, EMPTY_METADATA, EMPTY_CONFIG, "2026-10-01", "2026-10-01")
        self.assertEqual(result["summary"]["total_cost_usd"], "1" + "0" * 80 + "." + "0" * 79 + "1")

    def test_beijing_both_dates_month_boundary_and_upper_exclusion(self) -> None:
        moments = (
            ("before", "2026-09-30T15:59:59+00:00"),
            ("first", "2026-09-30T16:00:00+00:00"),
            ("last", "2026-10-01T15:59:59+00:00"),
            ("after", "2026-10-01T16:00:00+00:00"),
        )
        data = source(
            [detail(request_id=key, created_at=timestamp(moment)) for key, moment in moments]
        )
        result = analyze(data, EMPTY_METADATA, EMPTY_CONFIG, "2026-10-01", "2026-10-01")
        self.assertEqual([row["request_id"] for row in result["details"]], ["first", "last"])
        self.assertEqual(result["details"][0]["time"], "2026-10-01T00:00:00+08:00")
        both = analyze(data, EMPTY_METADATA, EMPTY_CONFIG, "2026-09-30", "2026-10-01")
        self.assertEqual(both["summary"]["record_count"], 3)

    def test_leap_day_and_invalid_selection_errors(self) -> None:
        row = detail(created_at=timestamp("2024-02-29T23:59:59+08:00"))
        data = source([row])
        self.assertEqual(
            analyze(data, {}, EMPTY_CONFIG, "2024-02-29", "2024-02-29")["summary"]["record_count"],
            1,
        )
        for start, end in (
            ("2026-02-29", "2026-03-01"),
            ("2026-10-02", "2026-10-01"),
            ("20261001", "2026-10-01"),
            ("2026-1-01", "2026-10-01"),
            ("9999-12-31", "9999-12-31"),
        ):
            with self.subTest(start=start, end=end), self.assertRaises(AppError):
                analyze(data, EMPTY_METADATA, EMPTY_CONFIG, start, end)
        with self.assertRaises(AppError) as error:
            analyze(data, {}, EMPTY_CONFIG, "2026-10-01", "2026-10-01", "missing")
        self.assertEqual(error.exception.status, 404)

    def test_history_grain_counts_and_mixed_source_are_preserved(self) -> None:
        data = source(
            [current(total_cost_usd="0.3")],
            [rollup(date="2026-10-01", request_count=12, total_cost_usd="1.1")],
        )
        result = analyze(data, EMPTY_METADATA, EMPTY_CONFIG, "2026-10-01", "2026-10-01")
        summary = result["summary"]
        self.assertEqual(
            (summary["record_count"], summary["detail_count"], summary["rollup_record_count"]),
            (13, 1, 12),
        )
        self.assertEqual(summary["total_cost_usd"], "1.4")
        self.assertEqual(summary["detail_cost_usd"], "0.3")
        self.assertEqual(summary["rollup_cost_usd"], "1.1")
        self.assertEqual(result["daily"][0]["source_grain"], "mixed")
        self.assertTrue(any("可能重叠" in warning for warning in result["warnings"]))
        self.assertNotIn("created_at", result["rollups"][0])
        self.assertNotIn("session_id", result["rollups"][0])
        self.assertNotIn("time", result["rollups"][0])
        member = next(member for member in result["members"] if member["kind"] == "rollup")
        self.assertEqual(member["data_source"], "codex_session")
        self.assertEqual(member["request_count"], 12)

    def test_daily_models_and_detail_plus_history_totals_agree(self) -> None:
        data = source(
            [
                current(request_id="a", total_cost_usd="0.123456789"),
                current(request_id="b", model="other", total_cost_usd="0.2"),
                detail(
                    request_id="c",
                    created_at=timestamp("2026-10-02T12:00:00+08:00"),
                    total_cost_usd="0.3",
                ),
            ],
            [rollup(total_cost_usd="10.000000001")],
        )
        result = analyze(data, EMPTY_METADATA, EMPTY_CONFIG, "2026-09-01", "2026-10-02")
        expected = Decimal("10.623456790")
        self.assertEqual(Decimal(result["summary"]["total_cost_usd"]), expected)
        for key in ("daily", "models"):
            self.assertEqual(
                sum((Decimal(row["total_cost_usd"]) for row in result[key]), Decimal(0)), expected
            )
            self.assertEqual(sum(row["record_count"] for row in result[key]), 11)
            self.assertEqual(
                sum(row["total_tokens"] for row in result[key]), result["summary"]["total_tokens"]
            )

    def test_missing_prices_zero_is_unpriced_and_nonzero_keeps_history(self) -> None:
        data = source(
            [
                current(request_id="unknown-zero", model="unknown", total_cost_usd="0"),
                current(request_id="unknown-history", model="unknown", total_cost_usd="3.00000001"),
                current(request_id="no-rates", model="no-rates", total_cost_usd="0"),
            ],
            [rollup(model="unknown", request_count=5, total_cost_usd="0")],
            [
                price(
                    model_id="no-rates",
                    input_cost_per_million="0",
                    output_cost_per_million="0",
                    cache_read_cost_per_million="0",
                    cache_creation_cost_per_million="0",
                )
            ],
        )
        result = analyze(data, EMPTY_METADATA, EMPTY_CONFIG, "2026-09-01", "2026-10-01")
        rows = {row["request_id"]: row for row in result["details"]}
        self.assertEqual(rows["unknown-zero"]["pricing_status"], "unpriced")
        self.assertEqual(rows["unknown-history"]["pricing_status"], "missing_basis")
        self.assertEqual(rows["no-rates"]["pricing_status"], "unpriced")
        self.assertEqual(result["summary"]["unpriced_count"], 7)
        self.assertEqual(result["summary"]["total_cost_usd"], "3.00000001")
        self.assertTrue(any("免费" in warning for warning in result["warnings"]))

    def test_pricing_model_takes_precedence_over_reported_model(self) -> None:
        data = source([current(model="alias", pricing_model="m", total_cost_usd="0")])
        result = analyze(data, EMPTY_METADATA, EMPTY_CONFIG, "2026-10-01", "2026-10-01")
        self.assertEqual(result["details"][0]["pricing_status"], "available")

    def test_project_partition_longest_rule_unassigned_and_complete_rollup_override(self) -> None:
        rows = [
            current(request_id="a", session_id="root"),
            current(request_id="b", session_id="child"),
            current(request_id="c", session_id="unknown"),
        ]
        history = rollup(date="2026-10-01")
        data = source(rows, [history])
        metadata = {
            "sessions": {
                "root": {"status": "matched", "cwd": "/work/repo"},
                "child": {"status": "matched", "cwd": "/work/repo/child/module"},
                "unknown": {"status": "matched", "cwd": "/work/repository"},
            }
        }
        config = {
            "revision": 9,
            "projects": [
                {"id": "p1", "name": "根项目", "directories": ["/work/repo", r"C:\repo"]},
                {"id": "p2", "name": "子项目", "directories": ["/work/repo/child"]},
            ],
            "overrides": {
                record_key(history, "rollup"): {
                    "project_id": "p1",
                    "content_hash": row_fingerprint(history, "rollup"),
                }
            },
        }
        all_result = analyze(data, metadata, config, "2026-10-01", "2026-10-01")
        partitions = [
            analyze(data, metadata, config, "2026-10-01", "2026-10-01", item)
            for item in ("p1", "p2", "unassigned")
        ]
        self.assertEqual([row["summary"]["record_count"] for row in partitions], [9, 1, 1])
        self.assertEqual(partitions[0]["rollups"][0]["assignment_origin"], "manual")
        self.assertEqual(partitions[1]["details"][0]["assignment_origin"], "directory_rule")
        for metric in ("record_count", "total_tokens", "fresh_input_tokens"):
            self.assertEqual(
                sum(result["summary"][metric] for result in partitions),
                all_result["summary"][metric],
            )
        self.assertEqual(
            sum(
                (Decimal(result["summary"]["total_cost_usd"]) for result in partitions), Decimal(0)
            ),
            Decimal(all_result["summary"]["total_cost_usd"]),
        )
        keys = [member["key"] for result in partitions for member in result["members"]]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(all_result["classification_revision"], 9)

    def test_unassigned_rollups_do_not_enter_a_specific_project(self) -> None:
        config = {
            "revision": 1,
            "projects": [{"id": "p", "name": "项目", "directories": ["/repo"]}],
            "overrides": {},
        }
        data = source([], [rollup(date="2026-10-01")])
        result = analyze(data, EMPTY_METADATA, config, "2026-10-01", "2026-10-01", "p")
        self.assertEqual(result["summary"]["record_count"], 0)
        self.assertEqual(result["rollups"], [])

    def test_conflicting_or_missing_metadata_stays_unassigned(self) -> None:
        config = {
            "revision": 1,
            "projects": [{"id": "p", "name": "项目", "directories": ["/repo"]}],
            "overrides": {},
        }
        metadata = {"sessions": {"conflict": {"status": "conflict", "cwd": "/repo"}}}
        result = analyze(
            source([current(session_id="conflict")]), metadata, config, "2026-10-01", "2026-10-01"
        )
        self.assertIsNone(result["details"][0]["project_id"])
        self.assertEqual(result["unassigned_record_count"], 1)
        self.assertEqual(result["selection_coverage"]["matched_detail_count"], 0)

    def test_member_identity_survives_repricing_and_semantics_detect_rebuilt_key(self) -> None:
        first = analyze(source([current()]), {}, EMPTY_CONFIG, "2026-10-01", "2026-10-01")
        repriced = analyze(
            source([current(total_cost_usd="8")]), {}, EMPTY_CONFIG, "2026-10-01", "2026-10-01"
        )
        rebuilt = analyze(
            source([current(request_id="rebuilt")]), {}, EMPTY_CONFIG, "2026-10-01", "2026-10-01"
        )
        left, right, new = (result["members"][0] for result in (first, repriced, rebuilt))
        self.assertEqual(left["key"], right["key"])
        self.assertNotEqual(left["content_hash"], right["content_hash"])
        self.assertNotEqual(left["key"], new["key"])
        self.assertEqual(left["semantic_key"], new["semantic_key"])
        self.assertNotIn("cwd", left)

    def test_empty_result_is_explicit_and_serializable(self) -> None:
        result = analyze(source([current()]), {}, EMPTY_CONFIG, "2025-01-01", "2025-01-01")
        self.assertEqual(result["summary"]["total_cost_usd"], "0")
        self.assertEqual(result["summary"]["record_count"], 0)
        self.assertEqual(result["daily"], [])
        self.assertEqual(result["models"], [])
        self.assertTrue(any("没有匹配记录" in warning for warning in result["warnings"]))
        json.loads(canonical_bytes(result))

    def test_full_result_has_no_preview_limit_and_does_not_mutate_sources(self) -> None:
        data = source(
            [current(request_id=f"row-{index}", total_cost_usd="0.00001") for index in range(1005)]
        )
        before = copy.deepcopy(data)
        result = analyze(data, EMPTY_METADATA, EMPTY_CONFIG, "2026-10-01", "2026-10-01")
        self.assertEqual(data, before)
        self.assertEqual(len(result["details"]), 1005)
        self.assertEqual(len(result["members"]), 1005)
        self.assertEqual(result["summary"]["total_cost_usd"], "0.01005")
        self.assertEqual(result["summary"]["record_count"], 1005)


if __name__ == "__main__":
    unittest.main()
