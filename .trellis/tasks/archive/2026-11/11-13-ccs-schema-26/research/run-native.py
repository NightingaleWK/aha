"""Run one task check/build with a synthetic Windows profile and retain its log."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path("C:/Users/djsyw/AppData/Local/Temp/aha-ccs26-20261113")


def main():
    assert sys.platform == "win32"
    assert json.loads((ROOT / "task-ownership.json").read_text())["task"] == "ccs-schema-26"
    assert len(sys.argv) >= 3 and re.fullmatch(r"[a-z0-9-]+", sys.argv[1])
    name, arguments = sys.argv[1], sys.argv[2:]
    if arguments[0] == "--":
        arguments = arguments[1:]
    source = Path(__file__).resolve().parents[4]
    research = Path(__file__).resolve().parent
    profile = ROOT / ("profile-" + name)
    for relative in ("AppData/Local", "AppData/Roaming", "Temp", ".cc-switch", ".codex"):
        (profile / relative).mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.pop("PYTHONHOME", None)
    env.update(USERPROFILE=str(profile), HOME=str(profile), HOMEDRIVE=profile.drive,
               HOMEPATH=str(profile)[len(profile.drive):],
               LOCALAPPDATA=str(profile / "AppData/Local"), APPDATA=str(profile / "AppData/Roaming"),
               TEMP=str(profile / "Temp"), TMP=str(profile / "Temp"),
               XDG_CONFIG_HOME=str(profile / ".config"), XDG_STATE_HOME=str(profile / ".local/state"),
               XDG_DATA_HOME=str(profile / ".local/share"),
               PYTHONPATH=os.pathsep.join((str(source / "src"), str(source))),
               PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1",
               PYTHONPYCACHEPREFIX=str(ROOT / "pycache"), PIP_CACHE_DIR=str(ROOT / "pip-cache"),
               RUFF_CACHE_DIR=str(ROOT / "ruff-cache"), MYPY_CACHE_DIR=str(ROOT / ("mypy-" + name)),
               AHA_QA_ROOT=str(ROOT), AHA_CCS26_ROOT=str(ROOT))
    command = [str(ROOT / "qa315/Scripts/python.exe"), "-X", "utf8", "-B", *arguments]
    started = time.monotonic()
    with (research / (name + ".log")).open("w", encoding="utf-8", newline="\n") as stream:
        result = subprocess.run(command, cwd=source, env=env, stdout=stream, stderr=subprocess.STDOUT)
    report = {"verified": result.returncode == 0, "returncode": result.returncode,
              "command": command, "seconds": round(time.monotonic() - started, 3),
              "synthetic_profile": True, "log": name + ".log"}
    (research / (name + "-result.json")).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report), flush=True)
    if result.returncode:
        print("\n".join((research / (name + ".log")).read_text(encoding="utf-8").splitlines()[-35:]))
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
