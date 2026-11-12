"""Create only the task-owned native Python 3.15 release QA environment."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import struct
import subprocess
import sys
import venv
from datetime import datetime, timezone
from pathlib import Path


TASK = "project-record-continuity"
PURPOSE = "release-v050"
QA_PACKAGES = ["ruff==0.17.4", "mypy==2.4.1", "playwright==1.65.1",
               "pywin32==312", "pypdf==7.0.1", "PyMuPDF==1.26.7"]


def main():
    source = Path(__file__).resolve().parents[4]
    research = Path(__file__).resolve().parent
    if sys.platform != "win32" or tuple(sys.version_info[:3]) != (3, 15, 2):
        raise RuntimeError("Use the verified native CPython 3.15.2 base interpreter.")
    if struct.calcsize("P") * 8 != 64 or sqlite3.sqlite_version_info < (3, 51, 3):
        raise RuntimeError("The native x64 SQLite runtime gate is not satisfied.")
    task = Path("C:/Users/djsyw/AppData/Local/Temp/aha-release-v050-20261112")
    marker = task / "task-ownership.json"
    if task.exists():
        if not marker.is_file() or marker.is_symlink():
            raise RuntimeError("Refuse to reuse an unowned release directory.")
        owned = json.loads(marker.read_text(encoding="utf-8"))
        if owned.get("task") != TASK or owned.get("purpose") != PURPOSE:
            raise RuntimeError("Release directory ownership mismatch.")
    else:
        task.mkdir(parents=True, exist_ok=False)
        marker.write_text(json.dumps({"task": TASK, "purpose": PURPOSE,
            "source": str(source), "created_at": datetime.now(timezone.utc).isoformat(),
            "cleanup_after_release": True}, indent=2) + "\n", encoding="utf-8")
    profile = task / "synthetic-profile"
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
               PYTHONUTF8="1", PYTHONIOENCODING="utf-8", AHA_RELEASE_QA_ROOT=str(task))
    os.environ.update(env)
    qa = task / "qa315"
    python = qa / "Scripts/python.exe"
    if not python.exists():
        venv.EnvBuilder(with_pip=True).create(qa)
    command = [str(python), "-X", "utf8", "-m", "pip", "install", "--disable-pip-version-check",
               "-r", str(source / "scripts/requirements-build.txt"), *QA_PACKAGES]
    log = task / "setup-native.log"
    with log.open("w", encoding="utf-8") as stream:
        installed = subprocess.run(command, cwd=task, env=env, stdout=stream, stderr=subprocess.STDOUT)
    result = {"verified": installed.returncode == 0, "task": TASK, "purpose": PURPOSE,
              "task_root": str(task), "qa_python": str(python), "returncode": installed.returncode,
              "log": str(log), "cleanup_after_release": True,
              "real_profile_used": False, "built_artifact": False}
    if installed.returncode == 0:
        # Build project metadata from a task-owned copy, so setuptools never
        # creates egg-info/build output inside the shared source checkout.
        package = task / "metadata-package-source"
        package.mkdir(exist_ok=True)
        for name in ("pyproject.toml", "README.md"):
            shutil.copyfile(source / name, package / name)
        shutil.copytree(source / "src/aha", package / "src/aha", dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        with log.open("a", encoding="utf-8") as stream:
            metadata = subprocess.run([str(python), "-X", "utf8", "-m", "pip", "install",
                "--disable-pip-version-check", "--no-build-isolation", "--no-deps", str(package)],
                cwd=task, env=env, stdout=stream, stderr=subprocess.STDOUT)
        result["metadata_install_returncode"] = metadata.returncode
        result["verified"] = metadata.returncode == 0
    (research / "release-native-environment.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
