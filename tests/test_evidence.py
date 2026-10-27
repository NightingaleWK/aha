from __future__ import annotations

import csv
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from decimal import Decimal
from pathlib import Path

from test_storage_helpers import analyze_capture, claim, detail, metadata, rollup, source_data

from aha.analysis import analyze
from aha.domain import AppError
from aha.evidence import safe_filename_component, validate_claim
from aha.storage import Store


class EvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temporary.name))

    def tearDown(self) -> None:
        self.store.close()
        self.temporary.cleanup()

    def package(self, analysis: dict, **claim_values: str) -> tuple[zipfile.ZipFile, str]:
        saved = self.store.create_batch(analysis, claim(**claim_values), "evidence-key")
        raw, filename = self.store.download(saved["id"], saved["version"])
        return zipfile.ZipFile(io.BytesIO(raw)), filename

    def test_four_files_have_exact_decimals_matching_preview_and_valid_hashes(self) -> None:
        data = source_data([detail(), detail("r2", total_cost_usd="0.00000003")], [rollup()])
        result = analyze_capture(self.store, data)
        package, _ = self.package(result, amount="0.00", amount_note="本次只留使用证明")
        with package:
            self.assertEqual(
                set(package.namelist()),
                {"使用明细.csv", "每日汇总.csv", "费用说明.html", "导出信息.json"},
            )
            manifest = json.loads(package.read("导出信息.json"))
            for filename, expected in manifest["files"].items():
                self.assertEqual(
                    hashlib.sha256(package.read(filename)).hexdigest(), expected["sha256"]
                )
            self.assertNotIn("导出信息.json", manifest["files"])
            self.assertEqual(manifest["summary"]["total_cost_usd"], "1.12345674")
            self.assertEqual(manifest["claim"]["amount"], "0")
            self.assertEqual(manifest["selection"]["utc_offset"], "+08:00")
            for filename in ("使用明细.csv", "每日汇总.csv"):
                self.assertTrue(package.read(filename).startswith(b"\xef\xbb\xbf"))
            details = list(
                csv.DictReader(io.StringIO(package.read("使用明细.csv").decode("utf-8-sig")))
            )
            daily = list(
                csv.DictReader(io.StringIO(package.read("每日汇总.csv").decode("utf-8-sig")))
            )
            self.assertEqual(len(details), 2)
            self.assertEqual(
                sum(Decimal(row["total_cost_usd"]) for row in details), Decimal("0.12345673")
            )
            self.assertEqual(
                sum(Decimal(row["total_cost_usd"]) for row in daily), Decimal("1.12345674")
            )
            self.assertEqual(details[0]["fresh_input_tokens"], "15")
            self.assertEqual(details[0]["time"], "2026-10-26T01:00:00+08:00")
            report = package.read("费用说明.html").decode("utf-8")
            self.assertIn("1.12345674", report)
            self.assertIn("0 CNY", report)
            self.assertIn("参考成本为 CC Switch 保存的模型用量估算", report)
            self.assertIn("申请报销金额", report)
            self.assertIn("北京时间", report)
            self.assertEqual(manifest["manifest_version"], 2)
            self.assertTrue(manifest["effective_basis"]["effective_when_saved"])

    def test_csv_formula_guard_html_escaping_safe_name_and_private_fields(self) -> None:
        project = self.store.save_project(
            None, '=CMD() <script>alert("x")</script>', "", ["/work/a"]
        )["project"]
        data = source_data([detail(model="@SUM(1,2)")])
        data["source"]["api_key"] = "SECRET-CONFIG"
        result = analyze_capture(self.store, data, project_id=project["id"])
        package, filename = self.package(result, purpose='<img src=x onerror="attack()">')
        self.assertNotIn("/", filename)
        self.assertNotIn("<", filename)
        with package:
            all_bytes = b"\n".join(package.read(name) for name in package.namelist())
            self.assertNotIn(b"/work/a", all_bytes)
            self.assertNotIn(b"C:\\private", all_bytes)
            self.assertNotIn(b"SECRET-CONFIG", all_bytes)
            csv_rows = list(
                csv.DictReader(io.StringIO(package.read("使用明细.csv").decode("utf-8-sig")))
            )
            self.assertTrue(csv_rows[0]["project_name"].startswith("'=CMD"))
            self.assertEqual(csv_rows[0]["model"], "'@SUM(1,2)")
            report = package.read("费用说明.html").decode("utf-8")
            self.assertNotIn("<script>", report)
            self.assertNotIn("<img src=x", report)
            self.assertIn("&lt;img", report)
            manifest = json.loads(package.read("导出信息.json"))
            self.assertTrue(all("cwd" not in member for member in manifest["members"]))
            self.assertTrue(
                all(member["project_id"] == project["id"] for member in manifest["members"])
            )
            self.assertTrue(
                all(
                    member["assignment_origin"] == "directory_rule"
                    for member in manifest["members"]
                )
            )
            self.assertEqual(manifest["source"]["name"], "usage.sql")

    def test_report_explains_reference_cost_once_and_retains_specific_notes(self) -> None:
        result = analyze_capture(self.store)
        old_note = "参考成本沿用 CC Switch 保存值，是估算使用价值，不能单独证明实际扣款。"
        current_note = "参考成本按 CC Switch 历史记录汇总，申请报销金额由你填写。"
        specific_note = "所选日期包含历史来源说明。"
        self.assertIn(current_note, result["warnings"])
        result["warnings"].extend([{"message": old_note}, specific_note])
        package, _ = self.package(result)
        with package:
            report = package.read("费用说明.html").decode("utf-8")
            self.assertEqual(
                report.count("参考成本为 CC Switch 保存的模型用量估算；申请报销金额由申请人填写。"),
                1,
            )
            self.assertNotIn(old_note, report)
            self.assertNotIn(current_note, report)
            self.assertIn(specific_note, report)
            manifest = json.loads(package.read("导出信息.json"))
            self.assertEqual(manifest["warnings"], result["warnings"])

    def test_export_contains_all_rows_and_no_fabricated_rollup_details(self) -> None:
        data = source_data([detail(f"r{i}") for i in range(1201)], [rollup()])
        result = analyze_capture(self.store, data)
        package, _ = self.package(result)
        with package:
            rows = list(
                csv.DictReader(io.StringIO(package.read("使用明细.csv").decode("utf-8-sig")))
            )
            self.assertEqual(len(rows), 1201)
            self.assertEqual({row["request_id"] for row in rows}, {f"r{i}" for i in range(1201)})
            manifest = json.loads(package.read("导出信息.json"))
            self.assertEqual(manifest["summary"]["rollup_record_count"], 7)
            self.assertEqual(len(manifest["members"]), 1202)

    def test_empty_result_cannot_create_a_claim(self) -> None:
        result = analyze_capture(self.store, start_date="2020-01-01", end_date="2020-01-02")
        with self.assertRaises(AppError) as failure:
            self.package(result)
        self.assertEqual(failure.exception.code, "empty_usage")
        self.assertEqual(self.store.list_batches(), [])

    def test_available_export_freezes_exclusions_and_keeps_ledger_private(self) -> None:
        first = analyze_capture(self.store)
        self.store.create_batch(first, claim(), "first-record")
        second = detail("r2", created_at=detail()["created_at"] + 1, total_cost_usd="0.00000003")
        data = source_data([detail(), second])
        capture = self.store.retain(data, metadata())
        loaded = self.store.get_capture(capture["id"])
        result = analyze(
            loaded["data"], loaded["metadata"], self.store.config(),
            "2026-10-26", "2026-10-26", claim_snapshot=self.store.claim_snapshot(),
            availability_mode="available",
        )
        result["capture_id"] = capture["id"]
        result["availability"]["private_path"] = "/private/should-not-share"
        result["availability"]["excluded_groups"][0]["owners"][0]["private_path"] = "SECRET"
        package, _ = self.package(result)
        with package:
            manifest = json.loads(package.read("导出信息.json"))
            rows = list(csv.DictReader(io.StringIO(
                package.read("使用明细.csv").decode("utf-8-sig")
            )))
            self.assertEqual([row["request_id"] for row in rows], ["r2"])
            self.assertEqual(manifest["summary"]["total_cost_usd"], "0.00000003")
            self.assertEqual(manifest["availability"]["mode"], "available")
            excluded = manifest["availability"]["excluded_summary"]
            self.assertEqual(excluded["record_count"], 1)
            self.assertEqual(excluded["total_cost_usd"], "0.1234567")
            self.assertEqual(manifest["effective_basis"]["version"], 1)
            all_bytes = b"\n".join(package.read(name) for name in package.namelist())
            self.assertNotIn(b"/private/should-not-share", all_bytes)
            self.assertNotIn(b"SECRET", all_bytes)
            report = package.read("费用说明.html").decode("utf-8")
            self.assertIn("已排除用量", report)
            self.assertIn("0.00000003 USD", report)
            self.assertIn("0.1234567 USD", report)
            self.assertNotIn("+00:00", report)

    def test_amount_validation_distinguishes_blank_zero_and_invalid_inputs(self) -> None:
        self.assertIsNone(validate_claim(claim(amount=""))["amount"])
        self.assertEqual(validate_claim(claim(amount="0", amount_note="零申请"))["amount"], "0")
        self.assertEqual(
            validate_claim(claim(amount="12.30", amount_note="实付凭证", currency="USD"))["amount"],
            "12.30",
        )
        for amount in ("-1", "NaN", "Infinity", "1.001", "1e2", "+1", 1.2):
            with self.subTest(amount=amount), self.assertRaises(AppError):
                validate_claim(claim(amount=amount, amount_note="依据"))
        with self.assertRaises(AppError):
            validate_claim(claim(amount="1"))
        with self.assertRaises(AppError):
            validate_claim(claim(currency="EUR"))

    def test_windows_filename_rules_cover_reserved_names_and_length(self) -> None:
        self.assertEqual(safe_filename_component("CON"), "_CON")
        self.assertEqual(safe_filename_component("nul.txt"), "_nul.txt")
        self.assertEqual(safe_filename_component("a:b/c?* ."), "a_b_c__")
        self.assertLessEqual(len(safe_filename_component("项" * 500).encode("utf-16-le")) // 2, 80)
