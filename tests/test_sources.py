"""Synthetic historical usage projection and its stable fact identities."""

from __future__ import annotations

import unittest
from typing import Any

from aha.domain import (
    DETAIL_FIELDS,
    ROLLUP_FIELDS,
    AppError,
    build_source_data,
    decimal_text,
    record_key,
    row_fingerprint,
)


def detail(**changes: Any) -> dict[str, Any]:
    return {
        "request_id": "r1",
        "provider_id": "_codex_session",
        "app_type": "codex",
        "model": "m",
        "request_model": None,
        "pricing_model": None,
        "input_tokens": 100,
        "output_tokens": 5,
        "cache_read_tokens": 40,
        "cache_creation_tokens": 10,
        "input_token_semantics": 1,
        "input_cost_usd": "0.1",
        "output_cost_usd": "0.02",
        "cache_read_cost_usd": "0.03",
        "cache_creation_cost_usd": "0.04",
        "total_cost_usd": "0.19",
        "cost_multiplier": "1",
        "created_at": 1790866800,
        "session_id": "s1",
        "data_source": "codex_session",
        **changes,
    }


def rollup(**changes: Any) -> dict[str, Any]:
    return {
        "date": "2026-09-01",
        "provider_id": "_codex_session",
        "app_type": "codex",
        "model": "m",
        "request_model": "",
        "pricing_model": "",
        "request_count": 8,
        "input_tokens": 100,
        "output_tokens": 5,
        "cache_read_tokens": 40,
        "cache_creation_tokens": 10,
        "input_token_semantics": 2,
        "total_cost_usd": "1.23456789",
        **changes,
    }


def price(**changes: Any) -> dict[str, Any]:
    return {
        "model_id": "m",
        "display_name": "模型",
        "input_cost_per_million": "2",
        "output_cost_per_million": "3",
        "cache_read_cost_per_million": "0.1",
        "cache_creation_cost_per_million": "0",
        **changes,
    }


def history_projection(
    details: list[dict[str, Any]] | None = None,
    rollups: list[dict[str, Any]] | None = None,
    pricing: list[dict[str, Any]] | None = None,
    *,
    version: int = 23,
) -> dict[str, Any]:
    return build_source_data(
        [detail()] if details is None else details,
        [] if rollups is None else rollups,
        [price()] if pricing is None else pricing,
        {"kind": "history", "name": "测试历史投影", "source_schema_version": version},
    )


class HistoricalProjectionTests(unittest.TestCase):
    def test_cached_fields_and_money_remain_exact_in_allowed_projection(self) -> None:
        original = detail(
            request_id="记录,';\n旧版", model="m", total_cost_usd="1.234567891234567891e-10",
            cwd="/unrelated/private", message="PRIVATE_DATA",
        )
        normalized = history_projection([original], [rollup()], [price()])
        captured = normalized["details"][0]
        self.assertEqual(captured["request_id"], original["request_id"])
        self.assertEqual(captured["total_cost_usd"], "0.0000000001234567891234567891")
        self.assertEqual(set(captured), set(DETAIL_FIELDS))
        self.assertNotIn("PRIVATE_DATA", str(normalized))
        with self.assertRaises(AppError):
            decimal_text(0.1)

    def test_duplicate_usage_and_price_identities_are_rejected(self) -> None:
        for projections in (
            ([detail(), detail()], [], []),
            ([], [rollup(), rollup()], []),
            ([detail()], [], [price(), price()]),
        ):
            with self.subTest(projections=projections), self.assertRaises(AppError) as error:
                history_projection(*projections)
            self.assertEqual(error.exception.code, "duplicate_key")

    def test_projection_preserves_distinct_same_second_requests(self) -> None:
        records = history_projection([detail(), detail(request_id="r2")])["details"]
        self.assertEqual(len(records), 2)
        self.assertNotEqual(record_key(records[0]), record_key(records[1]))

    def test_irrelevant_app_and_proxy_rows_stay_outside_history(self) -> None:
        data = history_projection(
            [
                detail(),
                detail(request_id="proxy", data_source="proxy", total_cost_usd="not-money"),
                detail(request_id="claude", app_type="claude"),
            ],
            [rollup(), rollup(provider_id="other")],
            [price(), price(model_id="unused")],
        )
        self.assertEqual(len(data["details"]), 1)
        self.assertEqual(len(data["rollups"]), 1)
        self.assertEqual(len(data["pricing"]), 1)

    def test_invalid_historical_token_cost_and_timestamp_values_fail_closed(self) -> None:
        for row in (
            detail(total_cost_usd="NaN"), detail(total_cost_usd=-1),
            detail(input_tokens=-1), detail(output_tokens="1.5"),
            detail(input_token_semantics=3), detail(created_at=253402300800),
            detail(input_tokens=2**64),
        ):
            with self.subTest(row=row), self.assertRaises(AppError):
                history_projection([row])
        for row in (rollup(date="2026-02-30"), rollup(request_count=-1)):
            with self.subTest(row=row), self.assertRaises(AppError):
                history_projection([], [row])


class SourceIdentityTests(unittest.TestCase):
    def test_content_fingerprint_ignores_assignments_but_tracks_saved_cost(self) -> None:
        row = detail()
        changed = {**row, "project_id": "new", "project_name": "新项目", "cwd": "/private"}
        self.assertEqual(row_fingerprint(row), row_fingerprint(changed))
        changed["total_cost_usd"] = "99"
        self.assertEqual(record_key(row), record_key(changed))
        self.assertNotEqual(row_fingerprint(row), row_fingerprint(changed))
        other = rollup(request_model="changed")
        self.assertNotEqual(record_key(rollup(), "rollup"), record_key(other, "rollup"))
        self.assertEqual(set(rollup()), set(ROLLUP_FIELDS))
