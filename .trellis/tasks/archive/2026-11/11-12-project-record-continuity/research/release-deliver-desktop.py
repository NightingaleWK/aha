"""Reviewed, real-profile delivery only; preparation must never execute main().

Run qa315/Scripts/python.exe directly with the real Windows environment and
AHA_QA_ROOT set to aha-release-v050-20261112, never release-run-native.py.
Candidate-info binds version/source/runtime, approved report bytes, and optional
directory_executable_sha256. No migration, association apply, or restore is used.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

BASE_SHA = "9ccd827d1dc4edbbda8b4a8bf30abe3867143950b828a7ffc5217c97e334e97a"
RUNTIME_SHA = "2d64ab084e0aa6c3d8ffab874ef7a08fd35b4fbf452dc1353e89d06dc7ea8642"
VERSION = "0.5.0"


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_reports(info, research, source, h):
    allowed = {info["executable_sha256"]}
    if info.get("directory_executable_sha256"):
        allowed.add(info["directory_executable_sha256"])
    h.require(all(re.fullmatch(r"[a-f0-9]{64}", value) for value in allowed), "invalid_artifact_hash")
    seen, reports = set(), []
    for item in info["check_reports"]:
        path = Path(item["path"])
        path = path if path.is_absolute() else research / path
        h.require(h.sha(path) == item["sha256"], "approved_check_report_bytes_changed")
        report = h.read_json(path)
        h.require(report.get("verified") is True, "candidate_check_not_verified")
        artifact = report.get("executable_sha256", report.get("artifact_sha256"))
        if artifact:
            h.require(artifact in allowed, "check_report_for_different_executable")
            if "version" in report:
                h.require(report["version"] == VERSION, "artifact_check_version_mismatch")
                seen.add(artifact)
            if "source_sha" in report:
                h.require(report["source_sha"] == info["source_sha"], "artifact_check_source_mismatch")
        else:
            # An older source-only regression can be equivalent by normalized
            # fingerprints; it is never counted as a test of the new EXE/M.
            h.require(report.get("source_fingerprints") == info["fingerprints"]
                      or report.get("runtime_sha256") == RUNTIME_SHA, "unbound_source_only_check")
        for field in ("fingerprints", "source_fingerprints"):
            if field in report:
                h.require(report[field] == info["fingerprints"], "check_report_fingerprint_mismatch")
        if "runtime_sha256" in report:
            h.require(report["runtime_sha256"] == RUNTIME_SHA, "check_report_runtime_mismatch")
        for name, digest in report.get("ui_source_sha256", {}).items():
            h.require(name in {"app.js", "index.html", "style.css"}
                      and h.sha(source / "src/aha/web" / name) == digest, "tested_ui_bytes_changed")
        reports.append({"path": str(path), "sha256": item["sha256"], "artifact_sha256": artifact})
    h.require(allowed <= seen, "versioned_native_check_missing_for_artifact")
    return reports


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-info", required=True, type=Path)
    parser.add_argument("--open-browser", action="store_true")
    args = parser.parse_args()
    source, research = Path(__file__).resolve().parents[4], Path(__file__).resolve().parent
    h = load(research / "deliver-and-recover.py", "reviewed_delivery_helpers")
    h.OLD_SHA = BASE_SHA
    public = {"schema_version": 1, "verified": False, "started_at": h.now(),
              "native_tray_enabled": True, "physical_tray_input": False,
              "synchronization_requested_by_script": False, "real_ledger_restored": False}
    report_path, phase, state, checkpoint = research / "release-desktop-delivery.json", "preflight", {}, None
    try:
        task, data, desktop = h.native_context(source)
        h.require(task.name == "aha-release-v050-20261112"
                  and h.read_json(task / "task-ownership.json").get("purpose") == "release-v050",
                  "release_task_ownership_mismatch")
        h.require(Path(sys.executable).resolve() == (task / "qa315/Scripts/python.exe").resolve(),
                  "reviewed_qa315_interpreter_required")
        sys.path[:0] = [str(source / "scripts"), str(source / "src")]
        import release
        from aha.backup import create_backup
        from verify_windows_artifact import Client, pe_version
        bridge = load(research / "release-prepare-ui-template.py", "release_git_bridge")

        def git(root, *arguments, optional=False):
            result = subprocess.run(bridge.git_command(root, *arguments), capture_output=True)
            h.require(result.returncode == 0 or optional, "candidate_git_verification_failed")
            return result.stdout if result.returncode == 0 else b""

        release.git = git
        info = h.read_json(args.candidate_info)
        h.require(info.get("version") == VERSION and info.get("stage") in {"candidate", "published"}
                  and re.fullmatch(r"[a-f0-9]{40}", info.get("source_sha", ""))
                  and set(info.get("fingerprints", {})) == {"full", "tray", "materials", "recipe"},
                  "candidate_identity_invalid")
        h.require(subprocess.run(bridge.git_command(source, "merge-base", "--is-ancestor",
                                                   info["source_sha"], "HEAD"), capture_output=True).returncode == 0,
                  "candidate_not_ancestor_of_current_head")
        h.require(release.version_at(source, info["source_sha"]) == release.version_at(source, "WORKTREE") == VERSION
                  and release.fingerprints(source, info["source_sha"]) == info["fingerprints"]
                  == release.fingerprints(source, "WORKTREE"), "candidate_or_current_product_changed")
        runtime = release.installed_runtime()
        h.require(runtime["python"] == [3, 15, 2] and runtime["sqlite"] == [3, 53, 4]
                  and runtime["windows"] and runtime["bits"] == 64
                  and release.runtime_digest(source, "WORKTREE", runtime) == info["runtime_sha256"] == RUNTIME_SHA,
                  "actual_fixed_runtime_mismatch")
        executable = Path(info["executable"]).resolve()
        h.NEW_SHA = info["executable_sha256"]
        h.require(h.sha(executable) == h.NEW_SHA, "candidate_executable_bytes_changed")
        resource = pe_version(executable)
        h.require(all(resource[key + "_version"] == VERSION
                      and resource[key + "_version_parts"] == [0, 5, 0, 0] for key in ("file", "product")),
                  "candidate_pe_version_mismatch")
        reports = validate_reports(info, research, source, h)
        protection = h.read_json(research / "protection.json")
        persistent = Path(protection["archive"]).parent.resolve()
        h.require(persistent.is_dir() and persistent.drive.upper() == "D:"
                  and h.sha(Path(protection["archive"])) == protection["archive_sha256"]
                  and h.sha(Path(protection["old_executable"])) == protection["old_executable_sha256"],
                  "original_persistent_protection_unavailable")
        binding = {key: info[key] for key in ("version", "source_sha", "runtime_sha256", "fingerprints")}
        public.update(binding, executable_sha256=h.NEW_SHA, pe_version=resource, publication_stage=info["stage"],
                      candidate_info_sha256=h.sha(args.candidate_info), check_reports=reports,
                      data_directory=str(data), qa_python=sys.executable, current_head=release.resolve(source, "HEAD"))
        allowed = {BASE_SHA, h.NEW_SHA}
        for receipt in task.glob("release-desktop-delivery-state-*.json"):
            prior = h.read_json(receipt)
            if (prior.get("verified") is True and prior.get("task") == h.TASK
                    and prior.get("purpose") == "release-v050-desktop-delivery"
                    and prior.get("data_directory") == str(data)
                    and all(prior.get(key) == value for key, value in binding.items())):
                allowed.add(prior["executable_sha256"])
        checkpoint = task / ("release-desktop-delivery-state-" + h.NEW_SHA[:16] + ".json")
        state = h.read_json(checkpoint) if checkpoint.exists() else {
            **binding, "task": h.TASK, "purpose": "release-v050-desktop-delivery", "created_at": h.now(),
            "executable_sha256": h.NEW_SHA, "data_directory": str(data)}
        h.require(all(state.get(key) == value for key, value in binding.items())
                  and state.get("task") == h.TASK and state.get("purpose") == "release-v050-desktop-delivery"
                  and state.get("executable_sha256") == h.NEW_SHA and Path(state["data_directory"]).resolve() == data,
                  "delivery_checkpoint_identity_mismatch")
        targets = [desktop / "aha.exe", Path("D:/Program Files/aha.exe")]
        h.require(all(path.is_file() and h.sha(path) in allowed for path in targets),
                  "unrecognized_program_target_preserved")
        if (data / "runtime.json").exists():
            image = h.sha(h.process_image(h.read_json(data / "runtime.json")["pid"]))
            h.require(image in allowed, "unrecognized_default_instance_preserved")
            h.OLD_SHA = image
        running = h.existing_instance(data, Client)
        if state.get("verified") is True:
            h.require(all(h.sha(path) == h.NEW_SHA for path in targets), "completed_delivery_changed")
            h.require(running is None or (running[2] == h.NEW_SHA
                      and running[0].json("GET", "/api/status")["version"] == VERSION),
                      "completed_delivery_has_different_running_instance")
            previous = state["delivery_receipt"]
            h.require(previous.get("verified") is True and previous.get("executable_sha256") == h.NEW_SHA,
                      "completed_delivery_report_unavailable")
            public.pop("started_at")
            previous.update(public, verified=True, already_delivered=True, revalidated_at=h.now())
            if args.open_browser:
                process = subprocess.Popen([str(targets[0])], cwd=desktop,
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                h.require(process.wait(timeout=45) == 0, "normal_browser_launch_failed")
                previous.update(browser_open_requested=True, normal_ui_may_start_new_sync=True)
            h.write_json(report_path, previous)
            print(json.dumps({"verified": True, "already_delivered": True, "report": str(report_path)}))
            return 0
        phase = "normal_shutdown_and_schema4_backup"
        if running is not None:
            h.shutdown_default(data, running)
        snapshot = h.load_helper(research / "prepare-real-copy.py", "release_snapshot_helpers")
        relations = h.load_helper(research / "verify-real-associations.py", "release_relationship_helpers")

        def capture(root):
            return {"facts": snapshot.facts(root / "aha.sqlite3"),
                    "relationships": relations.relationships(root / "aha.sqlite3", snapshot.digest_rows),
                    "extra": h.extra_preservation(root, snapshot)}

        before = capture(data)
        h.require(before["facts"]["schema"] == 4, "schema4_primary_required_no_migration")
        if "before" in state:
            h.require(before == state["before"], "primary_changed_since_interrupted_delivery")
        state["before"] = before
        if "backup_before" not in state:
            archive = persistent / ("aha-before-release-v0.5.0-" + h.uuid4().hex[:12] + ".aha-backup")
            state["backup_before"] = h.backup_summary(create_backup(data, archive))
            h.write_json(checkpoint, state)
        backup = state["backup_before"]
        h.require(backup["store_schema_version"] == 4 and h.sha(Path(backup["archive_path"])) == backup["sha256"],
                  "fresh_complete_backup_missing_or_changed")
        with tempfile.TemporaryDirectory(prefix="release-backup-check-", dir=task) as temporary:
            database = Path(temporary) / "aha.sqlite3"
            with zipfile.ZipFile(backup["archive_path"]) as packed:
                manifest = json.loads(packed.read("manifest.json"))
                h.require(manifest["store_schema_version"] == 4 and packed.testzip() is None,
                          "fresh_backup_container_invalid")
                with packed.open("aha.sqlite3") as first, database.open("xb") as second:
                    shutil.copyfileobj(first, second, 1024 * 1024)
                expected = next(row for row in manifest["files"] if row["path"] == "aha.sqlite3")
                h.require(h.sha(database) == expected["sha256"], "backup_snapshot_hash_mismatch")
            h.require(snapshot.facts(database) == before["facts"]
                      and relations.relationships(database, snapshot.digest_rows) == before["relationships"],
                      "backup_readonly_facts_or_links_mismatch")
        h.require(capture(data) == before, "primary_changed_during_backup")
        phase = "preserve_programs_and_atomic_delivery"
        rollback = []
        for target in targets:
            observed = h.sha(target)
            if observed != h.NEW_SHA:
                preserved = persistent / ("aha-before-release-v0.5.0-" + observed[:16] + ".exe")
                if not preserved.exists():
                    with target.open("rb") as first, preserved.open("xb") as second:
                        shutil.copyfileobj(first, second, 1024 * 1024)
                        second.flush()
                        os.fsync(second.fileno())
                h.require(h.sha(preserved) == observed, "program_rollback_copy_mismatch")
                rollback.append({"path": str(preserved), "sha256": observed})
        state["rollback_programs"] = state.get("rollback_programs", []) + rollback
        h.write_json(checkpoint, state)
        delivered = []
        for target in targets:
            h.OLD_SHA = h.sha(target)
            h.require(h.OLD_SHA in allowed, "program_changed_before_atomic_delivery")
            delivered.append(h.copy_program(executable, target))
        phase = "start_actual_desktop_and_verify_preserved_baseline"
        client, descriptor = h.ready_default(targets[0], data, Client)
        status = client.json("GET", "/api/status")
        h.require(status["version"] == VERSION and Path(status["data_directory"]).resolve() == data
                  and capture(data) == before, "delivered_default_changed_primary_baseline")
        reopened = subprocess.Popen([str(targets[0]), "--no-browser"], cwd=desktop,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        h.require(reopened.wait(timeout=45) == 0, "desktop_reopen_failed")
        repeated = h.read_json(data / "runtime.json")
        h.require(all(repeated.get(key) == descriptor.get(key) for key in ("run_id", "profile_id", "pid"))
                  and client.json("GET", "/api/instance")["state"] == "ready"
                  and capture(data) == before, "desktop_reopen_did_not_preserve_instance_and_ledger")
        public.update(verified=True, completed_at=h.now(), delivery=delivered, backup_before=backup,
                      rollback_programs=state["rollback_programs"], baseline=before,
                      schema4_facts_and_relationships_unchanged=True, same_service_reopened=True,
                      original_protection_preserved=True, browser_open_requested=False)
        state.update(verified=True, completed_at=public["completed_at"], delivery_receipt=public.copy())
        h.write_json(report_path, public)
        h.write_json(checkpoint, state)
        if args.open_browser:
            phase = "normal_browser_launch_after_preservation_verification"
            process = subprocess.Popen([str(targets[0])], cwd=desktop,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            h.require(process.wait(timeout=45) == 0, "normal_browser_launch_failed")
            public.update(browser_open_requested=True, normal_ui_may_start_new_sync=True)
            h.write_json(report_path, public)
        print(json.dumps({"verified": True, "desktop": str(targets[0]), "report": str(report_path)}))
        return 0
    except Exception as error:
        public.update(verified=False, failed_at=h.now(), failure_stage=phase,
                      failure_code=str(error) if isinstance(error, h.DeliveryError) else type(error).__name__)
        h.write_json(report_path, public)
        if checkpoint is not None and state:
            state.update(last_failure_stage=phase, last_failure_at=public["failed_at"])
            h.write_json(checkpoint, state)
        print(json.dumps({"verified": False, "stage": phase, "code": public["failure_code"]}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
