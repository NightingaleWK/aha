"""Apply the authorized one-way continuation only after delivery and native gates."""

import importlib.util
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from uuid import uuid4

import win32com.client


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def wait_descriptor(path):
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
        time.sleep(0.1)
    raise RuntimeError("Primary ledger did not become ready")


def main():
    source = Path(__file__).resolve().parents[4]
    research = source / ".trellis/tasks/11-12-device-data-continuity/research"
    helpers = load(research / "verify-real-copy.py", "primary_helpers")
    transfers = load(research / "verify-frozen-real-copy.py", "primary_transfers")
    sys.path.insert(0, str(source / "scripts"))
    from verify_windows_artifact import Client, digest
    delivery = json.loads((research / "delivery.json").read_text(encoding="utf-8"))
    desktop_check = json.loads((research / "desktop-verification.json").read_text(encoding="utf-8"))
    tests = json.loads((research / "python-test-result.json").read_text(encoding="utf-8"))
    assert tests["verified"] and tests["tests_run"] >= 317
    assert desktop_check["verified"] and desktop_check["executable_sha256"] == delivery["executable_sha256"]
    assert digest(Path(delivery["desktop"])) == delivery["executable_sha256"]
    local = Path(os.environ["LOCALAPPDATA"])
    data = local / "aha"
    database = data / "aha.sqlite3"
    _, old = helpers.old_facts(database)
    before = helpers.summary(database)
    assert before["projects"]["count"] >= 5 and before["usage_records"]["count"] >= 39463
    report = {"verified": False, "old_fact_count": len(old), "source_program": delivery["desktop"],
              "executable_sha256": delivery["executable_sha256"]}
    expected_original = "1d9d53134e61d30bc96335e73b7545c84b9b7544977599b65c998fcece18f57c"
    if (data / "aha.sqlite3-wal").exists() or digest(database) != expected_original:
        from aha.backup import create_backup
        fresh = Path(delivery["recovery_archive"]).parent / ("aha-latest-before-continuity-" + uuid4().hex[:8] + ".aha-backup")
        report["fresh_prechange_backup"] = create_backup(data, fresh)
        assert helpers.summary(database) == before, "Primary ledger changed during preparation"
    shell = win32com.client.Dispatch("Shell.Application")
    shell.ShellExecute(delivery["desktop"], "--no-browser", str(Path(delivery["desktop"]).parent), "open", 1)
    launch = wait_descriptor(data / "runtime.json")
    client = Client(launch)
    try:
        status = client.json("GET", "/api/status")
        assert Path(status["data_directory"]).resolve() == data.resolve()
        assert status["version"] == delivery["version"]
        report["actual_data_directory"] = status["data_directory"]
        binding = client.json("GET", "/api/source/binding")
        if binding["required"]:
            binding = client.json("POST", "/api/source/binding", {
                "reason": "用户已确认旧电脑格式化，仅使用新电脑；保留全部现存历史、项目及核对结果，将当前CCS作为新来源接续。"})
        assert binding["bound"] and not binding["required"]
        result = client.sync({})
        assert result["status"] == "completed", result.get("code")
        report["sync"] = {key: result["result"].get(key) for key in (
            "new_count", "revised_count", "unchanged_count", "pending_count", "source_schema_version", "observed")}
        repeated = client.sync({})
        assert repeated["status"] == "completed", repeated.get("code")
        report["repeat_sync"] = {key: repeated["result"].get(key) for key in (
            "new_count", "revised_count", "pending_count", "source_schema_version")}
        _, current = helpers.old_facts(database)
        assert all(current.get(key) == value for key, value in old.items()), "An old fact or project assignment changed"
        after = helpers.summary(database)
        assert after["projects"] == before["projects"]
        report["all_preexisting_facts_and_project_assignments_preserved"] = True
        report["projects_unchanged"] = True
        ledger = client.json("GET", "/api/ledger")
        report["ledger"] = {key: ledger.get(key) for key in ("counts", "coverage", "last_successful_sync_at")}
        report["open_case_types"] = sorted({case["type"] for case in client.json("GET", "/api/reconciliations")["cases"]})
        for label, start in (("all_history", "2026-06-17"), ("today", "2026-11-12")):
            analysis = client.json("POST", "/api/analysis", {"start_date": start, "end_date": "2026-11-12",
                                   "project_id": "all", "availability_mode": "available"})
            report[label] = {key: analysis["summary"].get(key) for key in
                             ("record_count", "detail_count", "rollup_record_count")}
        job = transfers.wait_job(client, client.json("POST", "/api/backups", {}))
        backup_root = Path(delivery["recovery_archive"]).parent
        stamp = datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d-%H%M%S")
        output = backup_root / ("aha-after-continuity-" + stamp + "-" + uuid4().hex[:6] + ".aha-backup")
        report["after_backup"] = {"path": str(output), **transfers.download(client, job, output)}
        # Reopen through Explorer exactly as the user will, and verify one owned service.
        shell.ShellExecute(delivery["desktop"], "", str(Path(delivery["desktop"]).parent), "open", 1)
        time.sleep(1)
        current_launch = json.loads((data / "runtime.json").read_text(encoding="utf-8"))
        assert current_launch["run_id"] == launch["run_id"]
        assert client.json("GET", "/api/instance")["state"] == "ready"
        report.update(verified=True, same_instance_reopened=True,
                       completed_at=datetime.now(timezone(timedelta(hours=8))).isoformat())
        delivery["desktop_started_and_verified"] = True
        delivery["primary_continuation_verified"] = True
        (research / "delivery.json").write_text(json.dumps(delivery, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    finally:
        (research / "primary-continuation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
