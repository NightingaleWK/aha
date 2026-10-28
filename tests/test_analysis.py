"""Real indexed local queries, exact aggregates and stable paging contracts."""

from __future__ import annotations

import tempfile
import unittest
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from test_storage_helpers import claim, detail, metadata, rollup, source_data

from aha import ledger
from aha.decimal_sql import DecimalSum, IntegerSum
from aha.domain import AppError
from aha.queries import _cursor_encode, _excluded_groups
from aha.storage import Store


class LocalAnalysisTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temporary.name))

    def tearDown(self) -> None:
        self.store.close()
        self.temporary.cleanup()

    def test_exact_decimal_and_tokens_beyond_int64_in_sql_and_statistics(self) -> None:
        rows = [
            detail("a", total_cost_usd="1e100", input_tokens=2**63 - 1, input_token_semantics=2),
            detail("b", total_cost_usd="1e-100", input_tokens=2**63 - 1, input_token_semantics=2),
        ]
        self.store.sync_data(source_data(rows), trust="live")
        result = self.store.analyze("2026-10-26", "2026-10-26")
        accumulator = DecimalSum()
        accumulator.step("1e100")
        accumulator.step("1e-100")
        self.assertEqual(result["summary"]["total_cost_usd"], accumulator.finalize())
        self.assertEqual(result["summary"]["fresh_input_tokens"], 2 * (2**63 - 1))
        integer = IntegerSum()
        integer.step(str(2**63 - 1))
        integer.step(str(2**63 - 1))
        self.assertEqual(integer.finalize(), str(2 * (2**63 - 1)))

    def test_token_semantics_are_counted_once(self) -> None:
        self.store.sync_data(
            source_data([detail(str(n), input_token_semantics=n) for n in (0, 1, 2)])
        )
        result = self.store.analyze("2026-10-26", "2026-10-26")
        self.assertEqual(result["summary"]["fresh_input_tokens"], 20 + 15 + 120)
        self.assertEqual(result["summary"]["total_tokens"], 20 + 15 + 120 + 3 * (10 + 100 + 5))

    def test_keyset_pages_same_second_are_lossless_and_reversible(self) -> None:
        self.store.sync_data(source_data([detail(str(n)) for n in range(121)]))
        analysis = self.store.analyze("2026-10-26", "2026-10-26")
        first = self.store.analysis_details(analysis)
        second = self.store.analysis_details(analysis, cursor=first["next_cursor"])
        third = self.store.analysis_details(analysis, cursor=second["next_cursor"])
        self.assertEqual([len(p["rows"]) for p in (first, second, third)], [50, 50, 21])
        keys = [r["record_key"] for p in (first, second, third) for r in p["rows"]]
        self.assertEqual(len(set(keys)), 121)
        back = self.store.analysis_details(analysis, cursor=third["previous_cursor"])
        self.assertEqual(
            [r["record_key"] for r in back["rows"]], [r["record_key"] for r in second["rows"]]
        )
        self.assertNotIn("details", analysis)
        self.assertNotIn("members", analysis)
        self.assertNotIn("daily", analysis)

    def test_cursor_and_preview_bind_filter_and_revisions(self) -> None:
        self.store.sync_data(source_data([detail(str(n)) for n in range(51)]))
        analysis = self.store.analyze("2026-10-26", "2026-10-26")
        cursor = self.store.analysis_details(analysis)["next_cursor"]
        other = self.store.analyze("2026-10-25", "2026-10-26")
        with self.assertRaises(AppError):
            self.store.analysis_details(other, cursor=cursor)
        self.store.save_project(None, "project", "", [])
        with self.assertRaises(AppError) as error:
            self.store.analysis_details(analysis, cursor=cursor)
        self.assertEqual(error.exception.code, "analysis_expired")

    def test_cursor_seeks_near_position_in_both_directions_and_keeps_date_bounds(self) -> None:
        midnight = detail()["created_at"] - 3600
        rows = [detail(str(n), created_at=midnight + n // 2) for n in range(5000)]
        rows += [detail("before", created_at=midnight - 1),
                 detail("after", created_at=midnight + 86400)]
        self.store.sync_data(source_data(rows), trust="live")
        self.store._db.execute("ANALYZE")
        analysis = self.store.analyze("2026-10-26", "2026-10-26")
        first = self.store.analysis_details(analysis)
        second = self.store.analysis_details(analysis, cursor=first["next_cursor"])
        with self.store.read_connection() as connection:
            boundary = connection.execute(
                "SELECT event_time,record_key FROM usage_records WHERE event_time=? "
                "ORDER BY record_key LIMIT 1", (midnight + 2250,),
            ).fetchone()
        cursor = _cursor_encode(analysis, "detail", list(boundary), "next")
        original_reader = self.store.read_connection
        instructions = 0

        @contextmanager
        def measured_reader():
            nonlocal instructions
            with original_reader() as connection:
                def progress():
                    nonlocal instructions
                    instructions += 100
                    return 0
                connection.set_progress_handler(progress, 100)
                yield connection

        with patch.object(self.store, "read_connection", measured_reader):
            deep = self.store.analysis_details(analysis, cursor=cursor)
            deep_work = instructions
            instructions = 0
            back = self.store.analysis_details(analysis, cursor=second["previous_cursor"])
            back_work = instructions
        self.assertEqual(len(deep["rows"]), 50)
        self.assertTrue(all(row["created_at"] >= midnight + 2250 for row in deep["rows"]))
        self.assertEqual([r["record_key"] for r in back["rows"]],
                         [r["record_key"] for r in first["rows"]])
        self.assertNotIn("before", [row["request_id"] for row in back["rows"]])
        self.assertLess(deep_work, 10000, "deep cursor scanned earlier history")
        self.assertLess(back_work, 10000, "reverse cursor scanned later history")

    def test_decimal_aggregate_fixed_and_exponent_inputs_remain_exact(self) -> None:
        values = ["-0.00000000000000000001", "+12.3400", "1e100", "1e-100", "-9.5", None]
        accumulator = DecimalSum()
        for value in values:
            accumulator.step(value)
        # Decimal's normal addition depends on its precision context; compare an
        # explicit coefficient at the smallest input scale instead.
        numerator = 10**200 + 284 * 10**98 - 10**80 + 1
        expected = str(numerator)
        expected = expected[:-100] + "." + expected[-100:]
        self.assertEqual(accumulator.finalize(), expected)

    def test_beijing_inclusive_date_boundaries(self) -> None:
        row = detail()
        self.store.sync_data(
            source_data([row, detail("next", created_at=row["created_at"] + 86400)])
        )
        day = self.store.analyze("2026-10-26", "2026-10-26")
        self.assertEqual(day["summary"]["record_count"], 1)
        self.assertEqual(len(self.store.analysis_details(day)["rows"]), 1)

    def test_partial_rollup_not_added_to_details_or_fabricated(self) -> None:
        self.store.sync_data(
            source_data(
                [detail(str(n)) for n in range(60)], [rollup(date="2026-10-26", request_count=100)]
            )
        )
        analysis = self.store.analyze("2026-10-26", "2026-10-26", availability_mode="all")
        self.assertEqual(analysis["pending_count"], 61)
        self.assertEqual(analysis["summary"]["record_count"], 0)
        case = self.store.list_reconciliations()[0]
        self.assertEqual(case["detail_count"], 60)
        self.assertEqual(case["rollup_record_count"], 100)
        self.store.resolve_reconciliation(
            case["id"], "rollup", "采用来源完整日汇总", case["generation"]
        )
        result = self.store.analyze("2026-10-26", "2026-10-26")
        self.assertEqual(result["summary"]["record_count"], 100)
        self.assertEqual(result["summary"]["detail_count"], 0)

    def test_aggregate_tabs_are_paged_local_results(self) -> None:
        self.store.sync_data(source_data([detail("a"), detail("b", model="model-b")]), metadata())
        analysis = self.store.analyze("2026-10-26", "2026-10-26")
        for kind in ("daily", "models"):
            first = self.store.analysis_details(analysis, kind=kind, size=1)
            second = self.store.analysis_details(
                analysis, kind=kind, size=1, cursor=first["next_cursor"]
            )
            self.assertEqual(len(first["rows"]), 1)
            self.assertEqual(len(second["rows"]), 1)
            self.assertIsNone(second["next_cursor"])
            self.assertNotEqual(first["rows"][0]["model"], second["rows"][0]["model"])

    def test_no_current_price_recalculation_and_invalid_dates(self) -> None:
        self.store.sync_data(source_data())
        result = self.store.analyze("2026-10-26", "2026-10-26")
        self.assertEqual(result["summary"]["total_cost_usd"], "0.1234567")
        for start, end in (("2026-02-30", "2026-03-01"), ("2026-10-27", "2026-10-26")):
            with self.assertRaises(AppError):
                self.store.analyze(start, end)

    def test_edit_aggregates_use_same_self_exemption_as_rows(self) -> None:
        self.store.sync_data(source_data(), trust="live")
        selected = self.store.analyze("2026-10-26", "2026-10-26")
        saved = self.store.create_batch(selected, claim(), "aggregate-own-claims-00001")
        ordinary = self.store.analyze("2026-10-26", "2026-10-26")
        self.assertEqual(ordinary["summary"]["record_count"], 0)
        own = self.store.analyze(
            "2026-10-26", "2026-10-26", target_batch_id=saved["id"]
        )
        self.assertEqual(own["summary"]["record_count"], 1)
        self.assertEqual(own["availability"]["excluded_summary"]["record_count"], 0)
        self.assertEqual(own["availability"]["excluded_summary"]["total_cost_usd"], "0")
        self.assertEqual(own["availability"]["excluded_groups"], [])
        for kind in ("detail", "daily", "models"):
            page = self.store.analysis_details(own, kind=kind)
            self.assertEqual(len(page["rows"]), 1)
        self.assertEqual(self.store.analysis_details(own)["rows"][0]["usage_state"], "available")

    def test_target_excludes_only_other_owners_with_exact_summary_difference(self) -> None:
        base = detail()["created_at"]
        self.store.sync_data(source_data([
            detail("a", model="unknown", pricing_model="unknown", total_cost_usd="0",
                   input_token_semantics=2,
                   input_tokens=2**63 - 1),
            detail("b", created_at=base + 1, total_cost_usd="0.2"),
            detail("c", created_at=base + 2, total_cost_usd="0.3"),
        ]), trust="live")
        p1 = self.store.save_project(None, "own", "", [])["project"]["id"]
        p2 = self.store.save_project(None, "other", "", [])["project"]["id"]
        rows = self.store.analysis_details(self.store.analyze("2026-10-26", "2026-10-26"))["rows"]
        self.store.assign_keys([row["record_key"] for row in rows if row["request_id"] != "c"], p1)
        self.store.assign_keys([row["record_key"] for row in rows if row["request_id"] == "c"], p2)
        own = self.store.create_batch(self.store.analyze("2026-10-26", "2026-10-26", p1),
                                      claim(), "target-own")
        self.store.create_batch(self.store.analyze("2026-10-26", "2026-10-26", p2),
                                claim(), "target-other")
        result = self.store.analyze("2026-10-26", "2026-10-26", target_batch_id=own["id"])
        basis = result["availability"]
        self.assertEqual(basis["matched_summary"]["record_count"], 3)
        self.assertEqual(basis["available_summary"]["record_count"], 2)
        self.assertEqual(basis["available_summary"]["total_cost_usd"], "0.2")
        self.assertEqual(basis["available_summary"]["unpriced_count"], 1)
        self.assertEqual(basis["excluded_summary"]["record_count"], 1)
        self.assertEqual(basis["excluded_summary"]["total_cost_usd"], "0.3")
        self.assertEqual(basis["excluded_summary"]["unpriced_count"], 0)
        self.assertEqual(sum(group["record_count"] for group in basis["excluded_groups"]), 1)
        readonly = self.store.analyze("2026-10-26", "2026-10-26", target_batch_id=own["id"],
                                      availability_mode="all")
        self.assertEqual(readonly["summary"]["record_count"], 3)
        for key in ("matched_summary", "available_summary", "excluded_summary", "excluded_groups"):
            self.assertEqual(readonly["availability"][key], basis[key])

    def test_target_global_overlap_self_exemption_has_no_negative_exclusion(self) -> None:
        self.store.sync_data(source_data([detail("a"), detail("b")]), trust="live")
        p1 = self.store.save_project(None, "first", "", [])["project"]["id"]
        p2 = self.store.save_project(None, "second", "", [])["project"]["id"]
        all_rows = self.store.analysis_details(
            self.store.analyze("2026-10-26", "2026-10-26")
        )["rows"]
        for row in all_rows:
            self.store.assign_keys([row["record_key"]], p1 if row["request_id"] == "a" else p2)
        saved = self.store.create_batch(self.store.analyze("2026-10-26", "2026-10-26", p1),
                                        claim(), "same-second-owner")
        other = self.store.analyze("2026-10-26", "2026-10-26", p2, target_batch_id=saved["id"])
        self.assertEqual(other["summary"]["record_count"], 1)
        self.assertEqual(other["availability"]["matched_summary"]["record_count"], 1)
        self.assertEqual(other["availability"]["excluded_summary"]["record_count"], 0)
        self.assertEqual(other["availability"]["excluded_groups"], [])

    def test_price_basis_changes_do_not_reprice_saved_cost(self) -> None:
        data = source_data([detail(total_cost_usd="0")])
        self.store.sync_data(data, trust="live")
        before = self.store.analyze("2026-10-26", "2026-10-26")
        self.assertEqual(before["summary"]["unpriced_count"], 0)
        for key in tuple(data["pricing"][0]):
            if key.endswith("per_million"):
                data["pricing"][0][key] = "0"
        self.store.sync_data(data, trust="live")
        result = self.store.analyze("2026-10-26", "2026-10-26")
        self.assertEqual(result["summary"]["total_cost_usd"], "0")
        self.assertEqual(result["summary"]["unpriced_count"], 1)

    def test_monthly_and_day_edges_match_rows_across_leap_day_and_business_changes(self) -> None:
        projects = [self.store.save_project(None, label, "", [f"/work/{label}"])["project"]
                    for label in ("a", "b")]
        days = ["2023-12-31", "2024-01-01", "2024-01-15", "2024-01-31", "2024-02-01",
                "2024-02-28", "2024-02-29", "2024-03-01", "2024-03-15", "2024-03-31",
                "2024-04-01"]
        rows = [detail(str(n), created_at=int(datetime.fromisoformat(day + "T00:00:00+08:00")
                                            .timestamp()),
                       session_id=f"s{n % 2}", total_cost_usd=f"{n}.000000001",
                       input_tokens=2**63 - 1, input_token_semantics=2)
                for n, day in enumerate(days)]
        self.store.sync_data(source_data(rows), {"sessions": {
            "s0": {"cwd": "/work/a", "status": "matched"},
            "s1": {"cwd": "/work/b", "status": "matched"},
        }}, trust="live")
        for start, end in (("2024-01-01", "2024-03-31"), ("2024-01-15", "2024-03-15"),
                           ("2024-02-01", "2024-02-29"), ("2024-02-28", "2024-03-01"),
                           ("2024-02-01", "2024-02-28"), ("2023-12-31", "2024-04-01")):
            for project in ("all", projects[0]["id"]):
                expected = [row for n, row in enumerate(rows) if start <= days[n] <= end
                            and (project == "all" or n % 2 == 0)]
                amount = DecimalSum()
                for row in expected:
                    amount.step(row["total_cost_usd"])
                for mode in ("available", "all"):
                    result = self.store.analyze(start, end, project, availability_mode=mode)
                    self.assertEqual(result["summary"]["record_count"], len(expected))
                    self.assertEqual(result["summary"]["total_cost_usd"], amount.finalize())
                    self.assertEqual(result["summary"]["fresh_input_tokens"],
                                     len(expected) * (2**63 - 1))
        selection = self.store.analyze("2024-02-01", "2024-02-29")
        saved = self.store.create_batch(selection, claim(), "monthly-claim")
        self.assertEqual(
            self.store.analyze("2024-02-01", "2024-02-29")["summary"]["record_count"], 0
        )
        self.assertEqual(self.store.analyze("2024-02-01", "2024-02-29",
                                          availability_mode="all")["summary"], selection["summary"])
        own = self.store.analyze("2024-02-01", "2024-02-29", target_batch_id=saved["id"])
        self.assertEqual(own["summary"], selection["summary"])
        self.assertEqual(
            self.store.analysis_details(own, kind="models")["rows"][0]["record_count"], 3
        )
        self.store.void_batch(saved["id"], saved["generation"], "测试释放", "monthly-void")
        self.assertEqual(self.store.analyze("2024-02-01", "2024-02-29")["summary"],
                         selection["summary"])
        january = self.store.analyze("2024-01-01", "2024-01-31")
        key = self.store.analysis_details(january)["rows"][0]["record_key"]
        self.store.assign_keys([key], projects[0]["id"])
        rows[1]["total_cost_usd"] = "0.000000000000001"
        self.store.sync_data(source_data(rows), trust="live")
        current = self.store.analyze("2024-01-01", "2024-01-31")
        total = DecimalSum()
        for row in rows[1:4]:
            total.step(row["total_cost_usd"])
        self.assertEqual(current["summary"]["total_cost_usd"], total.finalize())
        for start, end in (("0001-01-01", "0001-01-15"), ("9999-12-01", "9999-12-31")):
            self.assertEqual(self.store.analyze(start, end)["summary"]["record_count"], 0)

    def test_monthly_pending_coverage_is_updated_after_explicit_basis_choice(self) -> None:
        self.store.sync_data(source_data([detail()], [rollup(date="2026-10-26")]))
        pending = self.store.analyze("2026-10-01", "2026-10-31")
        self.assertEqual(pending["pending_count"], 2)
        self.assertEqual(pending["summary"]["record_count"], 0)
        case = self.store.list_reconciliations()[0]
        self.store.resolve_reconciliation(case["id"], "detail", "采用已存明细")
        monthly = self.store.analyze("2026-10-01", "2026-10-31")
        daily = self.store.analyze("2026-10-26", "2026-10-26")
        self.assertEqual(monthly["summary"], daily["summary"])
        self.assertEqual(monthly["pending_count"], 0)

    def test_status_and_limited_explanations_use_bounded_projection_work(self) -> None:
        # This fixture isolates projection-query work. Other tests cover deriving
        # these rows from facts, claims and reconciliation transactions.
        projected = []
        expected_counts = {"detail": 0, "rollup": 0, "pending": 0, "represented": 0}
        reference = {}
        start = date(2020, 1, 1)
        end = date(2024, 12, 31)
        for offset in range((end - start).days + 1):
            day = (start + timedelta(days=offset)).isoformat()
            for project in ("", "p1", "p2"):
                for model in ("m0", "m1"):
                    for kind in ("detail", "rollup"):
                        for state in ("available", "claimed", "pending"):
                            represented = 1 if kind == "detail" else 5
                            if (day, project, model, kind, state) == (
                                "2020-01-02", "p2", "m0", "rollup", "claimed"
                            ):
                                represented = 2**63 + 3
                            projected.append((
                                day, project, model, kind, state, 1, str(represented),
                                "10", "2", "3", "0", "15", "0.01", "0",
                            ))
                            expected_counts[kind] += 1
                            if state == "pending":
                                expected_counts["pending"] += 1
                            else:
                                expected_counts["represented"] += represented
                            if state != "available":
                                for selection in ("all", project):
                                    key = (selection, day, model, state)
                                    count, total = reference.get(key, (0, 0))
                                    reference[key] = (count + 1, total + represented)
        with self.store._transaction():
            self.store._db.executemany(
                "INSERT INTO daily_usage_stats VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", projected
            )
            ledger.refresh_monthly(self.store._db)
        self.store._db.execute("ANALYZE")
        original_reader = self.store.read_connection
        instructions = 0

        @contextmanager
        def measured_reader():
            nonlocal instructions
            with original_reader() as connection:
                def progress():
                    nonlocal instructions
                    instructions += 100
                    return 0
                connection.set_progress_handler(progress, 100)
                yield connection

        with patch.object(self.store, "read_connection", measured_reader):
            status = self.store.ledger_status()
        self.assertEqual(status["counts"], {
            "detail_count": expected_counts["detail"], "rollup_count": expected_counts["rollup"],
            "record_count": expected_counts["represented"],
            "pending_count": expected_counts["pending"],
        })
        self.assertEqual(status["coverage"], {"start_date": start.isoformat(),
                                              "end_date": end.isoformat()})
        self.assertLess(instructions, len(projected) * 4, "status scanned full daily projections")
        for project in ("all", "p1", "unassigned"):
            results, work = [], []
            for last in ("2020-01-31", end.isoformat()):
                selection = {"start_date": start.isoformat(), "end_date": last,
                             "project_id": project, "availability_mode": "available"}
                instructions = 0
                with patch.object(self.store, "read_connection", measured_reader):
                    with self.store.read_connection() as connection:
                        groups = _excluded_groups(connection, selection)
                work.append(instructions)
                observed = [(row["date"], row["model"], row["reason"],
                             row["row_count"], row["record_count"]) for row in groups]
                reference_project = "" if project == "unassigned" else project
                expected = [(day, model, "reconciliation" if state == "pending" else "identity",
                             counts[0], counts[1])
                            for (scope, day, model, state), counts in sorted(reference.items())
                            if scope == reference_project and day <= last][:100]
                self.assertEqual(observed, expected)
                results.append(observed)
            self.assertEqual(results[0], results[1])
            self.assertLessEqual(work[1], work[0] + 1000,
                                 "LIMIT 100 still scanned or sorted later history")
