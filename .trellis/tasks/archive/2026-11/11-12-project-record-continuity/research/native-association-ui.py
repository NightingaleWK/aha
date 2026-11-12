"""Exercise real Edge UI from a preserved synthetic schema3 backup.

Run through run-native.py. Without --exe, launch the current source; --exe runs
the same checks against a frozen Directory/OneFile executable. Private launch
addresses, cookies and CSRF stay in memory. Detailed artifacts stay in the
owned native QA directory; the repository report contains only safe summaries.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import runpy
import sqlite3
import subprocess
import sys
import traceback
import zipfile
from contextlib import closing
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

SOURCE = Path(__file__).resolve().parents[4]
RESEARCH = Path(__file__).resolve().parent
BEIJING = timezone(timedelta(hours=8))
sys.path.insert(0, str(SOURCE / "scripts"))
sys.path.insert(0, str(SOURCE / "src"))

from playwright.sync_api import expect, sync_playwright

from verify_windows_artifact import (
    Client,
    VerificationError,
    check_shutdown,
    digest,
    require,
    stop_process,
    wait_descriptor,
)


def restore_baseline(task: Path, archive: Path, destination: Path) -> None:
    code = (
        "import sys; from pathlib import Path; "
        "sys.path.insert(0,sys.argv[1]); "
        "from aha.backup import restore_backup; "
        "restore_backup(Path(sys.argv[2]),Path(sys.argv[3]))"
    )
    result = subprocess.run(
        [sys.executable, "-X", "utf8", "-B", "-c", code,
         str(task / "baseline-source/src"), str(archive), str(destination)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
        timeout=60, check=False,
    )
    require(result.returncode == 0, "Committed schema3 restore failed.")
    with closing(sqlite3.connect(destination / "aha.sqlite3")) as connection:
        require(connection.execute("PRAGMA user_version").fetchone()[0] == 3,
                "The browser fixture must start as schema3.")


def facts(data: Path) -> dict:
    uri = (data / "aha.sqlite3").resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=2)) as connection:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        rows = connection.execute(
            "SELECT record_key,content_hash,kind,request_count,total_cost_usd,project_id,"
            "availability_state,suppressed FROM usage_records ORDER BY record_key"
        ).fetchall()
        return {
            "schema": connection.execute("PRAGMA user_version").fetchone()[0],
            "content": {row[0]: row[1] for row in rows},
            "detail_count": sum(row[2] == "detail" for row in rows),
            "record_count": sum(int(row[3]) for row in rows if not row[7]),
            "cost": str(sum((Decimal(row[4]) for row in rows if not row[7]), Decimal())),
            "claims": connection.execute("SELECT COUNT(*) FROM usage_claims").fetchone()[0],
        }


def start_application(data: Path, executable: Path | None, error_stream):
    env = dict(os.environ)
    if executable is None:
        command = [sys.executable, "-X", "utf8", "-B", "-m", "aha"]
        env["PYTHONPATH"] = str(SOURCE / "src")
    else:
        command = [str(executable)]
        env.pop("PYTHONPATH", None)
    process = subprocess.Popen(
        [*command, "--data-dir", str(data), "--no-browser", "--no-tray"],
        cwd=SOURCE, env=env, stdout=subprocess.DEVNULL, stderr=error_stream,
    )
    descriptor = wait_descriptor(data / "runtime.json", process)
    return process, descriptor, Client(descriptor)


def wait_idle(page) -> None:
    expect(page.locator("#busy")).to_be_hidden(timeout=30000)


def overview(page) -> None:
    page.locator('[data-page="projects"]').click()
    wait_idle(page)
    expect(page.locator("#association-overview")).to_be_visible()


def choose_select(page, identity: str, value: str) -> None:
    """Use the visible AhaForms control, preserving the actual UI event path."""
    select = page.locator("#" + identity)
    if select.input_value() == value:
        return
    option = select.evaluate(
        "(element,value)=>{const item=[...element.options].find(option=>option.value===value);"
        "return item?{index:item.index,label:item.label}:null}", value)
    require(option is not None, "The target project/select option is unavailable.")
    control = select.locator("xpath=following-sibling::*[1]")
    if select.get_attribute("data-control") == "segmented":
        control.get_by_role("radio", name=option["label"], exact=True).click()
    else:
        control.locator(".form-select-trigger").click()
        search = control.locator(".form-select-search")
        if search.count():
            search.fill(option["label"])
        control.locator(f'[data-option-index="{option["index"]}"]').click()
    require(select.input_value() == value, "The visible selector did not commit its value.")


def query_records(page, *, project: str = "unassigned", session: str = "", reason: str = "all") -> dict:
    choose_select(page, "association-filter-project", project)
    choose_select(page, "association-filter-reason", reason)
    page.locator("#association-filter-directory").fill("")
    page.locator("#association-filter-session").fill(session)
    page.locator("#association-filter-start").fill("")
    page.locator("#association-filter-end").fill("")
    with page.expect_response(lambda response: "/api/project-associations/records?" in response.url) as response:
        page.locator("#search-associations").click()
    result = response.value.json()
    wait_idle(page)
    require(response.value.ok, "Association record query failed.")
    return result


def preview(page, button: str) -> dict:
    with page.expect_response(lambda response: response.url.endswith("/api/project-associations/preview")) as response:
        page.locator(button).click()
    result = response.value.json()
    wait_idle(page)
    require(response.value.ok, "UI association preview failed.")
    expect(page.locator("#association-dialog")).to_be_visible()
    return result


def apply_preview(page, reason: str) -> dict:
    page.locator("#association-reason").fill(reason)
    with page.expect_response(lambda response: response.url.endswith("/api/project-associations/apply")) as response:
        page.locator("#apply-associations").click()
    result = response.value.json()
    wait_idle(page)
    require(response.value.ok and result.get("applied") is True,
            "UI association apply failed.")
    expect(page.locator("#association-dialog")).to_be_hidden()
    return result


def material_summary(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        expected = {"使用明细.csv", "每日汇总.csv", "费用说明.html", "导出信息.json"}
        require(set(archive.namelist()) == expected, "Evidence did not contain four expected files.")
        manifest = json.loads(archive.read("导出信息.json"))
        rows = list(csv.DictReader(io.StringIO(archive.read("使用明细.csv").decode("utf-8-sig"))))
        require(len(rows) == 81 and manifest["summary"]["record_count"] == 81,
                "Saved project evidence has the wrong membership.")
        expected_cost = Decimal("0.1234567") * 81
        require(Decimal(manifest["summary"]["total_cost_usd"]) == expected_cost,
                "Evidence summary differs from project cost.")
        require(sum((Decimal(row["total_cost_usd"]) for row in rows), Decimal()) == expected_cost,
                "Evidence detail costs differ from project summary.")
        assignment = manifest.get("assignment_coverage")
        require(assignment is not None and assignment["status"] == "incomplete",
                "Evidence failed to disclose pending project assignment.")
        require("unassigned_cost_usd" not in assignment,
                "Shared evidence disclosed other unassigned costs.")
        require("未归属" in archive.read("费用说明.html").decode("utf-8"),
                "HTML evidence omitted assignment coverage.")
        require(all(row.get("project_name") == "合成项目丙" for row in rows),
                "Evidence included another project's members.")
    return {"member_count": len(rows), "total_cost_usd": str(expected_cost),
            "assignment_status": assignment["status"], "sha256": digest(path)}


def check_conservation(client: Client) -> dict:
    status = client.json("GET", "/api/project-associations")
    all_usage = client.json("POST", "/api/analysis", {
        "start_date": "2026-10-01", "end_date": "2026-10-31",
        "project_id": "all", "availability_mode": "all",
    })
    coverage = all_usage["assignment_coverage"]
    projects = status["projects"]
    project_count = sum(project["record_count"] for project in projects)
    project_cost = sum((Decimal(project["total_cost_usd"]) for project in projects), Decimal())
    require(project_count + coverage["unassigned_record_count"] == all_usage["summary"]["record_count"],
            "Project and unassigned membership did not conserve total usage.")
    require(project_cost + Decimal(coverage["unassigned_cost_usd"]) == Decimal(all_usage["summary"]["total_cost_usd"]),
            "Project and unassigned exact costs did not conserve total cost.")
    return {"record_count": all_usage["summary"]["record_count"],
            "total_cost_usd": all_usage["summary"]["total_cost_usd"],
            "unassigned_detail_count": coverage["unassigned_detail_count"],
            "unassigned_rollup_count": coverage["unassigned_rollup_count"]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path)
    parser.add_argument("--label", default="source")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    require(re.fullmatch(r"[a-z0-9-]{1,40}", args.label) is not None, "Invalid QA label.")
    task = Path(os.environ["AHA_QA_ROOT"])
    require(Path(os.environ["USERPROFILE"]).is_relative_to(task), "QA must use an isolated profile.")
    fixture = json.loads((task / "association-fixture-info.json").read_text(encoding="utf-8"))
    archive = Path(fixture["archive"])
    require(digest(archive) == fixture["archive_sha256"], "Synthetic schema3 archive changed.")
    case = task / ("association-ui-" + args.label + "-" + uuid4().hex[:8])
    case.mkdir()
    (case / "task-ownership.json").write_text(
        json.dumps({"task": "project-record-continuity", "synthetic": True}) + "\n",
        encoding="utf-8",
    )
    report_path = args.report or RESEARCH / ("native-ui-" + args.label + ".json")
    report = {"verified": False, "mode": "exe" if args.exe else "source",
              "case_id": case.name, "browser": "native Edge via Playwright headless",
              "physical_desktop_input": False, "profile_isolated": True, "checks": [],
              "started_at": datetime.now(BEIJING).isoformat()}
    report["ui_source_sha256"] = {name: digest(SOURCE / "src/aha/web" / name)
                                  for name in ("app.js", "index.html", "style.css")}
    if args.exe:
        report["executable_sha256"] = digest(args.exe)
    process = client = browser = page = None
    console_errors, page_errors = [], []
    phase = "restore-schema3"
    try:
        data = case / "store"
        restore_baseline(task, archive, data)
        initial = facts(data)
        require(initial["detail_count"] == 152 and initial["record_count"] == 159,
                "Synthetic schema3 baseline count changed.")
        with (case / "application-stderr.log").open("wb") as error_stream:
            phase = "launch-upgrade"
            process, descriptor, client = start_application(data, args.exe, error_stream)
            upgraded = facts(data)
            require(upgraded["schema"] == 4 and upgraded["content"] == initial["content"],
                    "Opening schema3 failed to upgrade without fact changes.")
            report["checks"].append("schema3_restore_then_native_upgrade")
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    executable_path=r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                    headless=True,
                )
                context = browser.new_context(viewport={"width": 1440, "height": 1000},
                                              locale="zh-CN", timezone_id="Asia/Shanghai",
                                              accept_downloads=True)
                page = context.new_page()
                page.on("console", lambda message: console_errors.append(message.text)
                        if message.type == "error" else None)
                page.on("pageerror", lambda error: page_errors.append(str(error)))
                phase = "initial-project-workspace"
                page.goto(descriptor["bootstrap_url"], wait_until="domcontentloaded")
                wait_idle(page)
                overview(page)
                require(page.locator(".project-card").count() == 3, "Project cards were not rendered.")
                initial_status = client.json("GET", "/api/project-associations")
                require(initial_status["summary"]["recoverable_detail_count"] == 135,
                        "History recovery classification omitted known project members.")
                for text in ("历史依据可恢复", "有目录，待确认归属", "缺少目录依据", "目录依据存在冲突"):
                    require(text in page.locator("#association-groups").inner_text(),
                            "A pending assignment category is missing in UI.")
                report["checks"].append("project_cost_overview_and_pending_reasons")

                phase = "cross-page-assignment"
                records = query_records(page, session="history-a")
                require(len(records["rows"]) == 50 and records["next_cursor"],
                        "The 80-row group did not expose a 50-row first page.")
                expect(page.locator("#association-records tbody tr")).to_have_count(50)
                require(page.locator("#association-records tbody input:disabled").count() == 0,
                        "Loaded record checkboxes remained disabled.")
                page.locator("#association-all-filtered").check()
                choose_select(page, "association-target-project", fixture["project_c"])
                bulk = preview(page, "#preview-assignment")
                require(bulk["summary"]["selected_detail_count"] == 80,
                        "All-filtered preview selected only the current page.")
                apply_preview(page, "合成验收：跨分页的 80 条消费归项目丙。")
                report["checks"].append("ui_all_filtered_80_rows_from_50_row_page")

                phase = "whole-session-and-stale-preview"
                records = query_records(page, project=fixture["project_c"], session="history-a")
                page.locator("#association-records tbody input[type=checkbox]").first.check()
                page.locator("#association-bind-sessions").check()
                whole = preview(page, "#preview-assignment")
                require(whole["summary"]["selected_detail_count"] == 80,
                        "One selected record did not expand to the whole 80-row session.")
                require("当前筛选以外" in page.locator("#association-preview-summary").inner_text(),
                        "The UI did not explain expanded whole-session scope.")
                old_analysis = client.json("POST", "/api/analysis", {
                    "start_date": "2026-10-01", "end_date": "2026-10-31",
                    "project_id": fixture["project_c"], "availability_mode": "available",
                })
                apply_preview(page, "合成验收：整个会话的现有明细与后续新增沿用项目丙。")
                raw = client.request("POST", "/api/batches/preview", {
                    "analysis_id": old_analysis["analysis_id"], "claim": {},
                }, expected=409)[2]
                require(json.loads(raw)["code"] == "analysis_expired",
                        "A prior billing preview survived an assignment change.")
                report["checks"].append("ui_one_record_expands_whole_session_and_old_preview_expires")

                phase = "future-session-consumption"
                helpers = runpy.run_path(str(SOURCE / "tests/test_storage_helpers.py"))
                sql_helpers = runpy.run_path(str(SOURCE / "tests/test_sources.py"))
                future = helpers["detail"](request_id="synthetic-future-history-a",
                                           session_id="history-a", created_at=1792948600)
                sql = case / "synthetic-future-session.sql"
                sql.write_bytes(sql_helpers["dump"]([future], [], [], version=25))
                with page.expect_response(lambda response: response.url.endswith("/api/source/sql")) as response:
                    page.locator("#sql-file").set_input_files(str(sql))
                require(response.value.ok, "Synthetic SQL import request failed.")
                expect(page.locator("#source-mode")).to_have_text(re.compile("已同步|需要核对"), timeout=30000)
                wait_idle(page)
                require(facts(data)["detail_count"] == 153, "Future consumption did not enter the ledger.")
                future_records = client.json("GET", "/api/project-associations/records?project_id=all&session_id=history-a&size=200")
                require(len(future_records["rows"]) == 81 and all(
                    row["project_id"] == fixture["project_c"] for row in future_records["rows"]),
                    "A new consumption failed to inherit its persistent session project.")
                report["checks"].append("ui_sql_import_future_record_inherits_session_project")

                phase = "recover-old-directories"
                query_records(page, project="all")
                recovery = preview(page, "#recover-associations")
                require(recovery["summary"]["selected_detail_count"] == 67
                        and recovery["summary"]["directory_only_sessions"] == 1,
                        "History recovery did not distinguish project and directory-only evidence.")
                apply_preview(page, "合成验收：按唯一历史目录恢复，保留已确认的逐条项目归属。")
                recovered = client.json("GET", "/api/project-associations")
                per_project = {project["id"]: project for project in recovered["projects"]}
                require(per_project[fixture["project_c"]]["detail_count"] == 81
                        and per_project[fixture["project_b"]]["detail_count"] == 56,
                        "Recovery replaced accepted ownership or lost the manual exception.")
                require(recovered["summary"]["unassigned_detail_count"] == 16,
                        "Unknown, ambiguous or generic work was guessed into a project.")
                report["checks"].append("ui_history_recovery_preserves_owners_and_uncertain_queue")

                phase = "keyboard-and-layout"
                query_records(page, session="generic-work")
                trigger = page.locator(".association-bulk-fields > .field .form-select-trigger")
                trigger.click()
                page.keyboard.press("Escape")
                require(trigger.evaluate("element => element === document.activeElement"),
                        "Escape did not return focus to the project selector.")
                page.locator("#association-all-filtered").check()
                cancelled = preview(page, "#preview-assignment")
                require(cancelled["summary"]["selected_detail_count"] == 12,
                        "Generic work could not remain actionable in the queue.")
                page.keyboard.press("Escape")
                expect(page.locator("#association-dialog")).to_be_hidden()
                expect(page.locator("#preview-assignment")).to_be_focused()
                layouts = []
                for width in (1440, 1366, 1280, 430, 375):
                    page.set_viewport_size({"width": width, "height": 1000})
                    page.evaluate("() => window.scrollTo(0,0)")
                    page.wait_for_timeout(80)
                    measurement = page.evaluate("() => ({width:innerWidth,scroll:document.documentElement.scrollWidth})")
                    require(measurement["scroll"] <= measurement["width"] + 1,
                            "Project workspace overflows the viewport horizontally.")
                    page.screenshot(path=str(case / f"projects-{width}.png"), full_page=True)
                    layouts.append({"width": width, "horizontal_overflow": False})
                report["layouts"] = layouts
                report["checks"].append("escape_focus_and_five_responsive_widths")
                page.set_viewport_size({"width": 1440, "height": 1000})

                phase = "project-evidence"
                card = page.locator(".project-card").filter(has=page.get_by_role("heading", name="合成项目丙", exact=True))
                card.get_by_role("button", name="查看项目全部费用").click()
                wait_idle(page)
                choose_select(page, "availability-mode", "available")
                page.locator("#analyze").click()
                wait_idle(page)
                require(page.locator("#metric-count").inner_text().strip() == "81",
                        "Project preview has the wrong record count.")
                expect(page.locator("#assignment-coverage-note")).to_be_visible()
                page.locator("#claim-purpose").fill("合成验收：项目丙消费统计与报销证据。")
                with page.expect_download() as download:
                    page.locator("#create-batch").click()
                materials = case / "materials"
                materials.mkdir()
                saved_material = materials / "project-c.zip"
                download.value.save_as(str(saved_material))
                wait_idle(page)
                report["material"] = material_summary(saved_material)
                report["conservation"] = check_conservation(client)
                report["checks"].append("ui_project_preview_save_and_exact_evidence_members")

                phase = "reopen-persistent-ledger"
                context.close()
                check_shutdown(client, process, data / "runtime.json")
                process, descriptor, client = start_application(data, args.exe, error_stream)
                reopened = browser.new_context(viewport={"width": 1440, "height": 1000},
                                                locale="zh-CN", timezone_id="Asia/Shanghai",
                                                accept_downloads=True)
                page = reopened.new_page()
                page.on("console", lambda message: console_errors.append(message.text)
                        if message.type == "error" else None)
                page.on("pageerror", lambda error: page_errors.append(str(error)))
                page.goto(descriptor["bootstrap_url"], wait_until="domcontentloaded")
                wait_idle(page)
                overview(page)
                persisted = client.json("GET", "/api/project-associations")
                require(next(project for project in persisted["projects"]
                             if project["id"] == fixture["project_c"])["detail_count"] == 81,
                        "Project membership did not survive native restart.")
                rejected = json.loads(client.request("POST", "/api/project-associations/apply", {
                    "preview_id": cancelled["preview_id"], "idempotency_key": uuid4().hex,
                    "reason": "合成验收：旧实例的预览必须失效。",
                }, expected=409)[2])
                require(rejected["code"] == "association_preview_required",
                        "An unsaved preview survived the old server instance.")
                page.locator('[data-page="batches"]').click()
                page.locator("#batch-list .batch-link").first.click()
                wait_idle(page)
                with page.expect_download() as download:
                    page.locator("#batch-detail").get_by_role("button", name="下载材料", exact=True).click()
                redownloaded = materials / "project-c-redownloaded.zip"
                download.value.save_as(str(redownloaded))
                wait_idle(page)
                require(digest(redownloaded) == digest(saved_material),
                        "Frozen evidence changed after native restart.")
                report["checks"].append("native_reopen_retains_ownership_and_original_package")
                reopened.close()
                browser.close()
                browser = None
            phase = "final-conservation-and-shutdown"
            final = facts(data)
            require(all(final["content"].get(key) == value for key, value in initial["content"].items()),
                    "Assignment changed an original consumption fact.")
            require(final["detail_count"] == 153 and final["claims"] == 81,
                    "Final synthetic fact or claim count is unexpected.")
            require(not console_errors and not page_errors, "Browser reported console or page errors.")
            check_shutdown(client, process, data / "runtime.json")
            report.update(verified=True, original_facts_unchanged=True,
                          console_error_count=len(console_errors), page_error_count=len(page_errors),
                          final_detail_count=final["detail_count"], final_claim_count=final["claims"],
                          final_record_count=final["record_count"], completed_at=datetime.now(BEIJING).isoformat())
    except BaseException as error:
        (case / "failure-details.txt").write_text(traceback.format_exc(), encoding="utf-8")
        if page is not None and not page.is_closed():
            try:
                page.screenshot(path=str(case / "failure.png"), full_page=True)
            except Exception:
                pass
        (case / "browser-errors.json").write_text(json.dumps({"console": console_errors, "page": page_errors}, ensure_ascii=False, indent=2), encoding="utf-8")
        report.update(failed_phase=phase, error_type=type(error).__name__,
                      error=str(error) if isinstance(error, VerificationError) else type(error).__name__,
                      console_error_count=len(console_errors), page_error_count=len(page_errors))
    finally:
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        if process is not None:
            stop_process(process, client)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
