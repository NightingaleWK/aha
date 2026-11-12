"""Run the frozen EXE against a protected real-size copy using local HTTP only."""

import argparse
import http.client
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter
from uuid import uuid4


def load(path):
    spec = importlib.util.spec_from_file_location("real_verification_helpers", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def apply(client, preview, retry):
    payload = json.dumps({"preview_id": preview, "idempotency_key": retry,
                          "reason": "最终单文件成品真实规模副本验收：恢复唯一历史目录，保留原消费和项目。"}).encode()
    connection = http.client.HTTPConnection("127.0.0.1", client.port, timeout=120)
    try:
        connection.request("POST", "/api/project-associations/apply", payload, headers={
            "Content-Type": "application/json", "Cookie": client.cookie,
            "Origin": client.origin, "X-AHA-CSRF": client.csrf})
        response = connection.getresponse()
        assert response.status == 200
        return json.loads(response.read())
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", required=True, type=Path)
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[4]
    research = source / ".trellis/tasks/11-12-project-record-continuity/research"
    task = Path(os.environ["AHA_QA_ROOT"])
    sys.path.insert(0, str(source / "scripts"))
    from verify_windows_artifact import Client, check_shutdown, digest, stop_process, wait_descriptor
    snapshot = load(research / "prepare-real-copy.py")
    links = load(research / "verify-real-associations.py")
    protection = json.loads((research / "protection.json").read_text(encoding="utf-8"))
    baseline = json.loads((research / "real-copy-baseline.json").read_text(encoding="utf-8"))["snapshot"]
    target = task / ("frozen-real-copy-" + uuid4().hex[:8])
    code = "import sys; from pathlib import Path; sys.path.insert(0,sys.argv[1]); from aha.backup import restore_backup; restore_backup(Path(sys.argv[2]),Path(sys.argv[3]))"
    subprocess.run([sys.executable, "-X", "utf8", "-B", "-c", code,
                    str(task / "baseline-source/src"), protection["archive"], str(target)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    assert snapshot.facts(target / "aha.sqlite3") == baseline
    process = None
    client = None
    report = {"verified": False, "executable_sha256": digest(args.exe), "timings_ms": {}}
    try:
        started = perf_counter()
        process = subprocess.Popen([str(args.exe), "--data-dir", str(target), "--no-browser"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        descriptor = wait_descriptor(target / "runtime.json", process)
        client = Client(descriptor)
        report["timings_ms"]["launch_and_schema3_migration"] = round((perf_counter() - started) * 1000)
        assert snapshot.facts(target / "aha.sqlite3")["assigned"] == 1500
        started = perf_counter()
        preview = client.json("POST", "/api/project-associations/preview", {"action": "recover"})
        report["timings_ms"]["recovery_preview"] = round((perf_counter() - started) * 1000)
        assert preview["summary"]["recovered_sessions"] == 347
        assert preview["summary"]["changed_count"] == 37165
        started = perf_counter()
        retry = uuid4().hex
        result = apply(client, preview["preview_id"], retry)
        report["timings_ms"]["atomic_recovery"] = round((perf_counter() - started) * 1000)
        assert result["changed_count"] == 37165 and result["recovered_sessions"] == 347
        assert result == apply(client, preview["preview_id"], retry)
        status = client.json("GET", "/api/project-associations")
        assert status["summary"]["assigned_detail_count"] == 38665
        assert status["summary"]["unassigned_detail_count"] == 3438
        after = snapshot.facts(target / "aha.sqlite3")
        for key in ("fact_identity_content", "versions", "projects", "claims", "revisions", "coverage", "counts"):
            assert after[key] == baseline[key]
        ownership = links.relationships(target / "aha.sqlite3", snapshot.digest_rows)
        check_shutdown(client, process, target / "runtime.json")
        process = subprocess.Popen([str(args.exe), "--data-dir", str(target), "--no-browser"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        descriptor = wait_descriptor(target / "runtime.json", process)
        client = Client(descriptor)
        assert links.relationships(target / "aha.sqlite3", snapshot.digest_rows) == ownership
        assert client.json("GET", "/api/project-associations")["summary"] == status["summary"]
        check_shutdown(client, process, target / "runtime.json")
        original = task.parent.parent / "aha/aha.sqlite3"
        assert snapshot.facts(original) == baseline
        report.update(verified=True, recovered_sessions=347, recovered_detail_count=37165,
                      assigned_detail_count=38665, unassigned_detail_count=3438,
                      facts_cost_tokens_claims_old_materials_unchanged=True,
                      ownership_survives_frozen_restart=True, original_ledger_unchanged=True,
                      native_tray_enabled=True, physical_tray_input=False,
                      completed_at=datetime.now(timezone(timedelta(hours=8))).isoformat())
    finally:
        if process is not None:
            stop_process(process, client)
        (research / "frozen-real-copy-verification.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
