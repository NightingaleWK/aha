"""Deliver the verified OneFile to the Windows desktop and test that exact copy."""

from __future__ import annotations

import ctypes
import json
import os
import shutil
import sys
from pathlib import Path
from uuid import uuid4


def main():
    root=Path(os.environ["AHA_CCS26_ROOT"])
    source=Path(__file__).resolve().parents[4]
    research=Path(__file__).resolve().parent
    assert json.loads((root/"task-ownership.json").read_text())["task"]=="ccs-schema-26"
    sys.path.insert(0,str(source/"scripts"))
    import verify_windows_artifact as artifact
    validated=json.loads((research/"onefile-verification.json").read_text())
    assert validated["verified"] is True
    original=root/"build/release/portable/aha.exe"
    expected=validated["executable_sha256"]
    assert artifact.digest(original)==expected
    buffer=ctypes.create_unicode_buffer(32768)
    shell=ctypes.WinDLL("shell32",use_last_error=True)
    shell.SHGetFolderPathW.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_wchar_p]
    shell.SHGetFolderPathW.restype=ctypes.c_long
    assert shell.SHGetFolderPathW(None,0x10,None,0,buffer)==0
    desktop=Path(buffer.value).resolve(strict=True)
    destination=desktop/"aha.exe"
    backup=None
    if destination.exists():
        assert destination.is_file() and not destination.is_symlink()
        prior=artifact.digest(destination)
        if prior!=expected:
            allowed={"8991fa71cadd906678cb1b76d302921d1e874f022918f854a0540f2bb3d0e4d5":"0.5.0",
                "0c25c25da9df56f7b82e7fe4cbce9f20613e1e82172c2ac9b620c2b77b0e8f58":"0.4.1"}
            assert prior in allowed,"Unrecognized desktop executable must be preserved."
            backup=desktop/("aha-"+allowed[prior]+"-before-ccs26.exe")
            assert not backup.exists()
            shutil.copy2(destination,backup)
            assert artifact.digest(backup)==prior
    temporary=desktop/(".aha-ccs26-"+uuid4().hex+".exe")
    try:
        shutil.copy2(original,temporary)
        assert artifact.digest(temporary)==expected
        os.replace(temporary,destination)
    finally:
        temporary.unlink(missing_ok=True)
    report={"verified":False,"destination":str(destination),"executable_sha256":expected,
            "version":validated["version"],"single_file":True,"known_folder_checked":True,
            "backup":str(backup) if backup else None,"genuine_aha_accessed":False}
    report_path=research/"desktop-delivery.json"
    report_path.write_text(json.dumps(report,indent=2)+"\n")
    checked=artifact.verify(destination,source,root/"verify-desktop",with_tray=True)
    assert checked["verified"] and checked["executable_sha256"]==expected
    (research/"desktop-verification.json").write_text(json.dumps(checked,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    report.update(verified=True,from_desktop_executable_run=True,isolated_data_checked=True,
                  shutdown_cleaned=True,sha_matches_validated_onefile=artifact.digest(destination)==expected)
    report_path.write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(report),flush=True)


if __name__=="__main__":
    main()
