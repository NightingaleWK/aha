"""Exercise CCS26 in Edge and frozen synthetic materials in Excel/A4 PDF."""

from __future__ import annotations

import argparse
import csv
import json
import os
import runpy
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4


SOURCE = Path(__file__).resolve().parents[4]
RESEARCH = Path(__file__).resolve().parent
ROOT = Path(os.environ["AHA_CCS26_ROOT"])
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
sys.path.insert(0, str(SOURCE / "scripts"))
import verify_windows_artifact as artifact


def ui(executable, label):
    from playwright.sync_api import expect, sync_playwright

    case = ROOT / ("ui-" + label + "-" + uuid4().hex[:8])
    env, profile = artifact.isolated_environment(case)
    fixtures = runpy.run_path(str(SOURCE / "tests/test_sources.py"))
    event = int(datetime.now(timezone.utc).timestamp()) - 60
    rows = [fixtures["detail"](request_id=f"ui26-{n}", session_id=None,
        model="合成模型", total_cost_usd="0.190000001", created_at=event+n) for n in range(3)]
    source = profile / ".cc-switch/cc-switch.db"
    fixtures["database"](source, rows, version=26).close()
    descriptor = case / "store/runtime.json"
    process = subprocess.Popen([str(executable), "--data-dir", str(descriptor.parent), "--no-browser"],
        cwd=profile, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    client = None
    try:
        launch = artifact.wait_descriptor(descriptor, process)
        client = artifact.Client(launch)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=EDGE, headless=True)
            try:
                page = browser.new_page(locale="zh-CN", viewport={"width":1440,"height":1000})
                page.goto(launch["bootstrap_url"])
                expect(page.locator("#source-mode")).to_have_text("已同步", timeout=30000)
                assert not page.locator("#sync-error").is_visible()
                before = client.json("GET", "/api/ledger")
                assert before["counts"]["detail_count"] == 3
                assert before["last_sync"]["source_schema_version"] == 26
                with closing(sqlite3.connect(source)) as connection:
                    connection.execute("PRAGMA user_version=27")
                    connection.commit()
                page.locator("#load-default").click()
                expect(page.locator("#source-mode")).to_have_text("同步失败", timeout=30000)
                error = page.locator("#sync-error").inner_text()
                assert "27" in error and "23、24、25、26" in error and "已保存的本地数据" in error
                failed = client.json("GET", "/api/ledger")
                assert failed["counts"] == before["counts"]
                assert failed["last_successful_sync_at"] == before["last_successful_sync_at"]
                with closing(sqlite3.connect(source)) as connection:
                    connection.execute("PRAGMA user_version=26")
                    connection.commit()
                page.locator("#load-default").click()
                expect(page.locator("#source-mode")).to_have_text("已同步", timeout=30000)
                assert not page.locator("#sync-error").is_visible()
                recovered = client.json("GET", "/api/ledger")
                assert recovered["counts"] == before["counts"]
                assert recovered["last_sync"]["source_schema_version"] == 26
                screenshot = RESEARCH / ("ui-"+label+".png")
                page.screenshot(path=str(screenshot), full_page=True)
            finally:
                browser.close()
        artifact.check_shutdown(client, process, descriptor)
        return {"verified":True,"browser":"native Edge headless","executable_sha256":artifact.digest(executable),
            "ccs26_startup":True,"unknown27_ui_failure_history_preserved":True,"ccs26_manual_recovery":True,
            "duplicate_usage":False,"shutdown_descriptor_cleaned":not descriptor.exists(),
            "screenshot":screenshot.name,"real_profile_used":False,"tray_enabled":True,
            "physical_tray_input":False}
    finally:
        artifact.stop_process(process, client)


def office(label):
    import win32com.client
    from playwright.sync_api import sync_playwright
    from pypdf import PdfReader
    import pymupdf

    material = ROOT / ("verify-" + label) / "material"
    manifest = json.loads((material / "导出信息.json").read_text(encoding="utf-8"))
    expected_cost = manifest["summary"]["total_cost_usd"]
    assert Decimal(expected_cost) == Decimal("0.570000003")
    result = {"verified":False,"material_sha256":artifact.digest(material/"evidence.zip"),
              "physical_office_input":False,"native_excel":[],"print":{}}
    excel = win32com.client.DispatchEx("Excel.Application")
    excel.Visible = False
    excel.DisplayAlerts = False
    try:
        for filename in ("使用明细.csv","每日汇总.csv"):
            with (material/filename).open(encoding="utf-8-sig",newline="") as stream:
                expected = list(csv.reader(stream))
            excel.Workbooks.OpenText(Filename=str(material/filename),Origin=65001,StartRow=1,
                DataType=1,TextQualifier=1,ConsecutiveDelimiter=False,Tab=False,Semicolon=False,
                Comma=True,Space=False,Other=False,
                FieldInfo=tuple((i+1,2) for i in range(len(expected[0]))))
            book = excel.ActiveWorkbook
            try:
                sheet = book.Worksheets(1)
                sheet.Columns.AutoFit()
                actual = sheet.UsedRange.Value2
                assert len(actual) == len(expected)
                for i,row in enumerate(expected):
                    for j,value in enumerate(row):
                        cell = sheet.Cells(i+1,j+1)
                        assert not cell.HasFormula
                        observed = actual[i][j]
                        if isinstance(observed,(int,float)):
                            if len(value)==10 and value[4:5]=="-" and value[7:8]=="-":
                                assert cell.Value.date() == datetime.fromisoformat(value).date()
                                assert "#" not in cell.Text
                            else:
                                assert Decimal(str(observed)) == Decimal(value)
                        else:
                            assert ("" if observed is None else str(observed)) == value
                result["native_excel"].append({"file":filename,"rows":len(expected),"all_cells_checked":True})
            finally:
                book.Close(SaveChanges=False)
    finally:
        excel.Quit()
    pdf = material / "a4.pdf"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=EDGE,headless=True)
        try:
            page = browser.new_page(locale="zh-CN")
            page.goto((material/"费用说明.html").as_uri())
            assert expected_cost in page.locator("body").inner_text()
            page.pdf(path=str(pdf),format="A4",print_background=True,prefer_css_page_size=True)
        finally:
            browser.close()
    document = PdfReader(pdf)
    assert expected_cost in "\n".join(page.extract_text() for page in document.pages)
    sizes = [[float(page.mediabox.width),float(page.mediabox.height)] for page in document.pages]
    assert sizes and all(abs(w-595.28)<2 and abs(h-841.89)<2 for w,h in sizes)
    image = RESEARCH / ("a4-"+label+".png")
    with pymupdf.open(pdf) as rendered:
        rendered[0].get_pixmap(matrix=pymupdf.Matrix(1.25,1.25)).save(image)
    result["print"]={"pages":len(sizes),"a4_page_sizes_pt":sizes,"precise_cost_preserved":True,
                     "pdf_sha256":artifact.digest(pdf),"first_page_rendered":image.name}
    result["verified"]=True
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("mode",choices=["ui","office"])
    parser.add_argument("--label",required=True,choices=["directory","onefile","desktop"])
    parser.add_argument("--exe",type=Path)
    args=parser.parse_args()
    assert json.loads((ROOT/"task-ownership.json").read_text())["task"]=="ccs-schema-26"
    result=ui(args.exe.resolve(strict=True),args.label) if args.mode=="ui" else office(args.label)
    result.update(label=args.label,completed_at=datetime.now(timezone(timedelta(hours=8))).isoformat())
    path=RESEARCH/(args.mode+"-"+args.label+".json")
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=="__main__":
    main()
