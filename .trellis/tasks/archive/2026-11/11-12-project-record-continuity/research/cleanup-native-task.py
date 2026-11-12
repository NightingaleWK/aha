"""Inventory/clean only this task's marked Windows temporary tree.

Run with the base native interpreter, outside qa312. Default is read-only.
--clean requires completed delivery/recovery/desktop verification reports.
"""

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path


EXPECTED_SHA = "9ccd827d1dc4edbbda8b4a8bf30abe3867143950b828a7ffc5217c97e334e97a"


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def write(path, value):
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def owned_processes(task):
    ps = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    query = (
        "$ErrorActionPreference='Stop'; "
        "Get-CimInstance Win32_Process | "
        "Select-Object ProcessId,ExecutablePath,CommandLine | ConvertTo-Json -Compress"
    )
    result = subprocess.run([str(ps), "-NoProfile", "-NonInteractive", "-Command", query],
                            check=True, capture_output=True, text=True, encoding="utf-8")
    rows = json.loads(result.stdout)
    if isinstance(rows, dict):
        rows = [rows]
    target = str(task).casefold()
    # Inspect command lines only in memory; never retain arguments/credentials.
    return [{"pid": row["ProcessId"], "executable": row.get("ExecutablePath")}
            for row in rows if row["ProcessId"] != os.getpid()
            and any(target in str(row.get(key) or "").casefold()
                    for key in ("ExecutablePath", "CommandLine"))]


