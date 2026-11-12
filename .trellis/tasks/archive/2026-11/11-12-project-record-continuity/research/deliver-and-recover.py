"""Reviewed native delivery and authorized primary recovery; never run during preparation.

Run only through run-native.py --real-profile after the main session reviews this file.
All validation precedes primary actions. No Store is constructed for the real ledger.
An interrupted apply retains its private preview/idempotency receipt for an exact replay.
Failures leave the recognized instance and backups intact; rollback is always independent.
"""

from __future__ import annotations

import ctypes
import hashlib
import http.client
import importlib.metadata
import importlib.util
import json
import os
import platform
import re
import shutil
import socket
import sqlite3
import struct
import subprocess
import sys
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

TASK = "project-record-continuity"
NEW_SHA = "9ccd827d1dc4edbbda8b4a8bf30abe3867143950b828a7ffc5217c97e334e97a"
OLD_SHA = "5f34fe26f9efda64c46aed32a8eacb90af4af9c54426650f4b1f48fa5fcef888"
BEIJING = timezone(timedelta(hours=8))
REASON = "用户已批准恢复当前真实台账：依据 aha 留存唯一有效历史目录恢复项目关联，保留原消费、费用、占用和历史材料。"
IMMUTABLE = ("fact_identity_content", "versions", "projects", "claims", "revisions", "coverage", "counts")


class DeliveryError(RuntimeError):
    """Only a fixed, credential-free stage code is persisted or displayed."""


def require(condition, code):
    if not condition:
        raise DeliveryError(code)


def now():
    return datetime.now(BEIJING).isoformat()


def read_json(path):
    require(path.is_file() and not path.is_symlink(), "required_evidence_missing")
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    require(isinstance(value, dict), "invalid_evidence_object")
    return value


