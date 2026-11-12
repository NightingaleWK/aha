"""Prepare the task-owned native Windows QA/build environment."""

import json
import os
import subprocess
import sys
import venv
from datetime import datetime, timedelta, timezone
from pathlib import Path


def main():
    source = Path(__file__).resolve().parents[4]
    task = Path(os.environ["LOCALAPPDATA"]) / "Temp/aha-project-record-continuity-20261112"
    marker = task / "task-ownership.json"
    if task.exists():
        assert marker.is_file() and json.loads(marker.read_text())["task"] == "project-record-continuity"
    task.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"task": "project-record-continuity", "source": str(source),
                                 "created_at": datetime.now(timezone(timedelta(hours=8))).isoformat()}) + "\n",
                      encoding="utf-8")
    qa = task / "qa312"
    if not (qa / "Scripts/python.exe").is_file():
        venv.EnvBuilder(with_pip=True).create(qa)
    python = qa / "Scripts/python.exe"
    args = [str(python), "-X", "utf8", "-m", "pip", "install", "--disable-pip-version-check",
            "-r", str(source / "scripts/requirements-build.txt"), "ruff", "mypy",
            "playwright==1.65.1", "pywin32==312", "pypdf==7.0.1", "-e", str(source)]
    with (task / "setup.log").open("w", encoding="utf-8") as log:
        result = subprocess.run(args, cwd=task, stdout=log, stderr=subprocess.STDOUT)
    print(json.dumps({"returncode": result.returncode, "qa_python": str(python),
                      "task_root": str(task), "log": str(task / "setup.log")}, ensure_ascii=False))
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
