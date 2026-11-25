"""Precise Beijing selection, detail statistics and immutable range evidence."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

from billing_fixtures import frozen_analysis
from test_storage_helpers import claim, detail, metadata, rollup, source_data

from aha import time_ranges
from aha.claims import member_from_row, scope_key, semantic_key
from aha.decimal_sql import DecimalSum
from aha.domain import AppError, canonical_bytes, content_hash
from aha.queries import _cursor_encode, _filters, _statistics_source
from aha.storage import Store


def moment(value: str) -> datetime:
    return datetime.fromisoformat(value + "+08:00")


def timestamp(value: str) -> int:
    return int(moment(value).timestamp())


def custom(start: str, end: str) -> dict[str, Any]:
    return {"kind": "custom", "start": start, "end": end, "follow_now": False}


def precise_detail(key: str, value: str, **changes: Any) -> dict[str, Any]:
    return detail(key, created_at=timestamp(value), **changes)


class TimeRangeContractTests(unittest.TestCase):
    def test_presets_capture_seconds_and_beijing_calendar_anchor(self) -> None:
        now = moment("2024-03-01T00:00:00").replace(microsecond=987654)
        expected = {
            "today": "2024-03-01T00:00:00+08:00",
            "last_24h": "2024-02-29T00:00:01+08:00",
            "last_7d": "2024-02-24T00:00:00+08:00",
            "last_14d": "2024-02-17T00:00:00+08:00",
            "last_30d": "2024-02-01T00:00:00+08:00",
            "month": "2024-03-01T00:00:00+08:00",
        }
        for preset, start in expected.items():
            with self.subTest(preset=preset):
                value = time_ranges.resolve(
                    {"kind": "preset", "preset": preset, "follow_now": True}, now=now
                ).as_dict()
                self.assertEqual(value["start_at"], start)
                self.assertEqual(value["end_before"], "2024-03-01T00:00:01+08:00")
                self.assertEqual(value["resolved_at"], "2024-03-01T00:00:00+08:00")
        for preset, expected_start in (("today", "2024-02-29"), ("month", "2024-02-01"),
                                       ("last_7d", "2024-02-23")):
            value = time_ranges.resolve({
                "kind": "preset", "preset": preset, "follow_now": False,
                "end_before": "2024-03-01T00:00:00+08:00",
            }, now=now).as_dict()
            self.assertEqual(value["start_at"], expected_start + "T00:00:00+08:00")

    def test_custom_includes_both_minutes_and_single_minute_is_valid(self) -> None:
        result = time_ranges.resolve(custom("2024-02-29T23:59", "2024-02-29T23:59"),
                                     now=moment("2024-03-01T12:00:00"))
        self.assertEqual(result.end_exclusive_epoch - result.start_epoch, 60)
        self.assertEqual(result.as_dict()["end_before"], "2024-03-01T00:00:00+08:00")
        self.assertEqual(result.precision, "minute")
        follow = time_ranges.resolve({"kind": "custom", "start": "2024-02-29T23:59",
                                      "follow_now": True}, now=moment("2024-03-01T00:00:05"))
        self.assertEqual(follow.as_dict()["end_before"], "2024-03-01T00:00:06+08:00")

    def test_invalid_shape_precision_timezone_and_overflow_are_rejected(self) -> None:
        valid = custom("2026-10-26T10:00", "2026-10-26T11:00")
        cases = [
            None, [], {}, {**valid, "extra": 1}, {**valid, "follow_now": 1},
            {**valid, "start": "2026-10-26T10:00:00"},
            {**valid, "start": "2026-10-26T10:00+08:00"},
            {**valid, "start": "2026-02-30T10:00"},
            {**valid, "start": "2026-10-26T11:01"},
            {**valid, "end": "9999-12-31T23:59"},
            {"kind": "custom", "start": "2026-10-27T10:00", "follow_now": True},
            {"kind": "preset", "preset": "nope", "follow_now": True},
            {"kind": "preset", "preset": "today", "follow_now": True, "end_before": "x"},
            {"kind": "preset", "preset": "today", "follow_now": False},
            {"kind": "preset", "preset": "all", "follow_now": True},
            {"kind": "preset", "preset": "last_24h", "follow_now": False,
             "end_before": "0001-01-01T00:00:00+08:00"},
        ]
        for invalid_end in ("2026-10-26T10:00:00Z", "2026-10-26T10:00:00+00:00",
                            "2026-10-26T10:00+08:00", "2026-10-26T10:00:00.1+08:00"):
            cases.append({"kind": "preset", "preset": "today", "follow_now": False,
                          "end_before": invalid_end})
        for value in cases:
            with self.subTest(value=value), self.assertRaises(AppError) as failure:
                time_ranges.resolve(value, now=moment("2026-10-26T12:00:00"))
            self.assertEqual(failure.exception.code, "invalid_time_range")

    def test_partial_pieces_are_disjoint_and_one_day_is_not_counted_twice(self) -> None:
        for start, end, expected_days in (
            ("2024-01-31T12:00", "2024-03-01T12:00", ["2024-01-31", "2024-03-01"]),
            ("2024-02-29T10:00", "2024-02-29T11:00", ["2024-02-29"]),
            ("2024-02-01T00:00", "2024-02-29T23:59", []),
        ):
            interval = time_ranges.resolve(custom(start, end), now=moment("2026-10-26T12:00:00"))
            pieces = interval.partial_days()
            self.assertEqual([p[2].isoformat() for p in pieces], expected_days)
            seconds = sum(last - first for first, last, _ in pieces)
            if full := interval.full_days():
                seconds += ((full[1] - full[0]).days + 1) * 86400
            self.assertEqual(seconds, interval.end_exclusive_epoch - interval.start_epoch)

    def test_non_beijing_clock_and_fixed_preset_keep_same_actual_range(self) -> None:
        intent = {"kind": "preset", "preset": "last_24h", "follow_now": True}
        local = time_ranges.resolve(intent, now=moment("2024-03-01T00:00:05"))
        utc = time_ranges.resolve(intent, now=datetime.fromisoformat("2024-02-29T16:00:05+00:00"))
        self.assertEqual(local.identity(), utc.identity())
        fixed = {**intent, "follow_now": False, "end_before": local.as_dict()["end_before"]}
        much_later = time_ranges.resolve(fixed, now=moment("2026-10-29T20:00:00"))
        self.assertEqual(much_later.identity(), local.identity())


class PreciseLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = Store(self.root)

    def tearDown(self) -> None:
        self.store.close()
        self.temporary.cleanup()

    def all_rows(self, analysis: dict[str, Any], kind: str) -> list[dict[str, Any]]:
        rows = []
        cursor = None
        while True:
            page = self.store.analysis_details(analysis, kind=kind, size=2, cursor=cursor)
            rows.extend(page["rows"])
            cursor = page["next_cursor"]
            if cursor is None:
                return rows

    def assert_totals(self, expected: dict[str, Any], rows: list[dict[str, Any]]) -> None:
        amount = DecimalSum()
        for row in rows:
            amount.step(row["total_cost_usd"])
        self.assertEqual(amount.finalize(), expected["total_cost_usd"])
        for field in ("record_count", "fresh_input_tokens", "output_tokens", "cache_read_tokens",
                      "cache_creation_tokens", "total_tokens"):
            self.assertEqual(sum(row[field] for row in rows), expected[field], field)

    def test_inclusive_end_minute_and_three_views_freeze_same_exact_members(self) -> None:
        rows = [precise_detail(key, when, total_cost_usd=amount, input_token_semantics=2,
                               input_tokens=2**63 - 1)
                for key, when, amount in (
                    ("before", "2026-10-26T09:59:59", "9"),
                    ("start", "2026-10-26T10:00:00", "1e100"),
                    ("end", "2026-10-26T11:00:59", "1e-100"),
                    ("after", "2026-10-26T11:01:00", "8"),
                )]
        self.store.sync_data(source_data(rows), trust="live")
        result = self.store.analyze_time_range(custom("2026-10-26T10:00", "2026-10-26T11:00"))
        selected = self.all_rows(result, "detail")
        self.assertEqual({row["request_id"] for row in selected}, {"start", "end"})
        self.assertEqual(result["row_counts"], {"detail": 2})
        self.assertEqual(result["unassigned_count"], 2)
        for kind in ("daily", "models"):
            self.assert_totals(result["summary"], self.all_rows(result, kind))
        saved = self.store.create_batch(result, claim(), "precise-evidence")
        with zipfile.ZipFile(self.store.download(saved["id"], 1)[0]) as package:
            manifest = json.loads(package.read("导出信息.json"))
            self.assertEqual(manifest["manifest_version"], 5)
            self.assertEqual(manifest["selection"]["time_range"], result["time_range"])
            self.assertTrue(manifest["summary_complete"])
            self.assertEqual(manifest["summary"], result["summary"])
            self.assertEqual({m["created_at"] for m in manifest["members"]},
                             {timestamp("2026-10-26T10:00:00"), timestamp("2026-10-26T11:00:59")})
            exported = list(csv.DictReader(io.StringIO(package.read("使用明细.csv")
                                                       .decode("utf-8-sig"))))
            self.assertEqual({r["request_id"] for r in exported}, {"start", "end"})
            report = package.read("费用说明.html").decode()
            self.assertIn("2026-10-26 10:00:00", report)
            self.assertIn("2026-10-26 11:00:59", report)

    def test_full_month_and_both_partial_days_have_disjoint_detail_stats(self) -> None:
        rows = [precise_detail(str(index), day + "T12:00:00", model="detail-model",
                               total_cost_usd=f"{index}.00000000000001")
                for index, day in enumerate(("2024-01-31", "2024-02-01", "2024-02-28",
                                              "2024-02-29", "2024-03-01"), 1)]
        self.store.sync_data(source_data(rows), trust="live")
        result = self.store.analyze_time_range(custom("2024-01-31T12:00", "2024-03-01T12:00"))
        self.assertEqual(result["summary"]["record_count"], 5)
        self.assertEqual(result["pending_count"], 0)
        self.assertTrue(result["summary_complete"])
        for kind in ("daily", "models"):
            self.assert_totals(result["summary"], self.all_rows(result, kind))
        monthly = self.store.analyze_time_range(custom("2024-01-30T12:00", "2024-03-01T12:00"))
        trend = self.store.analysis_trend(monthly)
        self.assertEqual(trend["grain"], "month")
        self.assertEqual([
            (point["start_date"], point["end_date"], point["total_cost_usd"], point["record_count"])
            for point in trend["points"]
        ], [
            ("2024-01-30", "2024-01-31", "1.00000000000001", 1),
            ("2024-02-01", "2024-02-29", "9.00000000000003", 3),
            ("2024-03-01", "2024-03-01", "5.00000000000001", 1),
        ])
        partial = self.store.analysis_details(result, kind="daily", day="2024-03-01")
        self.assertEqual([row["total_cost_usd"] for row in partial["rows"]],
                         ["5.00000000000001"])
        source, parameters = _statistics_source(result)
        with self.store.read_connection() as connection:
            plan = [row[3] for row in connection.execute(
                "EXPLAIN QUERY PLAN SELECT * FROM " + source, parameters)]
        self.assertTrue(any("monthly_usage_stats" in row and "SEARCH" in row for row in plan))
        self.assertTrue(any("usage_time" in row and "SEARCH" in row for row in plan))
        saved = self.store.create_batch(result, claim(), "partial-month")
        with zipfile.ZipFile(self.store.download(saved["id"], 1)[0]) as package:
            manifest = json.loads(package.read("导出信息.json"))
            self.assertNotIn("time_coverage", manifest)
            self.assertTrue(manifest["summary_complete"])
            self.assertEqual(len(manifest["members"]), 5)
            daily = list(csv.DictReader(io.StringIO(package.read("每日汇总.csv")
                                                    .decode("utf-8-sig"))))
            amount = DecimalSum()
            for row in daily:
                amount.step(row["total_cost_usd"])
            self.assertEqual(amount.finalize(), result["summary"]["total_cost_usd"])
            self.assertNotIn("历史日汇总", package.read("费用说明.html").decode())

    def test_legacy_aggregate_input_leaves_empty_ranges_unavailable_for_saving(self) -> None:
        self.store.sync_data(source_data([], [rollup(date="2026-10-26")]), trust="live")
        result = self.store.analyze_time_range(custom("2026-10-26T10:00", "2026-10-26T11:00"))
        self.assertEqual(result["summary"]["record_count"], 0)
        self.assertEqual(result["summary"]["total_cost_usd"], "0")
        self.assertTrue(result["summary_complete"])
        self.assertNotIn("time_coverage", result)
        self.assertEqual(result["pending_count"], 0)
        self.assertEqual(result["availability"]["excluded_summary"]["total_cost_usd"], "0")
        self.assertEqual(result["availability"]["excluded_groups"], [])
        for kind in ("detail", "daily", "models"):
            self.assertEqual(self.all_rows(result, kind), [])
        self.assertEqual(self.store.analysis_trend(result), {"grain": "day", "points": [{
            "start_date": "2026-10-26", "end_date": "2026-10-26", "total_cost_usd": "0",
            "record_count": 0, "unpriced_count": 0,
        }]})
        with self.assertRaises(AppError) as failure:
            self.store.create_batch(result, claim(), "empty-partial")
        self.assertEqual(failure.exception.code, "empty_usage")
        whole = self.store.analyze_time_range(custom("2026-10-26T00:00", "2026-10-26T23:59"))
        self.assertTrue(whole["summary_complete"])
        self.assertEqual(whole["summary"]["record_count"], 0)
        with self.assertRaises(AppError) as failure:
            self.store.create_batch(whole, claim(), "empty-whole-day")
        self.assertEqual(failure.exception.code, "empty_usage")

    def test_pending_counts_are_scoped_by_project_and_resolved_minute(self) -> None:
        self.store.sync_data(source_data(), trust="live")
        edited = source_data([detail(total_cost_usd="99")])
        edited["source"]["name"] = "other.sql"
        self.store.sync_data(edited)
        selected = custom("2026-10-26T01:00", "2026-10-26T01:00")
        pending = self.store.analyze_time_range(selected, availability_mode="all")
        self.assertEqual(pending["pending_count"], 1)  # Only the actual minute's detail.
        self.assertFalse(pending["summary_complete"])
        self.assertEqual(pending["summary"]["record_count"], 0)
        self.assertEqual(self.store.analysis_trend(pending)["points"][0]["record_count"], 0)
        other = self.store.save_project(None, "other", "", [])['project']['id']
        self.assertTrue(self.store.analyze_time_range(selected, other)["summary_complete"])
        case = self.store.list_reconciliations()[0]
        self.store.resolve_reconciliation(
            case["id"], "current", "已核对逐条依据", case["generation"]
        )
        resolved = self.store.analyze_time_range(selected)
        self.assertTrue(resolved["summary_complete"])
        self.assertEqual(resolved["pending_count"], 0)
        self.assertEqual(resolved["summary"]["record_count"], 1)

    def test_daily_trend_and_scoped_cursors_cover_group_pages_without_narrowing_save(self) -> None:
        event = timestamp("2026-10-26T10:00:00")
        rows = [
            detail(str(index), created_at=event + index, model=f"model-{index:02d}",
                   total_cost_usd="0.00000000000001")
            for index in range(60)
        ]
        rows.append(precise_detail("next-day", "2026-10-27T10:00:00", total_cost_usd="1e-50"))
        self.store.sync_data(source_data(rows), trust="live")
        result = self.store.analyze("2026-10-25", "2026-10-28")
        trend = self.store.analysis_trend(result)
        self.assertEqual(trend["grain"], "day")
        self.assertEqual([point["record_count"] for point in trend["points"]], [0, 60, 1, 0])
        self.assertEqual(trend["points"][1]["total_cost_usd"], "0.0000000000006")
        exact = DecimalSum()
        for point in trend["points"]:
            exact.step(point["total_cost_usd"])
        self.assertEqual(exact.finalize(), result["summary"]["total_cost_usd"])

        day = "2026-10-26"
        first = self.store.analysis_details(result, kind="daily", day=day)
        second = self.store.analysis_details(
            result, kind="daily", day=day, cursor=first["next_cursor"]
        )
        self.assertEqual([len(first["rows"]), len(second["rows"])], [50, 10])
        self.assertEqual({row["date"] for row in first["rows"] + second["rows"]}, {day})
        self.assertIsNone(second["next_cursor"])
        back = self.store.analysis_details(
            result, kind="daily", day=day, cursor=second["previous_cursor"]
        )
        self.assertEqual(back["rows"], first["rows"])
        for selected in (None, "2026-10-27"):
            with self.subTest(day=selected), self.assertRaises(AppError) as failure:
                self.store.analysis_details(
                    result, kind="daily", day=selected, cursor=first["next_cursor"]
                )
            self.assertEqual(failure.exception.code, "invalid_cursor")

        saved = self.store.create_batch(result, claim(), "full-trend-preview")
        with zipfile.ZipFile(self.store.download(saved["id"], 1)[0]) as package:
            manifest = json.loads(package.read("导出信息.json"))
        self.assertEqual(manifest["summary"], result["summary"])
        self.assertEqual(len(manifest["members"]), 61)

    def test_trend_coalesces_long_ranges_and_distinguishes_empty_and_zero_cost(self) -> None:
        self.store.sync_data(source_data([
            precise_detail("old", "1980-04-02T02:00:00", total_cost_usd="0.000000001"),
            precise_detail("today", "2026-10-27T02:00:00", total_cost_usd="0"),
        ]), trust="live")
        result = self.store.analyze("1980-04-02", "2026-10-28")
        trend = self.store.analysis_trend(result)
        self.assertEqual(trend["grain"], "year")
        self.assertEqual(len(trend["points"]), 24)
        first, last = trend["points"][0], trend["points"][-1]
        self.assertEqual((first["start_date"], first["end_date"]), ("1980-04-02", "1981-12-31"))
        self.assertEqual((last["start_date"], last["end_date"]), ("2026-01-01", "2026-10-28"))
        self.assertEqual((first["record_count"], first["total_cost_usd"]), (1, "0.000000001"))
        self.assertEqual((last["record_count"], last["total_cost_usd"]), (1, "0"))
        self.assertTrue(all(point["record_count"] == 0 for point in trend["points"][1:-1]))

    def test_follow_preview_is_resolved_once_save_does_not_call_clock(self) -> None:
        self.store.sync_data(source_data([
            precise_detail("now", "2026-10-26T10:00:00"),
            precise_detail("next", "2026-10-26T10:00:01"),
        ]), trust="live")
        intent = {"kind": "preset", "preset": "today", "follow_now": True}
        with patch("aha.time_ranges.current_time",
                   return_value=moment("2026-10-26T10:00:00")) as clock:
            analysis = self.store.analyze_time_range(intent)
        self.assertEqual(clock.call_count, 1)
        self.assertEqual(analysis["time_range"]["end_before"], "2026-10-26T10:00:01+08:00")
        with patch("aha.time_ranges.current_time", side_effect=AssertionError("save read clock")):
            saved = self.store.create_batch(analysis, claim(), "fixed-preview")
        with zipfile.ZipFile(self.store.download(saved["id"], 1)[0]) as package:
            manifest = json.loads(package.read("导出信息.json"))
            self.assertEqual(manifest["selection"]["time_range"], analysis["time_range"])
            self.assertEqual(len(manifest["members"]), 1)
        with patch("aha.time_ranges.current_time", return_value=moment("2026-10-26T10:00:01")):
            newer = self.store.analyze_time_range(intent, availability_mode="all")
        self.assertEqual(newer["summary"]["record_count"], 2)
        self.assertNotEqual(newer["selection_hash"], analysis["selection_hash"])

    def test_all_uses_local_complete_day_coverage_and_empty_has_no_fake_date(self) -> None:
        intent = {"kind": "preset", "preset": "all", "follow_now": False}
        with self.assertRaises(AppError) as failure:
            self.store.analyze_time_range(intent)
        self.assertEqual(failure.exception.code, "invalid_time_range")
        self.store.sync_data(source_data([detail()], [rollup()]), trust="live")
        result = self.store.analyze_time_range(intent)
        self.assertEqual(result["time_range"]["start_at"], "2026-10-26T00:00:00+08:00")
        self.assertEqual(result["time_range"]["end_before"], "2026-10-27T00:00:00+08:00")
        self.assertTrue(result["summary_complete"])
        self.assertEqual(result["summary"]["record_count"], 1)

    def test_same_range_ignores_display_intent_but_cursor_binds_different_hours(self) -> None:
        self.store.sync_data(source_data([detail(str(n)) for n in range(55)]), trust="live")
        old = self.store.analyze("2026-10-26", "2026-10-26")
        full = self.store.analyze_time_range(custom("2026-10-26T00:00", "2026-10-26T23:59"))
        self.assertEqual(old["selection_hash"], full["selection_hash"])
        a = self.store.analyze_time_range(custom("2026-10-26T01:00", "2026-10-26T01:00"))
        b = self.store.analyze_time_range(custom("2026-10-26T01:00", "2026-10-26T01:01"))
        self.assertEqual(a["summary"], b["summary"])
        for kind in ("detail", "daily", "models"):
            cursor = _cursor_encode(a, kind, ["anything"], "next")
            with self.assertRaises(AppError) as failure:
                self.store.analysis_details(b, kind=kind, cursor=cursor)
            self.assertEqual(failure.exception.code, "invalid_cursor")

    def test_continuous_24h_contains_exact_start_and_last_second_only(self) -> None:
        start, end = "2024-02-29T10:00:01", "2024-03-01T10:00:01"
        first, last = timestamp(start), timestamp(end)
        self.store.sync_data(source_data([
            detail("before", created_at=first - 1), detail("start", created_at=first),
            detail("last", created_at=last - 1), detail("after", created_at=last),
        ]), trust="live")
        result = self.store.analyze_time_range({
            "kind": "preset", "preset": "last_24h", "follow_now": False,
            "end_before": end + "+08:00",
        })
        self.assertEqual({row["request_id"] for row in self.all_rows(result, "detail")},
                         {"start", "last"})
        for kind in ("daily", "models"):
            self.assert_totals(result["summary"], self.all_rows(result, kind))

    def test_new_frozen_incompleteness_does_not_get_rejudged_after_coverage_changes(self) -> None:
        original = detail()
        candidate = detail("candidate", model="other-model")
        self.store.sync_data(source_data([original, candidate]), trust="live")
        adjusted = source_data([original, {**candidate, "total_cost_usd": "99"}])
        adjusted["source"]["name"] = "other.sql"
        self.store.sync_data(adjusted)
        intent = custom("2026-10-26T01:00", "2026-10-26T01:00")
        before = self.store.analyze_time_range(intent)
        first = self.store.create_batch(before, claim(), "incomplete-first")
        case = next(c for c in self.store.list_reconciliations() if c["type"] == "revision")
        self.store.resolve_reconciliation(case["id"], "current", "后续已经核对完整明细")
        current = self.store.analyze_time_range(intent, availability_mode="all")
        self.assertTrue(current["summary_complete"])
        frozen = frozen_analysis(self.store, first["id"])
        changed = self.store.create_batch(frozen, claim(purpose="保留原部分依据"),
                                          "incomplete-revision", first["id"])
        self.assertEqual(changed["summary"], before["summary"])
        self.assertFalse(changed["summary_complete"])
        self.assertEqual(changed["pending_count"], before["pending_count"])
        self.assertEqual(changed["warnings"], before["warnings"])

    def test_exact_target_exemption_and_exclusions_share_partial_range(self) -> None:
        self.store.sync_data(source_data([
            precise_detail("own", "2026-10-26T10:00:00", total_cost_usd="0.1"),
            precise_detail("other", "2026-10-26T10:01:00", total_cost_usd="0.2"),
            precise_detail("outside", "2026-10-26T11:00:00", total_cost_usd="99"),
        ]), trust="live")
        first_range = custom("2026-10-26T10:00", "2026-10-26T10:00")
        own = self.store.create_batch(self.store.analyze_time_range(first_range), claim(), "own")
        self.store.create_batch(self.store.analyze_time_range(
            custom("2026-10-26T10:01", "2026-10-26T10:01")), claim(), "other")
        result = self.store.analyze_time_range(
            custom("2026-10-26T10:00", "2026-10-26T10:01"), target_batch_id=own["id"])
        self.assertEqual(result["summary"]["total_cost_usd"], "0.1")
        self.assertEqual(result["unassigned_count"], 1)
        self.assertEqual(result["availability"]["matched_summary"]["total_cost_usd"], "0.3")
        self.assertEqual(result["availability"]["excluded_summary"]["total_cost_usd"], "0.2")
        self.assertEqual(result["availability"]["excluded_groups"][0]["record_count"], 1)
        for kind in ("daily", "models"):
            self.assert_totals(result["summary"], self.all_rows(result, kind))
        with self.assertRaises(AppError) as failure:
            self.store.create_batch(result, claim(), "wrong-new")
        self.assertEqual(failure.exception.code, "analysis_target_mismatch")

    def test_range_changes_business_identity_without_changing_member_digest(self) -> None:
        self.store.sync_data(source_data(), trust="live")
        selected = self.store.analyze_time_range(custom("2026-10-26T01:00", "2026-10-26T01:00"))
        first = self.store.create_batch(selected, claim(), "first")
        wider = self.store.analyze_time_range(
            custom("2026-10-26T00:59", "2026-10-26T01:00"), target_batch_id=first["id"],
            expected_generation=first["generation"], expected_active_version=1)
        second = self.store.create_batch(wider, claim(), "wider", first["id"])
        self.assertEqual(second["version"], 2)
        revisions = self.store._db.execute(
            "SELECT selection_hash,business_hash FROM revisions ORDER BY version").fetchall()
        self.assertEqual(revisions[0]["selection_hash"], revisions[1]["selection_hash"])
        self.assertNotEqual(revisions[0]["business_hash"], revisions[1]["business_hash"])
        forged = frozen_analysis(self.store, first["id"])
        forged["time_range"]["start_at"] = "2026-10-26T00:58:00+08:00"
        with self.assertRaises(AppError) as failure:
            self.store.create_batch(forged, claim(purpose="changed"), "forged", first["id"])
        self.assertEqual(failure.exception.code, "invalid_analysis")

    def test_partial_day_query_seeks_index_and_work_stays_bounded_by_selected_day(self) -> None:
        target = [detail("target-a"), detail("target-b", created_at=detail()["created_at"] + 1)]
        base = timestamp("2020-01-01T10:00:00")
        history = [detail(f"old-{n}", created_at=base + n * 86400) for n in range(2000)]
        reader = self.store.read_connection
        work = 0

        @contextmanager
        def measured_reader():
            nonlocal work
            with reader() as connection:
                def progress():
                    nonlocal work
                    work += 100
                    return 0
                connection.set_progress_handler(progress, 100)
                yield connection

        observed_work = []
        trend_work = []
        for size in (1000, 2000):
            self.store.sync_data(source_data(history[:size] + target), trust="live")
            self.store._db.execute("ANALYZE")
            work = 0
            with patch.object(self.store, "read_connection", measured_reader):
                result = self.store.analyze_time_range(
                    custom("2026-10-26T01:00", "2026-10-26T01:00"))
                observed_work.append(work)
                work = 0
                trend = self.store.analysis_trend(result)
                trend_work.append(work)
            self.assertEqual(result["summary"]["record_count"], 2)
            self.assertEqual(trend["points"][0]["record_count"], 2)
        self.assertLessEqual(observed_work[1], observed_work[0] + 1000)
        self.assertLess(observed_work[1], 10000)
        self.assertLessEqual(trend_work[1], trend_work[0] + 1000)
        self.assertLess(trend_work[1], 10000)
        where, parameters = _filters(result)
        with reader() as connection:
            plan = [r[3] for r in connection.execute(
                "EXPLAIN QUERY PLAN SELECT r.record_key FROM usage_records r WHERE " + where,
                parameters)]
        self.assertTrue(any("SEARCH" in row and "event_time>?" in row for row in plan), plan)

    def test_precise_deep_keyset_seeks_and_reverse_keeps_original_seconds(self) -> None:
        base = timestamp("2026-10-26T01:00:00")
        rows = [detail(str(n), created_at=base + n // 2) for n in range(3200)]
        rows.extend([detail("before", created_at=base - 1),
                     detail("after", created_at=base + 31 * 60)])
        self.store.sync_data(source_data(rows), trust="live")
        self.store._db.execute("ANALYZE")
        analysis = self.store.analyze_time_range(custom("2026-10-26T01:00", "2026-10-26T01:30"))
        first = self.store.analysis_details(analysis)
        second = self.store.analysis_details(analysis, cursor=first["next_cursor"])
        boundary = self.store._db.execute(
            "SELECT event_time,record_key FROM usage_records WHERE event_time=? "
            "ORDER BY record_key LIMIT 1", (base + 1500,),
        ).fetchone()
        cursor = _cursor_encode(analysis, "detail", list(boundary), "next")
        reader = self.store.read_connection
        instructions = 0

        @contextmanager
        def measured_reader():
            nonlocal instructions
            with reader() as connection:
                def progress():
                    nonlocal instructions
                    instructions += 100
                    return 0
                connection.set_progress_handler(progress, 100)
                yield connection

        with patch.object(self.store, "read_connection", measured_reader):
            deep = self.store.analysis_details(analysis, cursor=cursor)
            forward_work = instructions
            instructions = 0
            back = self.store.analysis_details(analysis, cursor=second["previous_cursor"])
            reverse_work = instructions
        self.assertEqual(len(deep["rows"]), 50)
        self.assertTrue(all(base + 1500 <= row["created_at"] < base + 31 * 60
                            for row in deep["rows"]))
        self.assertEqual(back["rows"], first["rows"])
        self.assertLess(forward_work, 10000)
        self.assertLess(reverse_work, 10000)

    def test_independent_v3_zip_and_frozen_rows_survive_new_writer_and_fact_changes(self) -> None:
        # Construct the old persisted contract directly. Neither analyze() nor
        # create_batch()/build_evidence() creates this fixture, so the current
        # writer cannot accidentally stand in for compatibility evidence.
        data = source_data()
        self.store.sync_data(data, metadata(), trust="live")
        record = self.store._db.execute("SELECT * FROM usage_records").fetchone()
        original_row = {
            **data["details"][0], "kind": "detail", "record_key": record["record_key"],
            "version_id": record["version_id"], "content_fingerprint": record["content_hash"],
            "date": "2026-10-26", "time": "2026-10-26T01:00:00+08:00",
            "project_id": None, "project_name": "未归属", "assignment_origin": "unassigned",
            "fresh_input_tokens": 15, "total_tokens": 130, "pricing_status": "available",
        }
        summary = {
            "record_count": 1, "detail_count": 1, "rollup_record_count": 0, "rollup_count": 0,
            "unpriced_count": 0, "fresh_input_tokens": 15, "output_tokens": 10,
            "cache_read_tokens": 100, "cache_creation_tokens": 5, "total_tokens": 130,
            "total_cost_usd": "0.1234567", "detail_cost_usd": "0.1234567",
            "rollup_cost_usd": "0", "source_grain": "detail",
        }
        frozen_json = canonical_bytes(original_row).decode()
        selection_hash = hashlib.sha256(frozen_json.encode() + b"\n").hexdigest()
        analysis = {
            "start_date": "2026-10-26", "end_date": "2026-10-26", "project_id": "all",
            "project_name": "全部项目", "timezone": "Asia/Shanghai", "data_revision": 1,
            "classification_revision": 0, "claim_revision": 0,
            "warnings": ["旧记录存在原始说明，历史完整性未保存。"], "summary": summary,
            "member_count": 1, "selection_hash": selection_hash, "availability_mode": "available",
        }
        original_analysis_json = canonical_bytes(analysis).decode()
        batch = {"id": "legacy-v3", "number": "AHA-000001", "version": 1,
                 "created_at": "2026-10-26T02:00:00+00:00"}
        member = member_from_row(original_row, "detail")
        member.update(version_id=record["version_id"], project_id=None, project_name="未归属",
                      assignment_origin="unassigned", pricing_status="available")
        files = {
            "使用明细.csv": (b"\xef\xbb\xbftime,total_cost_usd\r\n"
                              b"2026-10-26T01:00:00+08:00,0.1234567\r\n"),
            "每日汇总.csv": b"\xef\xbb\xbfdate,total_cost_usd\r\n2026-10-26,0.1234567\r\n",
            "费用说明.html": "<!doctype html><meta charset=utf-8><p>旧版费用说明</p>".encode(),
        }
        manifest = {
            "manifest_version": 3, "batch": batch, "selection": {
                "start_date": "2026-10-26", "end_date": "2026-10-26",
                "timezone": "Asia/Shanghai", "utc_offset": "+08:00", "project_id": "all",
                "project_name": "全部项目",
            }, "summary": summary, "members": [member], "claim": claim(),
            "selection_hash": selection_hash,
            "files": {name: {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
                      for name, raw in files.items()},
        }
        path = self.root / "packages" / "original-v3.zip"
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as package:
            for name, raw in files.items():
                package.writestr(name, raw)
            package.writestr("导出信息.json", canonical_bytes(manifest))
        original_bytes = path.read_bytes()
        original_sha = hashlib.sha256(original_bytes).hexdigest()
        business_hash = content_hash({"selection_hash": selection_hash, "claim": claim(),
                                      "selection": {key: analysis[key] for key in (
                                          "start_date", "end_date", "project_id", "project_name")},
                                      "summary": summary})
        with self.store._transaction():
            self.store._db.execute("INSERT INTO batches VALUES(?,?,?,?,?,?,?,?)", (
                batch["id"], 1, batch["created_at"], 1, "active", 1, None, None,
            ))
            self.store._db.execute("INSERT INTO revisions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                batch["id"], 1, batch["created_at"], "draft", batch["created_at"],
                original_analysis_json, canonical_bytes(claim()).decode(), selection_hash,
                business_hash, "packages/original-v3.zip", original_sha, "旧版材料_v1.zip",
                content_hash({"analysis": analysis, "batch": batch, "claim": claim()}),
            ))
            self.store._db.execute("INSERT INTO revision_members VALUES(?,?,?,?,?,?,?,?,?)", (
                batch["id"], 1, record["record_key"], record["version_id"], "detail",
                scope_key(member), semantic_key(member), canonical_bytes(member).decode(),
                frozen_json,
            ))
            self.store._db.execute("INSERT INTO usage_claims VALUES(?,?,?,?,?,?,?)", (
                record["record_key"], batch["id"], 1, "detail", scope_key(member),
                semantic_key(member), canonical_bytes(member).decode(),
            ))
            self.store._db.execute("UPDATE billing_sequence SET next_number=2 WHERE id=1")
            self.store._db.execute("UPDATE settings SET value='1' WHERE key='claim_revision'")
            self.store.refresh_availability(self.store._db)
        self.store.close()
        self.store = Store(self.root)
        old = self.store.batch_detail(batch["id"])
        self.assertEqual(old["time_range"]["intent"]["kind"], "legacy_dates")
        self.assertIsNone(old["summary_complete"])
        self.assertNotIn("time_coverage", old)
        self.assertIsNone(old["assignment_coverage"])
        self.assertIsNone(old["revisions"][0]["analysis"]["assignment_coverage"])
        self.assertEqual(old["warnings"], analysis["warnings"])
        self.assertEqual(self.store.download(batch["id"], 1)[0].read_bytes(), original_bytes)
        unchanged = self.store.create_batch(
            frozen_analysis(self.store, batch["id"]), claim(), "legacy-no-change", batch["id"],
        )
        self.assertEqual(unchanged["version"], 1)
        self.store.sync_data(source_data([detail(total_cost_usd="99")]), metadata(), trust="live")
        frozen = frozen_analysis(self.store, batch["id"])
        revised = self.store.create_batch(frozen, claim(purpose="仅补充用途"), "legacy-revise",
                                         batch["id"])
        self.assertEqual(revised["version"], 2)
        detail_summary = {key: value for key, value in summary.items()
                          if key not in {"rollup_record_count", "rollup_count", "rollup_cost_usd",
                                         "detail_cost_usd"}}
        self.assertEqual(revised["summary"], detail_summary)
        self.assertIsNone(revised["summary_complete"])
        self.assertIsNone(revised["assignment_coverage"])
        with zipfile.ZipFile(self.store.download(batch["id"], 2)[0]) as package:
            new_manifest = json.loads(package.read("导出信息.json"))
            self.assertEqual(new_manifest["manifest_version"], 5)
            self.assertEqual(new_manifest["summary"], detail_summary)
            self.assertNotIn("time_coverage", new_manifest)
            self.assertIsNone(new_manifest["summary_complete"])
            self.assertIsNone(new_manifest["assignment_coverage"])
            self.assertEqual(new_manifest["selection_hash"], selection_hash)
            self.assertEqual(new_manifest["members"][0]["version_id"], record["version_id"])
            report = package.read("费用说明.html").decode()
            self.assertIn("沿用旧记录的冻结用量与说明，未重新判断历史资料完整性", report)
            self.assertIn(analysis["warnings"][0], report)
        raw = self.store._db.execute(
            "SELECT analysis_json FROM revisions WHERE batch_id=? AND version=1", (batch["id"],)
        ).fetchone()[0]
        self.assertEqual(raw, original_analysis_json)
        submitted = self.store.set_status(batch["id"], 2, "submitted", revised["generation"])
        withdrawn = self.store.withdraw_batch(
            batch["id"], submitted["generation"], "补充说明", "back"
        )
        self.store.void_batch(batch["id"], withdrawn["generation"], "纠正材料", "void-old")
        self.assertEqual(hashlib.sha256(self.store.download(batch["id"], 1)[0].read_bytes())
                         .hexdigest(), original_sha)
