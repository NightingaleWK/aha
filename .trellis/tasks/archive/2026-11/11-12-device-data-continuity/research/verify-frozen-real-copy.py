"""Exercise the final frozen EXE with a private restored copy and a real-size transfer."""

import hashlib
import http.client
import importlib.util
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from uuid import uuid4


def load_helpers(path):
    spec = importlib.util.spec_from_file_location("real_copy_helpers", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def wait_job(client, job):
    deadline = time.monotonic() + 120
    while job["status"] == "running":
        assert time.monotonic() < deadline, "Transfer timed out"
        time.sleep(0.1)
        job = client.json("GET", "/api/backups/" + job["id"])
    assert job["status"] == "completed", job.get("code")
    return job


def download(client, job, output):
    connection = http.client.HTTPConnection("127.0.0.1", client.port, timeout=30)
    try:
        connection.request("GET", "/api/backups/" + job["id"] + "/download", headers={"Cookie": client.cookie})
        response = connection.getresponse()
        assert response.status == 200
        digest = hashlib.sha256()
        total = 0
        with output.open("xb") as stream:
            while chunk := response.read(1024 * 1024):
                stream.write(chunk)
                digest.update(chunk)
                total += len(chunk)
        assert total == job["result"]["size"] and digest.hexdigest() == job["result"]["sha256"]
        return {"size": total, "sha256": digest.hexdigest()}
    finally:
        connection.close()


def main():
    source = Path(__file__).resolve().parents[4]
    research = source / ".trellis/tasks/11-12-device-data-continuity/research"
    helpers = load_helpers(research / "verify-real-copy.py")
    sys.path.insert(0, str(source / "scripts"))
    from verify_windows_artifact import Client, check_shutdown, stop_process, wait_descriptor
    previous = json.loads((research / "real-copy-verification.json").read_text(encoding="utf-8"))
    receipt = json.loads((research / "onefile-verification.json").read_text(encoding="utf-8"))
    assert previous["verified"] and receipt["verified"]
    local = Path(os.environ["LOCALAPPDATA"])
    task = local / "Temp/aha-device-continuity-20261112"
    current = local / "aha/aha.sqlite3"
    original = helpers.summary(current)
    _, old = helpers.old_facts(current)
    data = Path(previous["restore"]["destination"])
    executable = task / "build/release/portable/aha.exe"
    with executable.open("rb") as stream:
        assert hashlib.file_digest(stream, "sha256").hexdigest() == receipt["executable_sha256"]
    process = subprocess.Popen([str(executable), "--data-dir", str(data), "--no-browser"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    client = None
    report = {"verified": False, "executable_sha256": receipt["executable_sha256"]}
    try:
        launch = wait_descriptor(data / "runtime.json", process)
        client = Client(launch)
        status = client.json("GET", "/api/status")
        if status["default_source"]["binding"]["required"]:
            client.json("POST", "/api/source/binding", {"reason": "最终成品隔离副本验收：保留现存历史，接续当前电脑来源。"})
        result = client.sync({})
        assert result["status"] == "completed", result.get("code")
        report["sync"] = {k: result["result"].get(k) for k in ("new_count", "revised_count", "unchanged_count", "pending_count", "source_schema_version")}
        _, now = helpers.old_facts(data / "aha.sqlite3")
        assert all(now.get(key) == value for key, value in old.items())
        report["all_original_facts_and_assignments_preserved"] = True
        job = wait_job(client, client.json("POST", "/api/backups", {}))
        archive = task / ("real-size-transfer-" + uuid4().hex[:8] + ".aha-backup")
        report["streamed_backup"] = download(client, job, archive)
        upload = client.json("POST", "/api/restore-uploads", {"size": archive.stat().st_size})
        offset = 0
        chunks = 0
        with archive.open("rb") as stream:
            while chunk := stream.read(upload["chunk_bytes"]):
                connection = http.client.HTTPConnection("127.0.0.1", client.port, timeout=30)
                try:
                    connection.request("POST", f"/api/restore-uploads/{upload['id']}/chunks", body=chunk, headers={
                        "Cookie": client.cookie, "Origin": client.origin, "X-AHA-CSRF": client.csrf,
                        "Content-Type": "application/octet-stream", "X-AHA-Upload-Offset": str(offset)})
                    response = connection.getresponse()
                    assert response.status == 200, response.read()
                    uploaded = json.loads(response.read())
                    offset += len(chunk)
                    assert uploaded["received"] == offset
                    chunks += 1
                finally:
                    connection.close()
        restored = task / ("real-frozen-restored-" + uuid4().hex[:8])
        job = wait_job(client, client.json("POST", f"/api/restore-uploads/{upload['id']}/restore", {"destination": str(restored)}))
        assert helpers.summary(data / "aha.sqlite3") == helpers.summary(restored / "aha.sqlite3")
        report["restore_transfer"] = {"chunks": chunks, "bytes": offset, "all_tables_identical": True}
        report["ledger"] = {k: client.json("GET", "/api/ledger").get(k) for k in ("counts", "coverage")}
        check_shutdown(client, process, data / "runtime.json")
        assert helpers.summary(current) == original
        report.update(verified=True, original_ledger_unchanged=True,
                       completed_at=datetime.now(timezone(timedelta(hours=8))).isoformat())
    finally:
        stop_process(process, client)
        (research / "frozen-real-copy-verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
