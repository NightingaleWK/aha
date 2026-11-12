"""Check frozen synthetic project evidence through native Excel and Edge A4 PDF."""

import argparse
import csv
import hashlib
import json
import os
import zipfile
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    from playwright.sync_api import sync_playwright
    from pypdf import PdfReader
    import pymupdf
    import win32com.client

    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    args = parser.parse_args()
    assert args.label in {"directory", "onefile", "desktop"}
    source = Path(__file__).resolve().parents[4]
    research = source / ".trellis/tasks/11-12-project-record-continuity/research"
    report_path = research / ("native-ui-" + args.label + ".json")
    ui = json.loads(report_path.read_text(encoding="utf-8"))
    assert ui["verified"] and ui["mode"] == "exe" and ui["material"]["member_count"] == 81
    task = Path(os.environ["AHA_QA_ROOT"])
    case = task / ui["case_id"]
    assert case.is_dir() and json.loads((case / "task-ownership.json").read_text())["task"] == "project-record-continuity"
    archive_path = case / "materials/project-c.zip"
    assert sha(archive_path) == ui["material"]["sha256"]
    output = case / ("office-validation-" + uuid4().hex[:6])
    output.mkdir(exist_ok=False)
    names = {"使用明细.csv", "每日汇总.csv", "费用说明.html", "导出信息.json"}
    with zipfile.ZipFile(archive_path) as archive:
        assert set(archive.namelist()) == names
        for name in names:
            (output / name).write_bytes(archive.read(name))
    result = {"verified": False, "executable_sha256": ui["executable_sha256"],
              "material_sha256": ui["material"]["sha256"], "physical_office_input": False,
              "excel": [], "print": {}}
    excel = win32com.client.DispatchEx("Excel.Application")
    excel.Visible = False
    excel.DisplayAlerts = False
    try:
        for filename in ("使用明细.csv", "每日汇总.csv"):
            path = output / filename
            with path.open(encoding="utf-8-sig", newline="") as stream:
                expected = list(csv.reader(stream))
            excel.Workbooks.OpenText(Filename=str(path), Origin=65001, StartRow=1,
                                     DataType=1, TextQualifier=1, ConsecutiveDelimiter=False,
                                     Tab=False, Semicolon=False, Comma=True, Space=False, Other=False,
                                     FieldInfo=tuple((i + 1, 2) for i in range(len(expected[0]))))
            book = excel.ActiveWorkbook
            try:
                sheet = book.Worksheets(1)
                sheet.Columns.AutoFit()
                actual = sheet.UsedRange.Value2
                assert len(actual) == len(expected)
                dates = 0
                for i, row in enumerate(expected):
                    for j, value in enumerate(row):
                        assert not sheet.Cells(i + 1, j + 1).HasFormula
                        observed = actual[i][j]
                        if isinstance(observed, (int, float)):
                            if len(value) == 10 and value[4:5] == "-" and value[7:8] == "-":
                                # Excel auto-detects the daily CSV date as a serial,
                                # even with FieldInfo. Verify its semantic date,
                                # rather than parsing YYYY-MM-DD as a decimal.
                                imported = sheet.Cells(i + 1, j + 1).Value
                                assert imported.date() == datetime.fromisoformat(value).date()
                                assert "#" not in sheet.Cells(i + 1, j + 1).Text
                                dates += 1
                            else:
                                assert Decimal(str(observed)) == Decimal(value)
                        else:
                            assert ("" if observed is None else str(observed)) == value
                result["excel"].append({"file": filename, "rows": len(expected) - 1,
                                         "columns": len(expected[0]), "all_cells_match": True,
                                         "semantic_date_cells": dates, "columns_autofit_for_inspection": True,
                                         "no_formulas": True, "version": str(excel.Version)})
            finally:
                book.Close(SaveChanges=False)
    finally:
        excel.Quit()
    expected_cost = "9.9999927"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", headless=True)
        try:
            page = browser.new_page(locale="zh-CN")
            page.goto((output / "费用说明.html").as_uri())
            body = page.locator("body").inner_text()
            assert expected_cost in body and "归属" in body
            assert "81" in body
            page.screenshot(path=str(output / "report-rendered.png"), full_page=True)
            pdf = output / "project-c-a4.pdf"
            page.pdf(path=str(pdf), format="A4", print_background=True, prefer_css_page_size=True)
        finally:
            browser.close()
    document = PdfReader(pdf)
    text = "\n".join(page.extract_text() for page in document.pages)
    assert expected_cost in text and "归属" in text
    sizes = [[float(page.mediabox.width), float(page.mediabox.height)] for page in document.pages]
    assert sizes and all(abs(w - 595.28) < 2 and abs(h - 841.89) < 2 for w, h in sizes)
    rendered = []
    with pymupdf.open(pdf) as document_image:
        for index, sheet in enumerate(document_image):
            image_path = output / f"a4-page-{index + 1}.png"
            sheet.get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5)).save(image_path)
            rendered.append(str(image_path))
    result["print"] = {"pages": len(document.pages), "a4_page_sizes_pt": sizes,
                       "precise_cost_and_assignment_note_preserved": True,
                       "pdf_sha256": sha(pdf), "pdf_path": str(pdf), "rendered_pages": rendered}
    result["verified"] = True
    result["completed_at"] = datetime.now(timezone(timedelta(hours=8))).isoformat()
    (research / ("native-materials-" + args.label + ".json")).write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
