"""Run release QA only with a synthetic profile and platform-local caches."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def main():
    if sys.platform != "win32":
        raise RuntimeError("Native Windows is required.")
    task = Path("C:/Users/djsyw/AppData/Local/Temp/aha-release-v050-20261112")
    owned = json.loads((task / "task-ownership.json").read_text(encoding="utf-8"))
    if owned.get("task") != "project-record-continuity" or owned.get("purpose") != "release-v050":
        raise RuntimeError("Release directory ownership mismatch.")
    source = Path(__file__).resolve().parents[4]
    profile = task / ("qa-profile-" + str(os.getpid()))
    for relative in ("AppData/Local", "AppData/Roaming", "Temp", ".cc-switch", ".codex"):
        (profile / relative).mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    env.update(USERPROFILE=str(profile), HOME=str(profile), HOMEDRIVE=profile.drive,
               HOMEPATH=str(profile)[len(profile.drive):],
               LOCALAPPDATA=str(profile / "AppData/Local"), APPDATA=str(profile / "AppData/Roaming"),
               TEMP=str(profile / "Temp"), TMP=str(profile / "Temp"),
               XDG_CONFIG_HOME=str(profile / ".config"), XDG_STATE_HOME=str(profile / ".local/state"),
               XDG_DATA_HOME=str(profile / ".local/share"), PIP_CACHE_DIR=str(task / "pip-cache"),
               PLAYWRIGHT_BROWSERS_PATH=str(task / "playwright-browsers"),
               RUFF_CACHE_DIR=str(task / "ruff-cache"), MYPY_CACHE_DIR=str(task / "mypy-cache"),
               PYTHONPYCACHEPREFIX=str(task / "pycache"), PYTHONDONTWRITEBYTECODE="1",
               PYTHONUTF8="1", PYTHONIOENCODING="utf-8", AHA_RELEASE_QA_ROOT=str(task),
               AHA_QA_ROOT=str(task), PYTHONPATH=os.pathsep.join((str(source / "src"), str(source))))
    result = subprocess.run([str(task / "qa315/Scripts/python.exe"), "-X", "utf8", "-B", *sys.argv[1:]],
                            cwd=source, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace")
    sys.stdout.write(result.stdout)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
