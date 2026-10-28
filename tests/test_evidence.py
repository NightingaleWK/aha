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
from unittest.mock import patch

from billing_fixtures import seed_analysis
from test_storage_helpers import claim, detail, metadata, rollup, source_data

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

    def package(self, analysis: dict, **values: str) -> tuple[zipfile.ZipFile, str]:
        saved = self.store.create_batch(analysis, claim(**values), "evidence")
        path, filename = self.store.download(saved["id"], saved["version"])
        self.assertIsInstance(path, Path)
        return zipfile.ZipFile(path), filename

    def test_four_files_exact_decimals_member_count_and_content_hashes(self) -> None:
        data = source_data(
            [
                detail(),
                detail("r2", created_at=detail()["created_at"] + 1, total_cost_usd="0.00000003"),
            ],
            [rollup()],
        )
        result = seed_analysis(self.store, data)
        self.assertFalse({"details", "rollups", "members", "daily", "models"} & result.keys())
        package, _ = self.package(result, amount="0.00", amount_note="仅留使用依据")
        with package:
            self.assertEqual(
                set(package.namelist()),
                {"使用明细.csv", "每日汇总.csv", "费用说明.html", "导出信息.json"},
            )
            manifest = json.loads(package.read("导出信息.json"))
            self.assertEqual(manifest["manifest_version"], 3)
            self.assertNotIn("capture_id", manifest)
            self.assertEqual(len(manifest["members"]), 3)
            self.assertEqual(manifest["summary"]["record_count"], 9)
            self.assertEqual(manifest["summary"]["rollup_count"], 1)
            self.assertEqual(manifest["summary"]["total_cost_usd"], "1.12345674")
            self.assertEqual(manifest["claim"]["amount"], "0")
            self.assertEqual(manifest["selection"]["utc_offset"], "+08:00")
            for filename, expected in manifest["files"].items():
                raw = package.read(filename)
                self.assertEqual(hashlib.sha256(raw).hexdigest(), expected["sha256"])
                self.assertEqual(len(raw), expected["bytes"])
            self.assertNotIn("导出信息.json", manifest["files"])
            for name in ("使用明细.csv", "每日汇总.csv"):
                self.assertTrue(package.read(name).startswith(b"\xef\xbb\xbf"))
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
            first = next(row for row in details if row["request_id"] == "r1")
            self.assertEqual(first["time"], "2026-10-26T01:00:00+08:00")
            report = package.read("费用说明.html").decode()
            self.assertIn("1.12345674 USD", report)
            self.assertIn("0 CNY", report)
            self.assertIn("北京时间", report)
            self.assertTrue(manifest["effective_basis"]["effective_when_saved"])

    def test_formula_protection_html_escaping_and_private_field_projection(self) -> None:
        project = self.store.save_project(
            None, '=CMD() <script>alert("x")</script>', "", ["/work/a"]
        )["project"]
        data = source_data([detail(model="@SUM(1,2)")])
        data["source"]["api_key"] = "SECRET-CONFIG"
        result = seed_analysis(self.store, data, project_id=project["id"])
        result["availability"]["private_path"] = "/private/should-not-share"
        package, filename = self.package(result, purpose='<img src=x onerror="attack()">')
        self.assertNotIn("/", filename)
        self.assertNotIn("<", filename)
        with package:
            all_bytes = b"\n".join(package.read(name) for name in package.namelist())
            for private in (
                b"/work/a",
                b"C:\\private",
                b"SECRET-CONFIG",
                b"/private/should-not-share",
            ):
                self.assertNotIn(private, all_bytes)
            rows = list(
                csv.DictReader(io.StringIO(package.read("使用明细.csv").decode("utf-8-sig")))
            )
            self.assertTrue(rows[0]["project_name"].startswith("'=CMD"))
            self.assertEqual(rows[0]["model"], "'@SUM(1,2)")
            report = package.read("费用说明.html").decode()
            self.assertNotIn("<script>", report)
            self.assertNotIn("<img src=x", report)
            self.assertIn("&lt;img", report)
            manifest = json.loads(package.read("导出信息.json"))
            self.assertTrue(all("cwd" not in item for item in manifest["members"]))
            self.assertEqual(manifest["members"][0]["project_id"], project["id"])
            self.assertEqual(manifest["members"][0]["assignment_origin"], "directory_rule")

    def test_report_cost_note_is_not_repeated_and_specific_warning_survives(self) -> None:
        result = seed_analysis(self.store)
        result["warnings"] = [
            "参考成本沿用 CC Switch 保存值，是估算使用价值，不能单独证明实际扣款。",
            "参考成本按 CC Switch 历史记录汇总，申请报销金额由你填写。",
            {"code": "specific", "message": "本期有来源核对说明。", "private": "SECRET"},
        ]
        package, _ = self.package(result)
        with package:
            report = package.read("费用说明.html").decode()
            self.assertEqual(
                report.count("参考成本为 CC Switch 保存的模型用量估算；申请报销金额由申请人填写。"),
                1,
            )
            self.assertIn("本期有来源核对说明。", report)
            self.assertNotIn("参考成本沿用 CC Switch 保存值", report)
            self.assertNotIn(b"SECRET", package.read("导出信息.json"))

    def test_full_selection_export_is_independent_of_visible_page_and_uses_streams(self) -> None:
        rows = [detail(f"r{i}", created_at=detail()["created_at"] + i) for i in range(1201)]
        result = seed_analysis(self.store, source_data(rows, [rollup()]))
        self.assertEqual(len(self.store.analysis_details(result)["rows"]), 50)
        with patch.object(
            Path, "read_bytes", side_effect=AssertionError("whole-file read is forbidden")
        ):
            package, _ = self.package(result)
        with package:
            exported = list(
                csv.DictReader(io.StringIO(package.read("使用明细.csv").decode("utf-8-sig")))
            )
            self.assertEqual(
                {row["request_id"] for row in exported}, {f"r{i}" for i in range(1201)}
            )
            manifest = json.loads(package.read("导出信息.json"))
            self.assertEqual(len(manifest["members"]), 1202)
            self.assertEqual(manifest["summary"]["rollup_record_count"], 7)

    def test_available_export_freezes_exclusions_but_not_private_context(self) -> None:
        first = seed_analysis(self.store)
        self.store.create_batch(first, claim(), "first")
        second = detail("r2", created_at=detail()["created_at"] + 1, total_cost_usd="0.00000003")
        self.store.sync_data(source_data([detail(), second]), metadata(), trust="live")
        result = self.store.analyze("2026-10-26", "2026-10-26")
        package, _ = self.package(result)
        with package:
            manifest = json.loads(package.read("导出信息.json"))
            rows = list(
                csv.DictReader(io.StringIO(package.read("使用明细.csv").decode("utf-8-sig")))
            )
            self.assertEqual([row["request_id"] for row in rows], ["r2"])
            self.assertEqual(manifest["summary"]["total_cost_usd"], "0.00000003")
            self.assertEqual(manifest["availability"]["excluded_summary"]["record_count"], 1)
            self.assertEqual(
                manifest["availability"]["excluded_summary"]["total_cost_usd"], "0.1234567"
            )
            self.assertIn("已排除用量", package.read("费用说明.html").decode())

    def test_amount_validation_and_windows_filename_rules(self) -> None:
        self.assertIsNone(validate_claim(claim(amount=""))["amount"])
        self.assertEqual(validate_claim(claim(amount="0", amount_note="零申请"))["amount"], "0")
        self.assertEqual(
            validate_claim(claim(amount="12.30", amount_note="凭证", currency="USD"))["amount"],
            "12.30",
        )
        for value in ("-1", "NaN", "Infinity", "1.001", "1e2", "+1", 1.2):
            with self.subTest(value=value), self.assertRaises(AppError):
                validate_claim(claim(amount=value, amount_note="依据"))
        with self.assertRaises(AppError):
            validate_claim(claim(amount="1"))
        with self.assertRaises(AppError):
            validate_claim(claim(currency="EUR"))
        self.assertEqual(safe_filename_component("CON"), "_CON")
        self.assertEqual(safe_filename_component("nul.txt"), "_nul.txt")
        self.assertEqual(safe_filename_component("a:b/c?* ."), "a_b_c__")
        self.assertLessEqual(len(safe_filename_component("项" * 500).encode("utf-16-le")) // 2, 80)
