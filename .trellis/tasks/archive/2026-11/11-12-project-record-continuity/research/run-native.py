"""Run isolated QA via native Python; real-profile mode requires explicit selection."""

import os
import subprocess
import sys
from pathlib import Path


def main():
    task = Path(os.environ["LOCALAPPDATA"]) / "Temp/aha-project-record-continuity-20261112"
    python = task / "qa312/Scripts/python.exe"
    source = Path(__file__).resolve().parents[4]
    arguments = sys.argv[1:]
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8", AHA_QA_ROOT=str(task))
    if arguments and arguments[0] == "--real-profile":
        arguments = arguments[1:]
    else:
        profile = task / ("qa-profile-" + str(os.getpid()))
        for relative in ("AppData/Local", "AppData/Roaming", "Temp", ".cc-switch", ".codex"):
            (profile / relative).mkdir(parents=True, exist_ok=True)
        env.update(USERPROFILE=str(profile), HOME=str(profile), HOMEDRIVE=profile.drive,
                   HOMEPATH=str(profile)[len(profile.drive):], LOCALAPPDATA=str(profile / "AppData/Local"),
                   APPDATA=str(profile / "AppData/Roaming"), TEMP=str(profile / "Temp"), TMP=str(profile / "Temp"),
                   XDG_CONFIG_HOME=str(profile / ".config"), XDG_STATE_HOME=str(profile / ".local/state"),
                   XDG_DATA_HOME=str(profile / ".local/share"))
    result = subprocess.run([str(python), "-X", "utf8", "-B", *arguments], cwd=source, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace")
    sys.stdout.write(result.stdout)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
