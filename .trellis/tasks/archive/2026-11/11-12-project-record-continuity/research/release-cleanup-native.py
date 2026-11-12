"""Read-only release inventory, or gated cleanup of the marked release-v050 root.

Run with the original native base interpreter, -X utf8 -B, outside the task root. Preparation
does not execute this script. Only --clean can curate evidence or delete files.
No junction is followed; only the known internal Edge compatibility link may be
detached. Real data, installed programs, base Python, source and Git are preserved.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import runpy
import shutil
import sqlite3
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


TASK = "project-record-continuity"
PURPOSE = "release-v050"
ROOT_NAME = "aha-release-v050-20261112"
M = "12d213b5b3c3c505d24f73fc7888966f24435337"
EXE_SHA = "8991fa71cadd906678cb1b76d302921d1e874f022918f854a0540f2bb3d0e4d5"
RUNTIME_SHA = "2d64ab084e0aa6c3d8ffab874ef7a08fd35b4fbf452dc1353e89d06dc7ea8642"
BASE = Path("C:/Users/djsyw/AppData/Roaming/uv/python/cpython-3.15.2-windows-x86_64-none")
MAX_FILE = 10 * 1024 * 1024
MAX_TOTAL = 20 * 1024 * 1024
REPARSE = stat.FILE_ATTRIBUTE_REPARSE_POINT


def require(condition, code):
    if not condition:
        raise RuntimeError(code)


def stamp():
    return datetime.now(timezone.utc).isoformat()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write(path, value):
    require(not path.is_symlink() and not (path.exists() and is_reparse(path.lstat())), "output_is_reparse")
    temporary = path.with_name("." + path.name + "." + uuid4().hex + ".tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(encoded(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def load(path):
    require(path.is_file() and not is_reparse(path.lstat()), "required_report_missing_or_linked")
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    require(isinstance(value, dict), "report_must_be_an_object")
    return value


def is_reparse(info):
    return bool(getattr(info, "st_file_attributes", 0) & REPARSE)


def plain_path(path, boundary):
    relative = path.relative_to(boundary)
    current = boundary
    require(not is_reparse(current.lstat()), "boundary_is_reparse")
    for name in relative.parts:
        current /= name
        require(not is_reparse(current.lstat()) and not current.is_symlink(), "evidence_ancestor_is_reparse")
    require(path.resolve().is_relative_to(boundary.resolve()), "evidence_outside_boundary")


def normalize_link(value):
    for prefix in ("\\\\?\\UNC\\", "\\??\\UNC\\"):
        if value.startswith(prefix):
            return Path("\\\\" + value[len(prefix):])
    for prefix in ("\\\\?\\", "\\??\\"):
        if value.startswith(prefix):
            return Path(value[len(prefix):])
    return Path(value)


def known_edge_junction(path, task):
    if not (path.is_junction() and path.name == "Content.IE5" and path.parent.name == "INetCache"):
        return None
    target = normalize_link(os.readlink(path))
    expected = path.parent / "IE"
    if (not target.is_absolute() or not expected.is_dir() or is_reparse(expected.lstat())
            or target.resolve() != expected.resolve() or not target.resolve().is_relative_to(task)):
        return None
    return {"path": str(path), "target": str(target.resolve()), "action": "detach_link_only"}


def known_top_level(name):
    exact = {"association-fixture-info.json", "association-ui-fixture-v2", "association-ui-schema3.aha-backup",
             "baseline-source", "build", "cloud-v050-assets", "cloud-v050-assets.zip", "cloud-zstd-wheel.zip",
             "compiled-source", "mypy-release-win", "pip-cache", "pycache", "qa315", "ruff-cache",
             "runtime-preparation-profile", "runtime-provenance", "runtime315-sqlite3534", "setup-native.log",
             "synthetic-profile", "task-ownership.json", "trusted-zstd-wheel"}
    return name in exact or any(re.fullmatch(pattern, name) for pattern in (
        r"qa-profile-[0-9]+",
        r"association-ui-release-(?:directory|cloud-onefile|desktop)(?:-[a-z0-9-]+)?",
        r"verify-(?:directory|onefile|cloud-onefile|desktop)(?:-[a-z0-9-]+)?",
        r"release-desktop-delivery-state-[0-9a-f]{16}\.json"))


def inventory(task):
    require(task.is_dir() and not is_reparse(task.lstat()), "task_root_is_not_a_plain_directory")
    categories, files, directories, junctions, blocked, manifest = {}, [], [], [], [], []
    stack = [task]
    while stack:
        directory = stack.pop()
        directories.append(directory)
        info = directory.lstat()
        require(not is_reparse(info), "directory_changed_to_reparse_during_inventory")
        with os.scandir(directory) as entries:
            for entry in sorted(entries, key=lambda item: item.name.casefold()):
                path = directory / entry.name
                relative = path.relative_to(task)
                info = entry.stat(follow_symlinks=False)
                if entry.name == ".git" or (directory == task and not known_top_level(entry.name)):
                    blocked.append({"path": str(path), "reason": "unrecognized_or_source_checkout"})
                    continue
                if is_reparse(info) or entry.is_symlink():
                    known = known_edge_junction(path, task)
                    if known:
                        junctions.append(known)
                    else:
                        blocked.append({"path": str(path), "reason": "unknown_reparse_point"})
                    continue  # Never traverse any reparse point, including known junctions.
                if stat.S_ISDIR(info.st_mode):
                    manifest.append([relative.as_posix(), "directory", info.st_mtime_ns])
                    stack.append(path)
                elif stat.S_ISREG(info.st_mode):
                    category = relative.parts[0] if len(relative.parts) > 1 else "root-files"
                    categories[category] = categories.get(category, 0) + info.st_size
                    files.append((path, info.st_size, info.st_mtime_ns))
                    manifest.append([relative.as_posix(), "file", info.st_size, info.st_mtime_ns])
                else:
                    blocked.append({"path": str(path), "reason": "unknown_file_kind"})
    manifest.extend([[item["path"], "known_junction", item["target"]] for item in junctions])
    summary = {"files": len(files), "directories": len(directories), "logical_bytes": sum(item[1] for item in files),
               "categories": categories, "known_internal_edge_junctions": junctions, "blocked_entries": blocked,
               "entry_manifest_sha256": hashlib.sha256(encoded(sorted(manifest))).hexdigest()}
    return summary, files, directories


def active_processes(task):
    # Command lines may contain private launch addresses: inspect only in memory.
    powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    query = ("$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.UTF8Encoding]::new(); "
             "Get-CimInstance Win32_Process | Select-Object ProcessId,Name,ExecutablePath,CommandLine | ConvertTo-Json -Compress")
    checked = subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-Command", query],
                             capture_output=True, text=True, encoding="utf-8-sig", check=True, timeout=30)
    rows = json.loads(checked.stdout)
    if isinstance(rows, dict):
        rows = [rows]
    targets = {str(task).casefold().replace("/", "\\")}
    import ctypes

    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.GetShortPathNameW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
    output = ctypes.create_unicode_buffer(32768)
    if api.GetShortPathNameW(str(task), output, len(output)):
        targets.add(output.value.casefold())
    task_processes, excel = [], []
    for row in rows:
        if row["ProcessId"] == os.getpid():
            continue
        if str(row.get("Name", "")).casefold() == "excel.exe":
            excel.append({"pid": row["ProcessId"], "name": "EXCEL.EXE"})
        if any(target in str(row.get(field) or "").casefold().replace("/", "\\")
               for target in targets for field in ("ExecutablePath", "CommandLine")):
            task_processes.append({"pid": row["ProcessId"], "name": row.get("Name"),
                                   "executable": row.get("ExecutablePath")})
    return {"task_root_processes": task_processes, "excel_processes_observed": excel}


def require_idle(processes):
    require(not processes["task_root_processes"], "task_root_process_still_running")
    # Excel observations are reported for review. Unrelated user workbooks never
    # trigger an automatic close/kill or a blanket requirement to close Excel.
    # A known task-root command line still blocks above; open/locked task files
    # cause the guarded deletion to stop rather than forcing access.


def product_state(source, research, helpers):
    sys.path[:0] = [str(source / "src"), str(source / "scripts")]
    import release

    candidate = load(research / "release-candidate-source.json")
    cloud = load(research / "release-cloud-assets.json")
    fingerprints = runpy.run_path(str(research / "release-final-native-checks.py"))["source_fingerprints"](source, release)
    require(candidate["source_sha"] == cloud["source_sha"] == M and candidate["version"] == cloud["version"] == "0.5.0"
            and fingerprints == candidate["source_fingerprints"] == cloud["fingerprints"]
            and cloud["runtime_sha256"] == RUNTIME_SHA
            and release.runtime_digest(source, "WORKTREE", cloud["build_runtime"]) == RUNTIME_SHA,
            "published_source_or_runtime_fingerprint_changed")
    initial = load(research / "release-private-runtime.json")
    require(sqlite3.sqlite_version == "3.53.1" and tuple(sys.version_info[:3]) == (3, 15, 2)
            and Path(sys.base_prefix).resolve() == BASE.resolve() and sys.prefix == sys.base_prefix,
            "use_original_external_base_cpython315_runtime")
    base_hashes = {name: digest(BASE / "DLLs" / name) for name in ("sqlite3.dll", "_sqlite3.pyd")}
    require(base_hashes == initial["base_sqlite_files_sha256"], "original_base_sqlite_was_modified")
    bridge = runpy.run_path(str(research / "release-prepare-ui-template.py"))["git_command"]
    head = subprocess.run(bridge(source, "rev-parse", "HEAD"), capture_output=True,
                          text=True, encoding="utf-8", check=True, timeout=30).stdout.strip()
    return {"source_sha": M, "source_fingerprints": fingerprints, "runtime_sha256": RUNTIME_SHA,
            "current_worktree_head": head, "cleanup_base_sqlite": sqlite3.sqlite_version,
            "original_base_sqlite_files_sha256": base_hashes}


def gates(research):
    names = ("release-desktop-delivery.json", "release-desktop-verification.json",
             "release-native-ui-directory.json", "release-native-ui-cloud-onefile.json",
             "release-native-materials-directory.json", "release-native-materials-cloud-onefile.json",
             "release-cloud-assets.json", "release-cloud-onefile-verification.json", "release-publication.json")
    reports = {name: load(research / name) for name in names}
    require(all(value.get("verified") is True for value in reports.values()), "required_release_gate_incomplete")
    cloud = reports["release-cloud-assets.json"]
    publication = reports["release-publication.json"]
    require(publication.get("published") is True and publication.get("version") == "0.5.0"
            and publication.get("source_sha") == M and publication.get("runtime_sha256") == RUNTIME_SHA
            and publication.get("executable_sha256") == cloud["executable_sha256"] == EXE_SHA
            and publication.get("public_asset_sha256") == cloud["file_sha256"]
            and set(publication["public_asset_sha256"]) == {"aha-0.5.0-windows-x64.exe", "SHA256SUMS.txt", "build-info.json"},
            "public_release_and_all_three_assets_not_confirmed")
    for name in ("release-desktop-delivery.json", "release-desktop-verification.json", "release-cloud-onefile-verification.json"):
        require(reports[name].get("executable_sha256") == EXE_SHA and reports[name].get("version") == "0.5.0",
                "desktop_or_cloud_verification_artifact_mismatch")
        for field, expected in (("source_sha", M), ("runtime_sha256", RUNTIME_SHA)):
            if field in reports[name]:
                require(reports[name][field] == expected, "release_gate_binding_mismatch")
    for label, expected_sha in (("directory", load(research / "release-directory-verification.json")["executable_sha256"]),
                                ("cloud-onefile", EXE_SHA)):
        ui_name = "release-native-ui-" + label + ".json"
        ui = reports[ui_name]
        material = reports["release-native-materials-" + label + ".json"]
        require(ui["executable_sha256"] == material["executable_sha256"] == expected_sha
                and ui["original_facts_unchanged"] is True
                and ui["console_error_count"] == ui["page_error_count"] == 0
                and material["ui_report_sha256"] == digest(research / ui_name)
                and material["material_sha256"] == ui["material"]["sha256"]
                and len(material["excel"]) == 2
                and all(item["all_cells_match"] is True and item["no_formulas"] is True for item in material["excel"])
                and material["print"]["pages"] == 1
                and material["print"]["precise_cost_and_assignment_note_preserved"] is True
                and material["print"]["all_rendered_pages_visually_reviewed"] is True,
                "native_ui_excel_a4_or_visual_review_not_confirmed")
    return reports, {name: digest(research / name) for name in names}


def default_health(helpers, delivery):
    sys.path[:0] = [str(Path(__file__).resolve().parents[4] / "src"),
                    str(Path(__file__).resolve().parents[4] / "scripts")]
    from aha.instance import _descriptor, profile_id
    from verify_windows_artifact import Client

    local = helpers["known_folder"]("F1B32785-6FBA-4FCF-9D55-7B8E7F157091")
    desktop = helpers["known_folder"]("B4BFCC3A-DB2C-424C-B029-7FE99A87C641") / "aha.exe"
    data = local / "aha"
    require(Path(delivery["data_directory"]).resolve() == data.resolve() and digest(desktop) == EXE_SHA,
            "real_default_data_or_desktop_identity_mismatch")
    descriptor = load(data / "runtime.json")  # Kept exclusively in process memory.
    require(_descriptor(descriptor, profile_id(data)) is not None
            and digest(helpers["process_image"](descriptor["pid"])) == EXE_SHA,
            "default_service_executable_unverified")
    client = Client(descriptor)
    status = client.json("GET", "/api/status")
    require(status["version"] == "0.5.0" and Path(status["data_directory"]).resolve() == data.resolve(),
            "default_service_not_ready_with_expected_ledger")
    for program in delivery["delivery"]:
        if program.get("updated") is True:
            require(digest(Path(program["path"])) == EXE_SHA, "delivered_persistent_program_changed")
    return {"desktop": str(desktop), "executable_sha256": EXE_SHA, "ready": True, "version": "0.5.0"}


def preservation(research, helpers, delivery):
    protection = load(research / "protection.json")
    require(digest(Path(protection["archive"])) == protection["archive_sha256"]
            and digest(Path(protection["old_executable"])) == protection["old_executable_sha256"],
            "original_persistent_protection_changed")
    backup = delivery["backup_before"]
    require(digest(Path(backup["archive_path"])) == backup["sha256"], "pre_release_backup_changed")
    for rollback in delivery["rollback_programs"]:
        require(digest(Path(rollback["path"])) == rollback["sha256"], "pre_release_rollback_program_changed")
    return default_health(helpers, delivery)


def retention_plan(task, source, research, reports):
    plan = []

    def add(origin, relative, boundary):
        plain_path(origin, boundary)
        require(origin.is_file() and origin.stat().st_size <= MAX_FILE, "evidence_missing_or_exceeds_ten_mib")
        require(origin.suffix.casefold() not in {".db", ".sqlite", ".sqlite3", ".exe", ".dll", ".pyd", ".whl"},
                "runtime_or_database_cannot_be_retained")
        plan.append({"origin": origin, "relative": Path(relative), "bytes": origin.stat().st_size,
                     "sha256": digest(origin), "temporary": origin.is_relative_to(task)})

    for label in ("directory", "cloud-onefile"):
        ui = reports["release-native-ui-" + label + ".json"]
        material = reports["release-native-materials-" + label + ".json"]
        case = task / ui["case_id"]
        owned = load(case / "task-ownership.json")
        require(owned.get("task") == TASK and owned.get("synthetic") is True, "ui_case_not_owned_synthetic_data")
        package = case / "materials/project-c.zip"
        require(digest(package) == ui["material"]["sha256"]
                and digest(case / "materials/project-c-redownloaded.zip") == digest(package), "frozen_ui_package_changed")
        add(package, Path(label) / "project-c.zip", task)
        for width in (1440, 375):
            add(case / f"projects-{width}.png", Path(label) / f"projects-{width}.png", task)
        printed = material["print"]
        pdf = task / printed["pdf_relative_path"]
        require(digest(pdf) == printed["pdf_sha256"]
                and len(printed["rendered_pages"]) == printed["pages"], "a4_artifact_changed")
        add(pdf, Path(label) / "project-c-a4.pdf", task)
        for index, relative in enumerate(printed["rendered_pages"], 1):
            add(task / relative, Path(label) / f"a4-page-{index}.png", task)
        for filename in ("使用明细.csv", "每日汇总.csv", "费用说明.html", "导出信息.json"):
            add(pdf.parent / filename, Path(label) / filename, task)
    report_names = ("python315-release.json", "release-candidate-source.json", "release-private-runtime.json",
                    "release-installed-runtime.json", "release-trusted-wheel.json", "release-previous-public-runtime.json",
                    "release-directory-build.json", "release-directory-verification.json", "release-onefile-build.json",
                    "release-onefile-verification.json", "release-cloud-assets.json", "release-cloud-onefile-verification.json",
                    "release-native-ui-directory.json", "release-native-ui-cloud-onefile.json",
                    "release-native-materials-directory.json", "release-native-materials-cloud-onefile.json",
                    "release-desktop-delivery.json", "release-desktop-verification.json", "release-publication.json")
    for name in report_names:
        add(research / name, Path("reports") / name, source)
    for name in ("release-post-publication-runtime.json", "release-user-tray-confirmation.json",
                 "release-user-tray-v050.json", "release-acceptance-evaluation.json"):
        if (research / name).is_file():
            add(research / name, Path("reports") / name, source)
    for name in ("release-python-tests.log", "release-ruff.log", "release-mypy.log", "release-compileall.log",
                 "release-directory-build.log", "release-directory-verification.log", "release-onefile-build.log",
                 "release-onefile-verification.log", "release-wheel-install.log", "release-directory-egg-info.log"):
        add(research / name, Path("logs") / name, source)
    for origin, name in ((task / "task-ownership.json", "task-ownership.json"),
                         (task / "trusted-zstd-wheel/provenance.json", "trusted-wheel-provenance.json"),
                         (task / "cloud-v050-assets/SHA256SUMS.txt", "SHA256SUMS.txt"),
                         (task / "cloud-v050-assets/build-info.json", "build-info.json"),
                         (task / "build/runtime-versions.json", "local-build-runtime-versions.json")):
        add(origin, Path("provenance") / name, task)
    require(sum(item["bytes"] for item in plan) + 128 * 1024 <= MAX_TOTAL, "curated_evidence_exceeds_twenty_mib")
    require(len({str(item["relative"]).casefold() for item in plan}) == len(plan), "retention_destination_collision")
    return plan


def curate(plan, retained):
    require(not retained.exists() or not is_reparse(retained.lstat()), "retention_root_is_reparse")
    retained.mkdir(exist_ok=True)
    marker = retained / "retention-ownership.json"
    ownership = {"task": TASK, "purpose": PURPOSE, "source_sha": M, "executable_sha256": EXE_SHA}
    if marker.exists():
        require(load(marker) == ownership, "retention_directory_ownership_mismatch")
    else:
        require(not any(retained.iterdir()), "unowned_nonempty_retention_directory")
        write(marker, ownership)
    allowed = {item["relative"].as_posix() for item in plan} | {"retention-ownership.json", "manifest.json", "release-cleanup.json"}
    for path in retained.rglob("*"):
        require(not is_reparse(path.lstat()), "retention_tree_contains_reparse")
        if path.is_file():
            require(path.relative_to(retained).as_posix() in allowed, "unknown_persistent_evidence_preserved")
    mapping = []
    for item in plan:
        target = retained / item["relative"]
        target.parent.mkdir(parents=True, exist_ok=True)
        plain_path(target.parent, retained)
        if target.exists():
            require(not is_reparse(target.lstat()) and digest(target) == item["sha256"], "existing_retained_file_conflicts")
        else:
            temporary = target.with_name("." + target.name + "." + uuid4().hex + ".tmp")
            try:
                shutil.copyfile(item["origin"], temporary)
                require(digest(temporary) == item["sha256"], "retention_copy_hash_mismatch")
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
        require(digest(target) == digest(item["origin"]) == item["sha256"], "retained_evidence_changed")
        mapping.append({"original_path": str(item["origin"]), "original_temporary_path": str(item["origin"]) if item["temporary"] else None,
                        "path": str(target), "sha256": item["sha256"], "bytes": item["bytes"]})
    return mapping


def delete_inventory(task, snapshot, files, directories):
    for junction in snapshot["known_internal_edge_junctions"]:
        path = Path(junction["path"])
        require(known_edge_junction(path, task) == junction, "edge_junction_changed_before_detach")
        os.rmdir(path)  # Link only; the real internal IE directory is counted separately.
    marker = task / "task-ownership.json"
    for path, size, modified in sorted(files, key=lambda item: (item[0] == marker, str(item[0]))):
        plain_path(path, task)
        info = path.lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_size == size and info.st_mtime_ns == modified,
                "file_changed_after_last_inventory")
        try:
            path.unlink()
        except PermissionError:
            require(bool(getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_READONLY),
                    "task_file_still_in_use_or_access_denied")
            os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
            path.unlink()
    for path in sorted(directories, key=lambda item: len(item.parts), reverse=True):
        plain_path(path, task)
        require(stat.S_ISDIR(path.lstat().st_mode), "directory_changed_before_removal")
        os.rmdir(path)  # New/unknown entries cause failure; no recursive follow or force.


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()
    research = Path(__file__).resolve().parent
    source = Path(__file__).resolve().parents[4]
    require(sys.platform == "win32", "native_windows_required")
    helpers = runpy.run_path(str(research / "deliver-and-recover.py"))
    local = helpers["known_folder"]("F1B32785-6FBA-4FCF-9D55-7B8E7F157091")
    task = local / "Temp" / ROOT_NAME
    require(task.is_dir() and not is_reparse(task.lstat()), "marked_release_root_missing_or_linked")
    require(not Path(sys.executable).resolve().is_relative_to(task.resolve())
            and not Path(sys.base_prefix).resolve().is_relative_to(task.resolve()), "cleanup_interpreter_is_inside_task")
    require(sys.dont_write_bytecode and Path(os.environ["LOCALAPPDATA"]).resolve() == local
            and not Path(os.environ["TEMP"]).resolve().is_relative_to(task), "base_minus_B_and_real_external_profile_required")
    marker = load(task / "task-ownership.json")
    require(marker.get("task") == TASK and marker.get("purpose") == PURPOSE
            and marker.get("cleanup_after_release") is True
            and Path(marker["source"]).resolve() == source.resolve(), "release_root_ownership_mismatch")
    snapshot, files, directories = inventory(task)
    processes = active_processes(task)
    if not args.clean:
        print(json.dumps({"mode": "read_only_inventory", "task_root": str(task), "inventory": snapshot,
                          "active_processes": processes, "c_free_bytes": shutil.disk_usage(task.anchor).free,
                          "will_not_clean_without_completed_publication_gates": True}, ensure_ascii=False, indent=2))
        return 0
    report = {"verified": False, "started_at": stamp(), "task_root": str(task), "source_sha": M,
              "executable_sha256": EXE_SHA, "runtime_sha256": RUNTIME_SHA, "forced_process_termination": False,
              "inventory_before_delete": snapshot, "deletion_started": False}
    try:
        require(not snapshot["blocked_entries"], "inventory_contains_unrecognized_objects_or_reparse_points")
        require_idle(processes)
        state_before = product_state(source, research, helpers)
        checked, gate_hashes = gates(research)
        health_before = preservation(research, helpers, checked["release-desktop-delivery.json"])
        persistent = Path(load(research / "protection.json")["archive"]).parent
        require(persistent.is_dir() and persistent.drive.upper() == "D:"
                and not persistent.resolve().is_relative_to(task.resolve())
                and not is_reparse(persistent.lstat()), "persistent_evidence_directory_invalid")
        retained = persistent / "acceptance-records-v0.5.0"
        plan = retention_plan(task, source, research, checked)
        mapping = curate(plan, retained)
        manifest = {"verified": True, "retained_root": str(retained), "source_sha": M,
                    "executable_sha256": EXE_SHA, "files": mapping,
                    "purpose": "Whitelisted small synthetic UI/Office and release QA records only",
                    "existing_acceptance_report_bytes_unchanged": True,
                    "single_file_limit_bytes": MAX_FILE, "total_limit_bytes": MAX_TOTAL}
        write(research / "release-retained-evidence.json", manifest)
        write(retained / "manifest.json", manifest)
        final_processes = active_processes(task)
        require_idle(final_processes)
        latest, latest_files, latest_directories = inventory(task)
        require(not latest["blocked_entries"] and latest["entry_manifest_sha256"] == snapshot["entry_manifest_sha256"],
                "task_tree_changed_while_curating_evidence")
        require(product_state(source, research, helpers) == state_before, "source_or_base_runtime_changed_before_cleanup")
        free_before = shutil.disk_usage(task.anchor).free
        report["deletion_started"] = True
        delete_inventory(task, latest, latest_files, latest_directories)
        require(not task.exists(), "task_root_not_fully_removed")
        free_after = shutil.disk_usage(task.anchor).free
        require(product_state(source, research, helpers) == state_before, "source_or_base_runtime_changed_after_cleanup")
        health_after = preservation(research, helpers, checked["release-desktop-delivery.json"])
        require(health_before == health_after, "desktop_or_default_service_changed_during_cleanup")
        require(all(digest(research / name) == expected for name, expected in gate_hashes.items()), "acceptance_report_bytes_changed")
        report.update(verified=True, completed_at=stamp(), removed_root=str(task), ownership_marker_verified=True,
                      active_task_processes_before_delete=[], excel_processes_observed_before_delete=final_processes["excel_processes_observed"],
                      logical_bytes_removed=snapshot["logical_bytes"], observed_c_free_bytes_before=free_before,
                      observed_c_free_bytes_after=free_after, observed_c_free_bytes_delta=free_after - free_before,
                      free_space_delta_may_include_other_system_activity=True,
                      retained_root=str(retained), retained_curated_payload_bytes=sum(item["bytes"] for item in plan),
                      source_and_original_base_runtime_unchanged=True, product_state_preserved=state_before,
                      desktop_and_default_service_health_after=health_after, acceptance_gate_sha256=gate_hashes,
                      known_edge_links_detached_without_following=True,
                      preserved=["real LocalAppData/aha and sidecars", "Desktop/D production programs",
                                 "all persistent D backups and rollback EXEs", "original base CPython315", "source/Git/Trellis"])
        # Include both generated receipts within the same total-size ceiling.
        for _ in range(5):
            cleanup_bytes = encoded(report)
            generated = {"original_path": str(research / "release-cleanup.json"), "original_temporary_path": None,
                         "path": str(retained / "release-cleanup.json"), "sha256": hashlib.sha256(cleanup_bytes).hexdigest(),
                         "bytes": len(cleanup_bytes)}
            manifest["generated_cleanup_receipt"] = generated
            total = sum(item["bytes"] for item in plan) + len(cleanup_bytes) + len(encoded(manifest)) + (retained / "retention-ownership.json").stat().st_size
            if report.get("retained_total_bytes") == total:
                break
            report["retained_total_bytes"] = total
        require(total <= MAX_TOTAL, "retained_receipts_exceed_twenty_mib")
        write(research / "release-cleanup.json", report)
        write(retained / "release-cleanup.json", report)
        write(research / "release-retained-evidence.json", manifest)
        write(retained / "manifest.json", manifest)
        actual_retained = sum(path.stat().st_size for path in retained.rglob("*") if path.is_file())
        require(actual_retained == report["retained_total_bytes"] <= MAX_TOTAL, "retained_total_byte_check_failed")
        print(json.dumps({"verified": True, "logical_bytes_removed": report["logical_bytes_removed"],
                          "observed_c_free_bytes_delta": report["observed_c_free_bytes_delta"],
                          "retained_total_bytes": actual_retained, "retained_root": str(retained)}, ensure_ascii=False, indent=2))
        return 0
    except Exception as error:
        report.update(verified=False, failed_at=stamp(), failure_type=type(error).__name__,
                      failure_code=str(error) if isinstance(error, RuntimeError) else "cleanup_stage_failed",
                      task_root_still_exists=task.exists(), automatic_rollback_attempted=False)
        write(research / "release-cleanup.json", report)
        print(json.dumps({"verified": False, "code": report["failure_code"],
                          "deletion_started": report["deletion_started"], "unknown_processes_or_files_were_not_forced": True}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
