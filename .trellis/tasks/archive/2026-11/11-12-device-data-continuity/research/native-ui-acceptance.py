"""Native Edge UI and Office checks against an already verified synthetic artifact."""

import argparse
import csv
import hashlib
import json
import os
import runpy
import subprocess
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[4]
    sys.path.insert(0, str(source / "scripts"))
    from verify_windows_artifact import (
        BEIJING, Client, check_shutdown, require, stop_process, wait_descriptor,
    )
    from playwright.sync_api import expect, sync_playwright
    from pypdf import PdfReader
    import win32com.client

    require((args.data_root / ".aha-artifact-verification.json").is_file(), "Unknown fixture")
    profile = args.data_root / "synthetic-profile"
    env = dict(os.environ)
    env.update(USERPROFILE=str(profile), HOME=str(profile), HOMEDRIVE=profile.drive,
               HOMEPATH=str(profile)[len(profile.drive):],
               LOCALAPPDATA=str(profile / "AppData/Local"), APPDATA=str(profile / "AppData/Roaming"),
               TEMP=str(profile / "Temp"), TMP=str(profile / "Temp"))
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    data = args.data_root / "store"
    command = [str(args.exe), "--data-dir", str(data), "--no-browser"]
    process = subprocess.Popen(command, cwd=profile, env=env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    client = None
    with args.exe.open("rb") as stream:
        artifact_sha = hashlib.file_digest(stream, "sha256").hexdigest()
    report = {"verified": False, "executable_sha256": artifact_sha,
              "console_errors": [], "screens": [], "ui_checks": []}
    try:
        descriptor = wait_descriptor(data / "runtime.json", process)
        client = Client(descriptor)
        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path=r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                headless=False, args=["--no-first-run", "--no-default-browser-check"])
            try:
                context = browser.new_context(viewport={"width": 1440, "height": 1000},
                                               locale="zh-CN", timezone_id="America/New_York")
                page = context.new_page()
                page.on("pageerror", lambda error: report["console_errors"].append(str(error)))
                page.goto(descriptor["bootstrap_url"])
                expect(page.locator("#source-mode")).to_have_text("已同步", timeout=30000)
                expect(page.locator("#empty-range-note")).to_be_visible()
                expect(page.locator("#empty-range-description")).to_contain_text("历史数据仍保留")
                page.locator("#view-all-history").click()
                expect(page.locator("#metric-count")).to_have_text("3")
                expect(page.locator("#create-batch")).to_be_disabled()
                report["ui_checks"].append("empty-current-range-and-all-history-readonly")
                page.locator("#backup-options").click()
                expect(page.locator("#backup-dialog")).to_be_visible()
                expect(page.locator("#backup-data-directory")).to_contain_text(str(data))
                for width in (1440, 1366, 1280, 430, 375):
                    page.set_viewport_size({"width": width, "height": 1000})
                    require(page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"),
                            "Backup dialog or page horizontally overflows")
                    page.screenshot(path=str(output / f"backup-{width}.png"))
                    report["screens"].append({"file": f"backup-{width}.png", "width": width})
                page.set_viewport_size({"width": 1440, "height": 1000})
                page.locator("#create-full-backup").click()
                expect(page.locator("#backup-result")).to_contain_text("完整备份已生成", timeout=30000)
                with page.expect_download() as download_event:
                    page.get_by_role("button", name="下载完整备份", exact=True).click()
                saved = output / "synthetic-full.aha-backup"
                download_event.value.save_as(saved)
                require(saved.stat().st_size > 0, "Browser backup download is empty")
                restored = args.data_root / ("browser-restored-" + uuid4().hex[:8])
                page.locator("#restore-file").set_input_files(str(saved))
                page.locator("#restore-destination").fill(str(restored))
                page.locator("#restore-backup").click()
                expect(page.locator("#backup-result")).to_contain_text("已还原到新目录", timeout=30000)
                require((restored / "aha.sqlite3").is_file(), "UI restore did not create a ledger")
                report["ui_checks"].append("generate-download-upload-restore-through-ui")
                restored_process = subprocess.Popen(
                    [str(args.exe), "--data-dir", str(restored), "--no-browser", "--no-tray"],
                    cwd=profile, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                restored_client = None
                try:
                    launch = wait_descriptor(restored / "runtime.json", restored_process)
                    restored_client = Client(launch)
                    restored_page = context.new_page()
                    restored_page.on("pageerror", lambda error: report["console_errors"].append(str(error)))
                    restored_page.goto(launch["bootstrap_url"])
                    expect(restored_page.locator("#bind-default-source")).to_be_visible(timeout=30000)
                    restored_page.locator("#bind-default-source").click()
                    expect(restored_page.locator("#source-binding-dialog")).to_be_visible(timeout=30000)
                    restored_page.locator("#source-binding-reason").fill("合成验收：恢复后保留历史并接续本机来源。")
                    restored_page.get_by_role("button", name="保留历史并接续", exact=True).click()
                    expect(restored_page.locator("#source-mode")).to_have_text("已同步", timeout=30000)
                    restored_page.locator("#view-all-history").click()
                    expect(restored_page.locator("#metric-count")).to_have_text("3")
                    original_batches = client.json("GET", "/api/batches")["batches"]
                    batch_id = original_batches[0].get("id", original_batches[0].get("batch_id"))
                    route = f"/api/batches/{batch_id}/revisions/1/download"
                    require(hashlib.sha256(client.request("GET", route)[2]).digest() ==
                            hashlib.sha256(restored_client.request("GET", route)[2]).digest(),
                            "Restored original material changed")
                    restored_page.screenshot(path=str(output / "restored-and-bound.png"))
                    restored_page.close()
                    check_shutdown(restored_client, restored_process, restored / "runtime.json")
                    report["ui_checks"].append("restored-binding-ui-deduplication-and-original-package")
                finally:
                    stop_process(restored_process, restored_client)
                page.keyboard.press("Escape")
                expect(page.locator("#backup-dialog")).to_be_hidden()
                expect(page.locator("#backup-options")).to_be_focused()
                report["ui_checks"].append("escape-focus-return")
                fixtures = runpy.run_path(str(source / "tests/test_sources.py"))
                event = int(datetime.fromisoformat("2026-10-26T08:00:00+08:00").timestamp())
                candidates = [fixtures["detail"](request_id=f"artifact-{i}", session_id=None,
                              model="合成模型", total_cost_usd="0.290000001", created_at=event+i)
                              for i in range(2)]
                sql = output / ("focus-review-" + uuid4().hex[:6] + ".sql")
                sql.write_bytes(fixtures["dump"](candidates, [], [fixtures["price"]()], version=25))
                page.locator("#sql-file").set_input_files(str(sql))
                expect(page.locator("#reconciliation-count")).to_have_text("2", timeout=30000)
                page.locator("#review-data").click()
                dialog = page.locator("#reconciliation-dialog")
                expect(dialog.locator(".reconciliation-card")).to_have_count(2)
                first = dialog.locator(".reconciliation-card").first
                first.locator("textarea").fill("合成验收：保留已有事实，验证核对后预览和焦点。")
                first.get_by_role("button", name="确认依据", exact=True).click()
                expect(dialog.locator(".reconciliation-card")).to_have_count(1)
                expect(dialog.get_by_role("combobox").first).to_be_focused()
                last = dialog.locator(".reconciliation-card").first
                last.locator("textarea").fill("合成验收：保留已有事实。")
                last.get_by_role("button", name="确认依据", exact=True).click()
                expect(dialog.locator(".reconciliation-card")).to_have_count(0)
                expect(page.locator("#metric-count")).to_have_text("3")
                page.keyboard.press("Escape")
                report["ui_checks"].append("reconciliation-repreview-and-visible-combobox-focus")
                require(not report["console_errors"], "Page JavaScript errors observed")
                report["browser_version"] = browser.version
            finally:
                browser.close()
            renderer = p.chromium.launch(
                executable_path=r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", headless=True)
            try:
                page = renderer.new_page(locale="zh-CN")
                page.goto((args.data_root / "material/费用说明.html").as_uri())
                require("0.570000003" in page.locator("body").inner_text(), "Printed report lost amount")
                page.pdf(path=str(output / "synthetic-material-a4.pdf"), format="A4",
                         print_background=True, prefer_css_page_size=True)
            finally:
                renderer.close()
        pdf = PdfReader(output / "synthetic-material-a4.pdf")
        require("0.570000003" in "\n".join(p.extract_text() for p in pdf.pages), "PDF lost amount")
        sizes = [[float(p.mediabox.width), float(p.mediabox.height)] for p in pdf.pages]
        require(all(abs(w - 595.28) < 2 and abs(h - 841.89) < 2 for w, h in sizes), "PDF is not A4")
        report["print"] = {"pages": len(pdf.pages), "page_sizes_pt": sizes, "precise_amount_preserved": True}
        csv_path = args.data_root / "material/使用明细.csv"
        with csv_path.open(encoding="utf-8-sig", newline="") as stream:
            expected = list(csv.reader(stream))
        excel = win32com.client.DispatchEx("Excel.Application")
        excel.Visible = False
        excel.DisplayAlerts = False
        book = None
        try:
            excel.Workbooks.OpenText(Filename=str(csv_path), Origin=65001, StartRow=1,
                                     DataType=1, TextQualifier=1, ConsecutiveDelimiter=False,
                                     Tab=False, Semicolon=False, Comma=True, Space=False, Other=False,
                                     FieldInfo=tuple((i + 1, 2) for i in range(len(expected[0]))))
            book = excel.ActiveWorkbook
            sheet = book.Worksheets(1)
            actual = sheet.UsedRange.Value2
            require(len(actual) == len(expected), "Excel row count changed")
            numeric = 0
            for i, row in enumerate(expected):
                for j, value in enumerate(row):
                    require(not sheet.Cells(i + 1, j + 1).HasFormula, "Excel interpreted formula")
                    observed = actual[i][j]
                    if isinstance(observed, (int, float)):
                        numeric += 1
                        require(Decimal(str(observed)) == Decimal(value), "Excel numeric content changed")
                    else:
                        require(("" if observed is None else str(observed)) == value, "Excel text changed")
            report["excel"] = {"version": str(excel.Version), "rows": len(actual) - 1,
                                "columns": len(expected[0]), "numeric_cells": numeric,
                                "all_cells_match": True, "no_formulas": True, "method": "native COM"}
        finally:
            if book is not None:
                book.Close(SaveChanges=False)
            excel.Quit()
        check_shutdown(client, process, data / "runtime.json")
        report.update(verified=True, completed_at=datetime.now(BEIJING).isoformat(),
                       tray_enabled=True, tray_physical_checked=False)
    finally:
        stop_process(process, client)
        (output / "ui-office-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
