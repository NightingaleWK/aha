"""Delete only inventoried, idle task-owned build/QA files; retain delivery/evidence."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT=Path("C:/Users/djsyw/AppData/Local/Temp/aha-ccs26-20261113")
RESEARCH=Path(__file__).resolve().parent


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream,"sha256").hexdigest()


def main():
    assert sys.platform=="win32" and not Path(sys.executable).is_relative_to(ROOT)
    assert ROOT.resolve()==ROOT and not ROOT.is_symlink()
    marker=json.loads((ROOT/"task-ownership.json").read_text())
    assert marker["task"]=="ccs-schema-26" and marker["cleanup_after_delivery"] is True
    delivery=json.loads((RESEARCH/"desktop-delivery.json").read_text())
    assert delivery["verified"] and json.loads((RESEARCH/"ui-desktop.json").read_text())["verified"]
    desktop=Path(delivery["destination"])
    assert not desktop.is_relative_to(ROOT) and sha(desktop)==delivery["executable_sha256"]
    command=["powershell.exe","-NoProfile","-Command",
        "Get-CimInstance Win32_Process | Select-Object ProcessId,ExecutablePath | ConvertTo-Json -Compress"]
    observed=subprocess.run(command,check=True,capture_output=True,text=True,encoding="utf-8")
    processes=json.loads(observed.stdout)
    active=[p["ProcessId"] for p in processes if p.get("ExecutablePath")
            and Path(p["ExecutablePath"]).is_relative_to(ROOT)]
    assert not active,"Task-owned processes are still running."
    known={"build","initial-requirements.txt","metadata-source","pip-cache","provenance","pycache",
           "qa-profile","qa315","ruff-cache","runtime315-sqlite3534","task-ownership.json"}
    for path in RESEARCH.glob("*-result.json"):
        name=path.name.removesuffix("-result.json")
        known.update({"profile-"+name,"mypy-"+name})
    # Edge creates this compatibility junction inside the synthetic profile.
    # Inspect every target first, then unlink only the junction itself.
    stack=[ROOT]
    junctions=[]
    while stack:
        for entry in os.scandir(stack.pop()):
            state=entry.stat(follow_symlinks=False)
            path=Path(entry.path)
            if getattr(state,"st_file_attributes",0)&stat.FILE_ATTRIBUTE_REPARSE_POINT:
                parts=path.relative_to(ROOT).parts
                assert parts[0] in known and parts[0].startswith("profile-")
                assert parts[1:]==("AppData","Local","Microsoft","Windows","INetCache","Content.IE5")
                assert getattr(state,"st_reparse_tag",None)==stat.IO_REPARSE_TAG_MOUNT_POINT
                target=Path(os.readlink(path).removeprefix("\\\\?\\"))
                assert target.resolve()==path.with_name("IE").resolve()
                assert target.resolve().is_relative_to(ROOT)
                junctions.append((path,target))
            elif entry.is_dir(follow_symlinks=False):
                stack.append(path)
    for path,target in junctions:
        os.rmdir(path)
    inventory=[]
    total=0
    for child in sorted(ROOT.iterdir()):
        if child.name not in known:
            assert child.name.startswith(("verify-","ui-directory","ui-onefile","ui-desktop","real-source-projection"))
            owned=json.loads((child/".aha-artifact-verification.json").read_text())
            assert owned["owner"]=="aha-artifact-verification"
        size=0
        files=0
        paths=[child] if child.is_file() else [child,*child.rglob("*")]
        for path in paths:
            state=path.lstat()
            assert not path.is_symlink() and not (getattr(state,"st_file_attributes",0)&stat.FILE_ATTRIBUTE_REPARSE_POINT)
            assert path.resolve().is_relative_to(ROOT)
            if path.is_file():
                size+=state.st_size
                files+=1
        inventory.append({"path":child.name,"bytes":size,"files":files,"ownership_verified":True})
        total+=size
    assert not list(ROOT.rglob("runtime.json")),"Owned live descriptors remain."
    base=Path(sys.base_prefix)
    original={name:sha(base/"DLLs"/name) for name in ("sqlite3.dll","_sqlite3.pyd")}
    for source,name in [(ROOT/"provenance/build-info.json","public-v050-build-info.json"),
                        (ROOT/"provenance/wheel/provenance.json","trusted-wheel-provenance.json"),
                        (ROOT/"build/runtime-versions.json","build-runtime-versions.json")]:
        shutil.copy2(source,RESEARCH/name)
    before=shutil.disk_usage(ROOT).free
    (RESEARCH/"cleanup-inventory.json").write_text(json.dumps({"task":marker["task"],
        "owned_processes":active,"root_symlink_checked":True,"tracked_source_outside_root":True,
        "detached_known_edge_junctions":[{"path":str(p.relative_to(ROOT)),"target":str(t.relative_to(ROOT))} for p,t in junctions],
        "entries":inventory,"total_bytes":total},indent=2)+"\n")
    shutil.rmtree(ROOT)
    assert not ROOT.exists() and sha(desktop)==delivery["executable_sha256"]
    assert original=={name:sha(base/"DLLs"/name) for name in original}
    assert sqlite3.sqlite_version=="3.53.1"
    report={"verified":True,"task":"ccs-schema-26","deleted_root":str(ROOT),
        "removed_bytes":total,"removed_mib":round(total/1024/1024,2),
        "free_space_delta_bytes":shutil.disk_usage(desktop).free-before,
        "task_root_absent":True,"desktop_sha256":sha(desktop),"desktop_preserved":True,
        "base_runtime_unchanged":True,"genuine_ccs_and_aha_outside_root":True,
        "evidence_retained_in_task_research":True,
        "known_edge_junctions_unlinked_without_following":len(junctions),
        "completed_at":datetime.now(timezone(timedelta(hours=8))).isoformat()}
    (RESEARCH/"cleanup.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(report),flush=True)


if __name__=="__main__":
    main()
