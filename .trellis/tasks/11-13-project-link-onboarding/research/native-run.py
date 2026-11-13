"""WSL entrypoint for the task-owned isolated native Windows QA runner."""
from pathlib import Path
import subprocess
import sys
root = Path('/mnt/c/Users/djsyw/AppData/Local/Temp/aha-project-link-20261113')
runner = Path(__file__).resolve().with_name('run-native.py')
windows = subprocess.check_output(['wslpath', '-w', str(runner)], text=True).strip()
raise SystemExit(subprocess.call([str(root/'qa315/Scripts/python.exe'), '-X', 'utf8', '-B', windows, *sys.argv[1:]]))
