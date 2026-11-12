"""Run task QA through the native interpreter with captured child output."""

import os
import subprocess
import sys
from pathlib import Path

root = Path(os.environ["LOCALAPPDATA"]) / "Temp" / "aha-device-continuity-20261112"
qa = root / "qa312" / "Scripts" / "python.exe"
source = Path(__file__).resolve().parents[4]
env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
arguments = sys.argv[1:]
if arguments and arguments[0] == "--real-profile":
    arguments = arguments[1:]
else:
    profile = root / "qa-profile"
    for relative in ("AppData/Local", "AppData/Roaming", "Temp", ".cc-switch", ".codex"):
        (profile / relative).mkdir(parents=True, exist_ok=True)
    env.update(USERPROFILE=str(profile), HOME=str(profile), HOMEDRIVE=profile.drive,
               HOMEPATH=str(profile)[len(profile.drive):],
               LOCALAPPDATA=str(profile / "AppData/Local"),
               APPDATA=str(profile / "AppData/Roaming"),
               TEMP=str(profile / "Temp"), TMP=str(profile / "Temp"),
               XDG_CONFIG_HOME=str(profile / ".config"),
               XDG_STATE_HOME=str(profile / ".local/state"),
               XDG_DATA_HOME=str(profile / ".local/share"))
command = [str(qa), "-X", "utf8", *arguments]
with subprocess.Popen(command, cwd=source, env=env, stdout=subprocess.PIPE,
                      stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace") as child:
    for line in child.stdout:
        print(line, end="", flush=True)
    code = child.wait()
raise SystemExit(code)