def inventory(task):
    categories = {}
    junctions = []
    count = 0
    total = 0
    for parent, directories, files in os.walk(task, followlinks=False):
        root = Path(parent)
        for item in [root, *(root / name for name in directories), *(root / name for name in files)]:
            info = item.lstat()
            assert not item.is_symlink(), f"Unexpected symlink: {item}"
            if getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                # Native Edge creates this compatibility junction in isolated
                # profiles. Inspect its boundary, do not follow it in the walk.
                target = Path(os.readlink(item).removeprefix("\\\\?\\")).resolve()
                assert item.is_junction() and item.name == "Content.IE5"
                assert item.parent.name == "INetCache" and item != root
                assert target == (item.parent / "IE").resolve() and target.is_relative_to(task.resolve())
                junctions.append({"path": str(item), "target": str(target), "action": "detach junction only"})
                directories.remove(item.name)
        assert ".git" not in directories and ".git" not in files, "Unexpected source checkout"
        for name in files:
            item = root / name
            size = item.stat().st_size
            relative = item.relative_to(task)
            category = relative.parts[0] if len(relative.parts) > 1 else "root-files"
            categories[category] = categories.get(category, 0) + size
            total += size
            count += 1
    return {"files": count, "logical_bytes": total, "categories": categories,
            "known_internal_edge_junctions": junctions}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()
    research = Path(__file__).resolve().parent
    source = research.parents[3]
    task = Path(os.environ["LOCALAPPDATA"]) / "Temp/aha-project-record-continuity-20261112"
    assert task.name == "aha-project-record-continuity-20261112" and task.is_dir()
    marker = load(task / "task-ownership.json")
    assert marker["task"] == "project-record-continuity"
    assert Path(marker["source"]).resolve() == source.resolve()
    assert not Path(os.sys.executable).resolve().is_relative_to(task.resolve())
    snapshot = inventory(task)
    processes = owned_processes(task)
    if not args.clean:
        print(json.dumps({"task_root": str(task), "inventory": snapshot,
                          "active_task_processes": processes}, ensure_ascii=False))
        return
    assert not processes, f"Task resources still in use: {processes}"
    expected_files = load(research / "product-file-sha256.json")
    assert all(digest(source / relative) == value for relative, value in expected_files.items())
    for name in ("python-final.json", "directory-verification.json", "onefile-verification.json",
                 "frozen-real-copy-verification.json", "native-materials-directory.json",
                 "native-materials-onefile.json", "desktop-verification.json",
                 "native-ui-desktop.json", "primary-recovery.json", "delivery.json"):
        assert load(research / name)["verified"], f"Incomplete gate: {name}"
    protection = load(research / "protection.json")
    retained = Path(protection["archive"]).parent / "acceptance-records"
    assert not retained.is_relative_to(task)
    retained.mkdir(exist_ok=True)
    files = []

    def retain(origin, destination):
        assert origin.is_file() and origin.resolve().is_relative_to(task.resolve())
        assert origin.stat().st_size < 10 * 1024 * 1024, f"Not small evidence: {origin}"
        target = retained / destination
        target.parent.mkdir(parents=True, exist_ok=True)
        origin_sha = digest(origin)
        if target.exists():
            assert digest(target) == origin_sha, f"Unknown retained file: {target}"
        else:
            shutil.copy2(origin, target)
        assert digest(target) == origin_sha
        files.append({"original_temporary_path": str(origin), "path": str(target),
                      "sha256": origin_sha, "bytes": target.stat().st_size})
        return target

    for label in ("directory", "onefile", "desktop"):
        ui = load(research / f"native-ui-{label}.json")
        case = task / ui["case_id"]
        case_marker = load(case / "task-ownership.json")
        assert case_marker.get("synthetic") is True, f"Case not synthetic: {case}"
        retain(case / "materials/project-c.zip", Path(label) / "project-c.zip")
        assert digest(case / "materials/project-c.zip") == digest(case / "materials/project-c-redownloaded.zip")
        for width in (1440, 375):
            retain(case / f"projects-{width}.png", Path(label) / f"projects-{width}.png")
        if label != "desktop":
            report_path = research / f"native-materials-{label}.json"
            report = load(report_path)
            office = Path(report["print"]["pdf_path"]).parent
            retain(office / "project-c-a4.pdf", Path(label) / "project-c-a4.pdf")
            retain(office / "a4-page-1.png", Path(label) / "a4-page-1.png")
            for filename in ("使用明细.csv", "每日汇总.csv", "导出信息.json", "费用说明.html"):
                retain(office / filename, Path(label) / filename)
    assert sum(item["bytes"] for item in files) < 20 * 1024 * 1024
    manifest = {"retained_root": str(retained), "files": files,
                "purpose": "Small synthetic UI/Excel/A4 evidence only; no real ledger duplicates",
                "verified_reports_preserved_byte_for_byte": True,
                "path_mapping": "original_temporary_path maps deleted temporary artifacts to retained path"}
    write(research / "retained-evidence.json", manifest)
    write(retained / "manifest.json", manifest)
    free_before = shutil.disk_usage(task).free
    assert not owned_processes(task), "A task process started during curation"

    def retry_readonly(function, path, exc_info):
        os.chmod(path, stat.S_IWRITE)
        function(path)

    for junction in snapshot["known_internal_edge_junctions"]:
        item = Path(junction["path"])
        assert item.is_junction()
        assert Path(os.readlink(item).removeprefix("\\\\?\\")).resolve() == Path(junction["target"])
        os.rmdir(item)  # Remove the link itself; its target is counted/deleted separately.
    shutil.rmtree(task, onerror=retry_readonly)
    assert not task.exists()
    desktop = Path(load(research / "delivery.json")["desktop_executable"])
    assert digest(desktop) == EXPECTED_SHA
    assert all(digest(source / relative) == value for relative, value in expected_files.items())
    free_after = shutil.disk_usage(desktop).free
    report = {"verified": True, "removed_root": str(task), "ownership_marker_verified": True,
              "active_task_processes_before_delete": [], "symlink_and_junction_boundaries_verified": True,
              "inventory_before_delete": snapshot, "logical_bytes_removed": snapshot["logical_bytes"],
              "retained_small_evidence_bytes": sum(item["bytes"] for item in files),
              "observed_c_free_bytes_before": free_before, "observed_c_free_bytes_after": free_after,
              "observed_c_free_bytes_delta": free_after - free_before,
              "free_space_delta_may_include_other_system_activity": True,
              "desktop_executable": str(desktop), "executable_sha256": EXPECTED_SHA,
              "product_source_fingerprint_unchanged": True,
              "preserved": ["real LocalAppData/aha and sidecars", "persistent D backups and old EXE",
                            "desktop/D production EXE", "base native interpreter", "source/Trellis records"],
              "completed_at": datetime.now(timezone(timedelta(hours=8))).isoformat()}
    write(research / "cleanup.json", report)
    for path in research.glob("*.json"):
        if path.name in {"delivery.json", "primary-recovery.json", "cleanup.json", "retained-evidence.json",
                         "native-materials-directory.json", "native-materials-onefile.json",
                         "native-ui-desktop.json", "desktop-verification.json", "product-file-sha256.json"}:
            shutil.copy2(path, retained / path.name)
    print(json.dumps({"verified": True, "logical_bytes_removed": snapshot["logical_bytes"],
                      "retained_small_evidence_bytes": report["retained_small_evidence_bytes"],
                      "retained_root": str(retained)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
