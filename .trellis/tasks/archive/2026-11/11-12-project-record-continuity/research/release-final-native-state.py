"""Check/reopen only the published desktop program using the retained base Python.

The default service's private descriptor/credentials remain in memory. This
script never constructs a Store or changes consumption/project assignments.
"""

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--after-cleanup", action="store_true")
    args = parser.parse_args()
    research = Path(__file__).resolve().parent
    source = research.parents[3]
    spec = importlib.util.spec_from_file_location("final_published_helpers", research / "deliver-and-recover.py")
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    sys.path[:0] = [str(source / "scripts"), str(source / "src")]
    from verify_windows_artifact import Client, pe_version

    published = helper.read_json(research / "release-publication.json")
    assert published["verified"] and published["published"]
    delivery = helper.read_json(research / "release-desktop-delivery.json")
    task = helper.known_folder("F1B32785-6FBA-4FCF-9D55-7B8E7F157091") / "Temp/aha-release-v050-20261112"
    assert not Path(sys.executable).resolve().is_relative_to(task)
    if args.after_cleanup:
        assert not task.exists()
    assert not Path(os.environ["TEMP"]).resolve().is_relative_to(task)
    local = helper.known_folder("F1B32785-6FBA-4FCF-9D55-7B8E7F157091")
    assert Path(os.environ["LOCALAPPDATA"]).resolve() == local
    data = local / "aha"
    assert data.resolve() == Path(delivery["data_directory"]).resolve()
    desktop = helper.known_folder("B4BFCC3A-DB2C-424C-B029-7FE99A87C641") / "aha.exe"
    for target in (desktop, Path("D:/Program Files/aha.exe")):
        assert helper.sha(target) == published["executable_sha256"]
    assert pe_version(desktop)["product_version"] == published["version"]
    helper.NEW_SHA = helper.OLD_SHA = published["executable_sha256"]
    client, descriptor = helper.ready_default(desktop, data, Client)
    status = client.json("GET", "/api/status")
    assert status["version"] == published["version"]
    assert Path(status["data_directory"]).resolve() == data.resolve()
    launch = subprocess.Popen([str(desktop)], cwd=desktop.parent,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    assert launch.wait(timeout=45) == 0
    repeated = helper.read_json(data / "runtime.json")
    assert all(repeated[key] == descriptor[key] for key in ("pid", "profile_id", "run_id"))
    assert client.json("GET", "/api/instance")["state"] == "ready"
    result = {"verified": True, "published": True, "source_sha": published["source_sha"],
              "version": published["version"], "executable_sha256": published["executable_sha256"],
              "default_service_ready": True, "desktop_reopen_reuses_same_service": True,
              "browser_open_requested": True, "browser_window_visually_checked_by_agent": False,
              "normal_ui_startup_may_sync_new_consumption": True,
              "task_root_absent": not task.exists(), "after_cleanup": args.after_cleanup,
              "base_interpreter_outside_task_root": True,
              "original_delivery_report_preserved": True, "verified_at": helper.now()}
    name = "release-after-cleanup-runtime.json" if args.after_cleanup else "release-post-publication-runtime.json"
    helper.write_json(research / name, result)
    backup_root = Path(delivery["backup_before"]["archive_path"]).parent
    if (backup_root / "acceptance-records-v0.5.0").exists():
        helper.write_json(backup_root / "acceptance-records-v0.5.0" / name, result)
    print(json.dumps({"verified": True, "after_cleanup": args.after_cleanup, "default_service_ready": True}))


if __name__ == "__main__":
    main()