def sha(path):
    require(path.is_file() and not path.is_symlink(), "required_regular_file_missing")
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def write_json(path, value):
    require(not path.is_symlink(), "report_path_is_link")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name("." + path.name + "." + uuid4().hex + ".tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(json.dumps(value, ensure_ascii=False, indent=2).encode() + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def load_helper(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "helper_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def known_folder(identifier):
    class GUID(ctypes.Structure):
        _fields_ = [("a", ctypes.c_uint32), ("b", ctypes.c_uint16),
                    ("c", ctypes.c_uint16), ("d", ctypes.c_ubyte * 8)]

    guid = GUID.from_buffer_copy(UUID(identifier).bytes_le)
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    get = shell.SHGetKnownFolderPath
    get.argtypes = [ctypes.POINTER(GUID), ctypes.c_uint32, ctypes.c_void_p,
                    ctypes.POINTER(ctypes.c_void_p)]
    get.restype = ctypes.c_long
    memory = ctypes.c_void_p()
    require(get(ctypes.byref(guid), 0, None, ctypes.byref(memory)) == 0 and memory.value,
            "known_folder_lookup_failed")
    try:
        return Path(ctypes.wstring_at(memory.value)).resolve()
    finally:
        ole = ctypes.WinDLL("ole32")
        ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
        ole.CoTaskMemFree(memory)


def native_context(source):
    require(sys.platform == "win32" and struct.calcsize("P") * 8 == 64,
            "native_windows_x64_required")
    require(sys.prefix != sys.base_prefix, "isolated_native_interpreter_required")
    local = known_folder("F1B32785-6FBA-4FCF-9D55-7B8E7F157091")
    profile = known_folder("5E6C858F-0E22-4760-9AFE-EA3317B67173")
    require(Path(os.environ["LOCALAPPDATA"]).resolve() == local,
            "synthetic_localappdata_is_forbidden")
    require(Path(os.environ["USERPROFILE"]).resolve() == profile,
            "synthetic_userprofile_is_forbidden")
    task = Path(os.environ["AHA_QA_ROOT"]).resolve()
    require(read_json(task / "task-ownership.json").get("task") == TASK,
            "task_directory_ownership_mismatch")
    data = local / "aha"
    require(data.is_dir() and (data / "aha.sqlite3").is_file()
            and not data.is_relative_to(task) and not data.is_relative_to(source),
            "real_default_ledger_not_identified")
    desktop = known_folder("B4BFCC3A-DB2C-424C-B029-7FE99A87C641")
    require(desktop.is_dir(), "actual_desktop_unavailable")
    return task, data.resolve(), desktop


def current_source(source, research, release):
    expected = read_json(research / "product-file-sha256.json")
    source_files = {p.relative_to(source).as_posix() for p in (source / "src/aha").rglob("*")
                    if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"}
    require(source_files == {p for p in expected if p.startswith("src/aha/")},
            "product_source_file_set_changed")
    for relative, wanted in expected.items():
        path = source / relative
        require(not Path(relative).is_absolute() and ".." not in Path(relative).parts
                and path.resolve().is_relative_to(source.resolve())
                and sha(path) == wanted, "product_or_recipe_bytes_changed")
    # Same grouping and normalization as release.fingerprints, without depending
    # on Windows Git or accidentally hashing ignored interpreter cache files.
    groups = {key: {} for key in ("full", "tray", "materials", "recipe")}
    for relative in sorted(source_files | release.RECIPE_FILES):
        value = hashlib.sha256(release.normalized(relative, (source / relative).read_bytes())).hexdigest()
        groups["full"][relative] = value
        if relative in release.RECIPE_FILES:
            groups["recipe"][relative] = value
        elif Path(relative).name in release.TRAY_FILES:
            groups["tray"][relative] = value
        elif Path(relative).name in release.MATERIAL_FILES:
            groups["materials"][relative] = value
    calculated = {key: hashlib.sha256(canonical(value)).hexdigest() for key, value in groups.items()}
    require(calculated == read_json(research / "source-fingerprints.json"),
            "worktree_fingerprints_changed")
    require(calculated == read_json(research / "source-fingerprints-after-onefile.json"),
            "onefile_source_fingerprints_changed")
    return calculated, hashlib.sha256(canonical(expected)).hexdigest()


def gates(source, research, task, release):
    fingerprints, files_sha = current_source(source, research, release)
    python = read_json(research / "python-final.json")
    require(python.get("verified") is True and python.get("python_tests_passed") is True
            and python.get("tests_run", 0) >= 351
            and python.get("failures") == 0 and python.get("errors") == 0
            and python.get("skipped") == 0, "final_python_gate_incomplete")
    for name in ("ruff", "mypy", "compileall"):
        require(python.get(name, {}).get("passed") is True
                and python[name].get("returncode") == 0, "final_static_gate_incomplete")
    log = (research / "python-final.log").read_text(encoding="utf-8-sig")
    require(re.findall(r"(?m)^Ran (\d+) tests? in ", log) == [str(python["tests_run"])]
            and re.search(r"(?m)^OK\s*$", log), "python_log_report_mismatch")
    node = (research / "node-final.log").read_text(encoding="utf-8-sig")
    for name, expected in (("tests", 53), ("pass", 53), ("fail", 0), ("cancelled", 0), ("skipped", 0)):
        observed = re.findall(r"(?m)^[^\n]*\b" + name + r"\s+(\d+)\s*$", node)
        require(observed == [str(expected)], "final_node_gate_incomplete")
    reports = {}
    for label, executable in (("directory", task / "build/release/directory/aha/aha.exe"),
                              ("onefile", task / "build/release/portable/aha.exe")):
        cli = read_json(research / (label + "-verification.json"))
        require(cli.get("verified") is True and cli.get("schema_version") == 1
                and cli.get("executable_sha256") == sha(executable), "native_cli_gate_incomplete")
        ui = read_json(research / ("native-ui-" + label + ".json"))
        require(ui.get("verified") is True and ui.get("mode") == "exe"
                and ui.get("executable_sha256") == cli["executable_sha256"]
                and ui.get("original_facts_unchanged") is True
                and ui.get("console_error_count") == 0 and ui.get("page_error_count") == 0,
                "native_ui_gate_incomplete")
        for name, wanted in ui.get("ui_source_sha256", {}).items():
            require(name in {"app.js", "index.html", "style.css"}
                    and sha(source / "src/aha/web" / name) == wanted, "ui_source_binding_mismatch")
        require(set(ui.get("ui_source_sha256", {})) == {"app.js", "index.html", "style.css"},
                "ui_source_proof_missing")
        case = task / ui["case_id"]
        require(case.resolve().is_relative_to(task)
                and read_json(case / "task-ownership.json").get("task") == TASK,
                "ui_fixture_ownership_mismatch")
        require(sha(case / "materials/project-c.zip") == ui["material"]["sha256"],
                "verified_material_bytes_changed")
        materials = read_json(research / ("native-materials-" + label + ".json"))
        require(materials.get("verified") is True
                and materials.get("executable_sha256") == cli["executable_sha256"]
                and materials.get("material_sha256") == ui["material"]["sha256"],
                "native_material_gate_incomplete")
        excel = materials.get("excel", [])
        require(len(excel) == 2 and {item.get("file") for item in excel}
                == {"使用明细.csv", "每日汇总.csv"}
                and all(item.get("all_cells_match") is True and item.get("no_formulas") is True
                        for item in excel), "native_excel_gate_incomplete")
        printed = materials.get("print", {})
        pdf = Path(printed.get("pdf_path", ""))
        require(printed.get("precise_cost_and_assignment_note_preserved") is True
                and printed.get("all_rendered_pages_visually_reviewed") is True
                and printed.get("pages") == 1
                and pdf.resolve().is_relative_to(case.resolve())
                and sha(pdf) == printed.get("pdf_sha256"), "native_print_gate_incomplete")
        require(len(printed.get("rendered_pages", [])) == printed["pages"]
                and all(Path(path).is_file() and Path(path).resolve().is_relative_to(case.resolve())
                        for path in printed["rendered_pages"]), "rendered_print_evidence_missing")
        reports[label] = cli
    require(reports["onefile"]["executable_sha256"] == NEW_SHA, "unreviewed_onefile_identity")
    frozen = read_json(research / "frozen-real-copy-verification.json")
    require(frozen.get("verified") is True and frozen.get("executable_sha256") == NEW_SHA
            and frozen.get("facts_cost_tokens_claims_old_materials_unchanged") is True
            and frozen.get("ownership_survives_frozen_restart") is True
            and frozen.get("original_ledger_unchanged") is True
            and frozen.get("recovered_sessions") == 347
            and frozen.get("recovered_detail_count") == 37165, "frozen_real_copy_gate_incomplete")
    protection = read_json(research / "protection.json")
    require(protection.get("protected") is True
            and protection.get("old_executable_sha256") == OLD_SHA
            and sha(Path(protection["archive"])) == protection["archive_sha256"]
            and sha(Path(protection["old_executable"])) == OLD_SHA,
            "persistent_original_protection_mismatch")
    gate_names = ("python-final.json", "directory-verification.json", "onefile-verification.json",
                  "native-ui-directory.json", "native-ui-onefile.json", "native-materials-directory.json",
                  "native-materials-onefile.json", "frozen-real-copy-verification.json", "node-final.log")
    return {"fingerprints": fingerprints, "product_files_sha256": files_sha,
            "gate_sha256": {name: sha(research / name) for name in gate_names},
            "version": reports["onefile"]["version"], "protection": protection,
            "frozen": frozen, "tests_run": python["tests_run"]}


def runtime_facts(source, task, release):
    actual = {"windows": True, "isolated": sys.prefix != sys.base_prefix,
              "bits": struct.calcsize("P") * 8, "python": list(sys.version_info[:3]),
              "machine": platform.machine(), "sqlite": list(sqlite3.sqlite_version_info),
              "sqlite_version": sqlite3.sqlite_version, "packages": {}}
    for line in (source / "scripts/requirements-build.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, separator, wanted = line.partition("==")
        require(separator and importlib.metadata.version(name) == wanted, "fixed_build_dependency_drift")
        actual["packages"][name.lower().replace("_", "-")] = wanted
    from aha.migrations import sqlite_wal_safe

    require(actual["isolated"] and sqlite_wal_safe(tuple(actual["sqlite"])), "unsafe_native_runtime")
    probe_path = task / "build/runtime-versions.json"
    probe = read_json(probe_path)
    for field in ("windows", "bits", "isolated", "machine", "sqlite", "sqlite_version"):
        require(probe.get(field) == actual[field], "build_probe_runtime_drift")
    require(probe.get("python") == actual["python"][:2], "build_probe_python_drift")
    final = read_json(source / ".trellis/tasks/11-12-project-record-continuity/research/python-final.json")
    require(final["python"] == actual["python"] and final["sqlite"] == actual["sqlite_version"],
            "tested_runtime_drift")
    tools = {}
    for name in ("ruff", "mypy", "playwright", "pywin32", "pypdf", "pymupdf"):
        try:
            tools[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            pass
    return {"build_runtime": actual, "runtime_sha256": release.runtime_digest(source, "WORKTREE", actual),
            "build_runtime_probe_sha256": sha(probe_path), "qa_tools": tools}


def process_image(pid):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    query = kernel.QueryFullProcessImageNameW
    query.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_wchar_p,
                      ctypes.POINTER(ctypes.c_uint32)]
    handle = kernel.OpenProcess(0x1000, False, pid)
    require(handle, "instance_process_identity_unavailable")
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        length = ctypes.c_uint32(len(buffer))
        require(query(handle, 0, buffer, ctypes.byref(length)), "instance_image_unavailable")
        return Path(buffer.value)
    finally:
        kernel.CloseHandle(handle)


def existing_instance(data, Client):
    descriptor_path = data / "runtime.json"
    if not descriptor_path.exists():
        return None
    from aha.instance import _descriptor, profile_id

    descriptor = read_json(descriptor_path)
    require(_descriptor(descriptor, profile_id(data)) is not None, "unverified_default_descriptor")
    image_sha = sha(process_image(descriptor["pid"]))
    require(image_sha in {OLD_SHA, NEW_SHA}, "unrecognized_running_default_program")
    client = Client(descriptor)
    require(Path(client.json("GET", "/api/status")["data_directory"]).resolve() == data,
            "instance_data_directory_mismatch")
    return client, descriptor, image_sha


def port_closed(port):
    with socket.socket() as connection:
        connection.settimeout(0.3)
        return connection.connect_ex(("127.0.0.1", port)) != 0


def shutdown_default(data, instance):
    client, _, _ = instance
    try:
        client.json("POST", "/api/shutdown", {})
    except (OSError, TimeoutError, http.client.HTTPException):
        # A successful shutdown can close the response; observe the owned state.
        pass
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if not (data / "runtime.json").exists() and port_closed(client.port):
            return
        time.sleep(0.1)
    raise DeliveryError("verified_default_did_not_shutdown_normally")


def copy_program(source, target, *, optional=False):
    require(sha(source) == NEW_SHA, "verified_program_bytes_changed")
    if optional and not target.exists():
        return {"path": str(target), "updated": False, "reason": "not_present"}
    require(not target.is_symlink(), "program_target_is_link")
    if target.exists():
        observed = sha(target)
        if observed not in {OLD_SHA, NEW_SHA}:
            require(optional, "unrecognized_desktop_program_preserved")
            return {"path": str(target), "updated": False, "reason": "unrecognized_preserved"}
        if observed == NEW_SHA:
            return {"path": str(target), "updated": True, "already_matching": True}
    require(target.parent.is_dir(), "program_target_directory_unavailable")
    temporary = target.with_name(".aha-project-continuity-" + uuid4().hex + ".tmp")
    try:
        with source.open("rb") as first, temporary.open("xb") as second:
            shutil.copyfileobj(first, second, 1024 * 1024)
            second.flush()
            os.fsync(second.fileno())
        require(sha(temporary) == NEW_SHA, "delivery_copy_hash_mismatch")
        deadline = time.monotonic() + 15
        while True:
            require(not target.exists() or sha(target) in {OLD_SHA, NEW_SHA}, "program_changed_during_delivery")
            try:
                os.replace(temporary, target)
                break
            except PermissionError:
                require(time.monotonic() < deadline, "program_still_in_use_no_forced_exit")
                time.sleep(0.2)
        require(sha(target) == NEW_SHA, "delivered_program_hash_mismatch")
        return {"path": str(target), "updated": True, "already_matching": False}
    finally:
        temporary.unlink(missing_ok=True)


def ready_default(executable, data, Client):
    instance = existing_instance(data, Client)
    if instance is not None:
        require(instance[2] == NEW_SHA, "old_default_still_running")
        return instance[0], instance[1]
    process = subprocess.Popen([str(executable), "--no-browser"], cwd=executable.parent,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        if (data / "runtime.json").is_file():
            instance = existing_instance(data, Client)
            if instance is not None:
                require(instance[2] == NEW_SHA, "unexpected_default_instance_program")
                return instance[0], instance[1]
        require(process.poll() is None, "desktop_program_exited_before_ready")
        time.sleep(0.1)
    raise DeliveryError("desktop_default_startup_timeout")


def extra_preservation(data, snapshot):
    with closing(sqlite3.connect((data / "aha.sqlite3").as_uri() + "?mode=ro", uri=True)) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("PRAGMA trusted_schema=OFF")
        db.execute("BEGIN")
        result = {table: snapshot.digest_rows(db.execute(f"SELECT * FROM {table} ORDER BY rowid"))
                  for table in ("overrides", "batches", "batch_events", "source_profiles", "sync_runs")}
        packages = []
        for relative, expected in db.execute("SELECT DISTINCT zip_path,zip_hash FROM revisions ORDER BY zip_path"):
            path = data / relative
            require(path.resolve().is_relative_to(data) and sha(path) == expected,
                    "original_package_missing_or_changed")
            packages.append([relative, expected])
        result["package_count"] = len(packages)
        result["package_inventory_sha256"] = hashlib.sha256(canonical(packages)).hexdigest()
        result["projection_sha256"] = snapshot.digest_rows(db.execute(
            "SELECT record_key,project_id,assignment_origin,cwd FROM usage_records ORDER BY record_key"))
        db.rollback()
        return result


def preserve_equal(before, after):
    for field in IMMUTABLE:
        require(before[field] == after[field], "primary_immutable_fact_or_material_changed")
    for field in ("data_revision", "claim_revision"):
        require(before["business_revisions"][field] == after["business_revisions"][field],
                "unexpected_primary_data_or_claim_revision")


def extra_equal(before, after, *, projection=False):
    fields = set(before) if projection else set(before) - {"projection_sha256"}
    require(all(before[field] == after[field] for field in fields), "primary_extra_preservation_mismatch")


def backup_summary(result):
    return {key: result[key] for key in ("archive_path", "sha256", "size", "format_version",
                                       "store_schema_version", "counts")}


def apply_http(client, payload):
    connection = http.client.HTTPConnection("127.0.0.1", client.port, timeout=120)
    try:
        connection.request("POST", "/api/project-associations/apply", canonical(payload), headers={
            "Content-Type": "application/json", "Cookie": client.cookie,
            "Origin": client.origin, "X-AHA-CSRF": client.csrf})
        response = connection.getresponse()
        raw = response.read(8 * 1024 * 1024 + 1)
        require(response.status == 200 and len(raw) <= 8 * 1024 * 1024,
                "primary_apply_not_confirmed_replay_private_receipt")
        result = json.loads(raw)
        require(isinstance(result, dict) and result.get("applied") is True,
                "primary_apply_response_invalid")
        return result
    finally:
        connection.close()


def conservation(client):
    ledger_status = client.json("GET", "/api/ledger")
    coverage = ledger_status["coverage"]
    base = {"start_date": coverage["start_date"], "end_date": coverage["end_date"],
            "availability_mode": "all"}
    whole = client.json("POST", "/api/analysis", {**base, "project_id": "all"})
    from aha.decimal_sql import DecimalSum

    cost, count = DecimalSum(), 0
    token_fields = ("fresh_input_tokens", "output_tokens", "cache_read_tokens",
                    "cache_creation_tokens", "total_tokens")
    tokens = dict.fromkeys(token_fields, 0)
    identifiers = [item["id"] for item in client.json("GET", "/api/projects")["projects"]]
    for identifier in [*identifiers, "unassigned"]:
        part = client.json("POST", "/api/analysis", {**base, "project_id": identifier})
        require(all(part[field] == whole[field] for field in (
            "data_revision", "classification_revision", "claim_revision")), "analysis_changed_during_conservation")
        summary = part["summary"]
        count += summary["record_count"]
        cost.step(summary["total_cost_usd"])
        for field in token_fields:
            tokens[field] += summary[field]
    summary = whole["summary"]
    require(count == summary["record_count"] and cost.finalize() == summary["total_cost_usd"]
            and all(tokens[field] == summary[field] for field in token_fields),
            "projects_and_unassigned_do_not_conserve_total")
    return {"verified": True, "represented_record_count": count,
            "summary_sha256": hashlib.sha256(canonical(summary)).hexdigest()}


def main():
    source = Path(__file__).resolve().parents[4]
    research = Path(__file__).resolve().parent
    public = {"verified": False, "started_at": now(), "source_ref": "WORKTREE",
              "executable_sha256": NEW_SHA, "native_tray_enabled": True,
              "physical_tray_input": False, "synchronization_requested_by_script": False}
    stage = "validate_all_gates"
    try:
        task, data, desktop = native_context(source)
        sys.path.insert(0, str(source / "scripts"))
        sys.path.insert(0, str(source / "src"))
        import release
        from verify_windows_artifact import Client
        from aha.backup import create_backup, restore_backup

        gate = gates(source, research, task, release)
        runtime = runtime_facts(source, task, release)
        snapshot = load_helper(research / "prepare-real-copy.py", "delivery_fact_helpers")
        relations = load_helper(research / "verify-real-associations.py", "delivery_link_helpers")
        executable = task / "build/release/portable/aha.exe"
        destination = desktop / "aha.exe"
        persistent = Path(gate["protection"]["archive"]).parent
        require(persistent.is_dir() and persistent.drive.upper() == "D:", "persistent_recovery_directory_unavailable")
        private = task / "private-primary-recovery.json"
        state = read_json(private) if private.exists() else {
            "format_version": 1, "task": TASK, "executable_sha256": NEW_SHA,
            "data_directory": str(data), "created_at": now(),
        }
        require(state.get("task") == TASK and state.get("executable_sha256") == NEW_SHA
                and Path(state["data_directory"]).resolve() == data, "private_recovery_receipt_mismatch")
        public.update(source_fingerprints=gate["fingerprints"], product_files_sha256=gate["product_files_sha256"],
                      gate_sha256=gate["gate_sha256"], version=gate["version"], **runtime)
        if state.get("verified") is True:
            require(sha(destination) == NEW_SHA, "completed_desktop_artifact_changed")
            print(json.dumps({"verified": True, "already_completed": True,
                              "desktop": str(destination),
                              "desktop_executable": str(destination)}, ensure_ascii=False))
            return 0
        stage = "normal_shutdown_and_fresh_protection"
        running = existing_instance(data, Client)
        if "before" not in state:
            if running is not None:
                shutdown_default(data, running)
                public["previous_default_instance_exited_normally"] = True
            before = snapshot.facts(data / "aha.sqlite3")
            require(before["schema"] == 3, "initial_primary_schema_not_expected")
            extra = extra_preservation(data, snapshot)
            archive = persistent / ("aha-before-final-apply-" + uuid4().hex[:12] + ".aha-backup")
            protected = backup_summary(create_backup(data, archive))
            require(snapshot.facts(data / "aha.sqlite3") == before,
                    "primary_changed_while_creating_fresh_backup")
            extra_equal(extra, extra_preservation(data, snapshot), projection=True)
            state.update(before=before, extra_before=extra, backup_before=protected)
            write_json(private, state)
        else:
            require(sha(Path(state["backup_before"]["archive_path"])) == state["backup_before"]["sha256"],
                    "fresh_preapply_backup_missing_or_changed")
            preserve_equal(state["before"], snapshot.facts(data / "aha.sqlite3"))
            if running is not None and running[2] == OLD_SHA:
                shutdown_default(data, running)
        stage = "deliver_verified_onefile"
        desktop_result = copy_program(executable, destination)
        existing_result = copy_program(executable, Path("D:/Program Files/aha.exe"), optional=True)
        state["desktop_delivered"] = True
        write_json(private, state)
        stage = "start_desktop_against_default_primary"
        client, descriptor = ready_default(destination, data, Client)
        status = client.json("GET", "/api/status")
        require(status["version"] == gate["version"]
                and Path(status["data_directory"]).resolve() == data, "delivered_default_status_mismatch")
        current = snapshot.facts(data / "aha.sqlite3")
        require(current["schema"] == 4, "primary_did_not_upgrade_to_schema4")
        preserve_equal(state["before"], current)
        extra_equal(state["extra_before"], extra_preservation(data, snapshot))
        public["migration_preserves_facts_project_rules_claims_packages_and_coverage"] = True
        if "apply_payload" not in state:
            require(current["assigned"] == state["before"]["assigned"], "unreviewed_primary_assignment_change")
            require(extra_preservation(data, snapshot)["projection_sha256"]
                    == state["extra_before"]["projection_sha256"], "migration_changed_current_ownership")
            stage = "preview_authorized_primary_recovery"
            preview = client.json("POST", "/api/project-associations/preview", {"action": "recover"})
            selected = preview["summary"]
            require(selected["recovered_sessions"] == gate["frozen"]["recovered_sessions"] == 347
                    and selected["changed_count"] == gate["frozen"]["recovered_detail_count"] == 37165
                    and selected["selected_detail_count"] == 38978
                    and selected["directory_only_sessions"] == 50, "primary_preview_differs_from_verified_scope")
            state["preview_counts"] = {key: value for key, value in selected.items()
                                       if isinstance(value, int) and not isinstance(value, bool)}
            state["apply_payload"] = {"preview_id": preview["preview_id"], "reason": REASON,
                                      "idempotency_key": "primary-recovery-" + uuid4().hex}
            write_json(private, state)
        stage = "atomic_primary_apply_or_exact_idempotent_replay"
        result = apply_http(client, state["apply_payload"])
        require(result["changed_count"] == 37165 and result["recovered_sessions"] == 347,
                "primary_apply_counts_mismatch")
        require(result == apply_http(client, state["apply_payload"]), "primary_apply_not_idempotent")
        state["apply_result_sha256"] = hashlib.sha256(canonical(result)).hexdigest()
        state["applied"] = True
        write_json(private, state)
        stage = "verify_primary_preservation_and_conservation"
        after = snapshot.facts(data / "aha.sqlite3")
        preserve_equal(state["before"], after)
        extra_equal(state["extra_before"], extra_preservation(data, snapshot))
        require(after["assigned"] == state["before"]["assigned"] + result["changed_count"]
                and int(after["business_revisions"]["revision"]) == result["classification_revision"],
                "primary_assignment_delta_or_revision_mismatch")
        association = client.json("GET", "/api/project-associations")
        conservation_result = conservation(client)
        state["after"] = after
        state["relationships_after"] = relations.relationships(data / "aha.sqlite3", snapshot.digest_rows)
        state["extra_after"] = extra_preservation(data, snapshot)
        write_json(private, state)
        stage = "reopen_desktop_same_owned_service"
        reopened = subprocess.Popen([str(destination), "--no-browser"], cwd=desktop,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        require(reopened.wait(timeout=45) == 0, "desktop_reopen_failed")
        repeated = read_json(data / "runtime.json")
        require(all(repeated.get(key) == descriptor.get(key)
                    for key in ("run_id", "profile_id", "pid"))
                and client.json("GET", "/api/instance")["state"] == "ready",
                "desktop_reopen_did_not_reuse_owned_service")
        require(snapshot.facts(data / "aha.sqlite3") == after, "desktop_reopen_changed_primary_baseline")
        public["same_instance_reopened_without_new_sync"] = True
        stage = "post_recovery_complete_backup_and_independent_restore"
        if "backup_after" not in state:
            archive = persistent / ("aha-after-project-associations-" + uuid4().hex[:12] + ".aha-backup")
            state["backup_after"] = backup_summary(create_backup(data, archive))
            write_json(private, state)
        require(sha(Path(state["backup_after"]["archive_path"])) == state["backup_after"]["sha256"],
                "post_recovery_backup_changed")
        validation = task / ("primary-recovery-validation-" + uuid4().hex[:10])
        validation.mkdir(exist_ok=False)
        write_json(validation / "task-ownership.json", {"task": TASK, "purpose": "post-recovery-restore-validation"})
        restored = validation / "ledger"
        restore_backup(Path(state["backup_after"]["archive_path"]), restored)
        require(snapshot.facts(restored / "aha.sqlite3") == after, "post_recovery_restore_facts_mismatch")
        require(relations.relationships(restored / "aha.sqlite3", snapshot.digest_rows)
                == state["relationships_after"], "post_recovery_restore_ownership_mismatch")
        extra_equal(state["extra_after"], extra_preservation(restored, snapshot), projection=True)
        require(snapshot.facts(data / "aha.sqlite3") == after, "primary_changed_during_restore_validation")
        require(relations.relationships(data / "aha.sqlite3", snapshot.digest_rows)
                == state["relationships_after"], "primary_ownership_changed_during_final_validation")
        stage = "persist_verified_delivery_and_recovery_reports"
        public.update(verified=True, completed_at=now(), desktop=str(destination),
                      desktop_executable=str(destination),
                      desktop_sha256=sha(destination), desktop_started_and_verified=True,
                      existing_program=existing_result, desktop_delivery=desktop_result,
                      actual_data_directory=str(data), schema_before=state["before"]["schema"],
                      schema_after=after["schema"], counts_before=state["before"]["counts"],
                      counts_after=after["counts"], assigned_before=state["before"]["assigned"],
                      assigned_after=after["assigned"], recovered_sessions=347, recovered_detail_count=37165,
                      preview_counts=state["preview_counts"],
                      association_counts_after={key: value for key, value in association["summary"].items()
                                                if isinstance(value, int) and not isinstance(value, bool)},
                      immutable_fact_hashes={key: after[key] for key in IMMUTABLE if key != "counts"},
                      relationships_after=state["relationships_after"], conservation=conservation_result,
                      original_packages_and_claims_unchanged=True, coverage_and_project_rules_unchanged=True,
                      backup_before=state["backup_before"], backup_after=state["backup_after"],
                      protected_initial_archive=gate["protection"]["archive"],
                      preserved_old_executable=gate["protection"]["old_executable"],
                      independent_post_recovery_restore_verified=True,
                      independent_restore_directory=str(restored), real_default_instance_left_running=True)
        write_json(research / "primary-recovery.json", public)
        write_json(research / "delivery.json", public)
        state.update(verified=True, completed_at=public["completed_at"])
        write_json(private, state)
        print(json.dumps({"verified": True, "desktop": str(destination),
                          "desktop_executable": str(destination),
                          "recovered_sessions": 347, "recovered_detail_count": 37165,
                          "assigned_after": after["assigned"], "backup_before": state["backup_before"]["archive_path"],
                          "backup_after": state["backup_after"]["archive_path"]}, ensure_ascii=False, indent=2))
        return 0
    except Exception as error:
        public.update(verified=False, failed_at=now(), failure_stage=stage,
                      failure_type=type(error).__name__,
                      failure_code=str(error) if isinstance(error, DeliveryError) else "stage_failed_no_private_details",
                      automatic_rollback_attempted=False, unknown_processes_forcibly_stopped=False)
        write_json(research / "primary-recovery.json", public)
        write_json(research / "delivery.json", public)
        print(json.dumps({"verified": False, "stage": stage, "code": public["failure_code"],
                          "note": "保留已生成备份、私有重试凭据及当前实例；不自动回退或强制退出。"}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
