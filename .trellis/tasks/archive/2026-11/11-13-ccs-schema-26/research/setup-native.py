"""Prepare only the task-owned Windows runtime and QA venv; preserve the base."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import sqlite3
import struct
import subprocess
import sys
import urllib.request
import venv
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path


TASK = "ccs-schema-26"
ROOT = Path("C:/Users/djsyw/AppData/Local/Temp/aha-ccs26-20261113")
PUBLIC_EXE_SHA = "8991fa71cadd906678cb1b76d302921d1e874f022918f854a0540f2bb3d0e4d5"
PUBLIC_INFO_SHA = "a34df29fdd2796da70994fdc70514302bd874bbcc693be8a42fd9e936a8861d6"
WHEEL_SHA = "a1c09646b16f6c5c3dfbd6d2074bbe5bdb6cac88d1566762b6ad2d7b4003e178"
RUNTIME_SHA = "2d64ab084e0aa6c3d8ffab874ef7a08fd35b4fbf452dc1353e89d06dc7ea8642"


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def environment():
    profile = ROOT / "qa-profile"
    for relative in ("AppData/Local", "AppData/Roaming", "Temp", ".cc-switch", ".codex"):
        (profile / relative).mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    env.update(USERPROFILE=str(profile), HOME=str(profile), HOMEDRIVE=profile.drive,
               HOMEPATH=str(profile)[len(profile.drive):],
               LOCALAPPDATA=str(profile / "AppData/Local"), APPDATA=str(profile / "AppData/Roaming"),
               TEMP=str(profile / "Temp"), TMP=str(profile / "Temp"),
               PYTHONPYCACHEPREFIX=str(ROOT / "pycache"), PYTHONDONTWRITEBYTECODE="1",
               PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PIP_CACHE_DIR=str(ROOT / "pip-cache"),
               RUFF_CACHE_DIR=str(ROOT / "ruff-cache"), MYPY_CACHE_DIR=str(ROOT / "mypy-cache"))
    return env


def download(name, expected_sha, expected_size):
    path = ROOT / "provenance" / name
    if not path.exists():
        request = urllib.request.Request(
            "https://github.com/NightingaleWK/aha/releases/download/v0.5.0/" + name,
            headers={"User-Agent": "aha-ccs26-qa"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read(expected_size + 1)
        assert len(raw) == expected_size and hashlib.sha256(raw).hexdigest() == expected_sha
        path.write_bytes(raw)
    assert path.is_file() and not path.is_symlink() and digest(path) == expected_sha
    return path


def main():
    assert sys.platform == "win32" and tuple(sys.version_info[:3]) == (3, 15, 2)
    assert struct.calcsize("P") == 8
    assert json.loads((ROOT / "task-ownership.json").read_text())["task"] == TASK
    source = Path(__file__).resolve().parents[4]
    research = Path(__file__).resolve().parent
    env = environment()
    os.environ.update(env)
    qa = ROOT / "qa315"
    python = qa / "Scripts/python.exe"
    if not python.exists():
        venv.EnvBuilder(with_pip=True).create(qa)
    requirements = ROOT / "initial-requirements.txt"
    requirements.write_text("\n".join(
        line for line in (source / "scripts/requirements-build.txt").read_text().splitlines()
        if not line.startswith("zstandard==")
    ) + "\n" + (source / "requirements-dev.txt").read_text(), encoding="utf-8")
    log = research / "native-setup.log"

    def run(args, timeout=300):
        with log.open("a", encoding="utf-8") as stream:
            subprocess.run([str(x) for x in args], cwd=ROOT, env=env,
                           stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=timeout)

    run([python, "-m", "pip", "install", "--disable-pip-version-check", "-r", requirements])
    exe = download("aha-0.5.0-windows-x64.exe", PUBLIC_EXE_SHA, 12833570)
    info = download("build-info.json", PUBLIC_INFO_SHA, 4179)
    public = json.loads(info.read_text())
    assert public["runtime_sha256"] == RUNTIME_SHA
    sys.path.insert(0, str(qa / "Lib/site-packages"))
    from PyInstaller.archive.readers import CArchiveReader

    archive = CArchiveReader(str(exe))
    base = Path(sys.base_prefix)
    original = {name: digest(base / "DLLs" / name) for name in ("sqlite3.dll", "_sqlite3.pyd")}
    private = ROOT / "runtime315-sqlite3534"
    if not private.exists():
        private.mkdir()
        (private / "runtime-ownership.json").write_text(json.dumps({"task": TASK,
            "source_base": str(base), "cleanup_after_delivery": True}) + "\n")
        for item in base.iterdir():
            if item.is_file() and item.suffix.lower() in {".dll", ".exe", ".txt", ".json"}:
                assert not item.is_symlink()
                shutil.copy2(item, private / item.name)
        for name in ("DLLs", "Lib", "include", "libs", "tcl"):
            assert (base / name).is_dir() and not (base / name).is_symlink()
            shutil.copytree(base / name, private / name,
                            ignore=shutil.ignore_patterns("site-packages", "__pycache__", "*.pyc"))
    assert json.loads((private / "runtime-ownership.json").read_text())["task"] == TASK
    extracted = {}
    for wanted in original:
        entries = [name for name in archive.toc
                   if name.replace("\\", "/").split("/")[-1].lower() == wanted]
        assert len(entries) == 1 and archive.toc[entries[0]][-1] == "b"
        raw = archive.extract(entries[0])
        assert raw.startswith(b"MZ") and len(raw) <= 8 * 1024 * 1024
        (private / "DLLs" / wanted).write_bytes(raw)
        extracted[wanted] = {"member": entries[0], "sha256": hashlib.sha256(raw).hexdigest()}
    run([private / "python.exe", "-m", "venv", "--upgrade", "--without-pip", qa])
    wheel = ROOT / "provenance/wheel/zstandard-0.25.0-cp315-cp315-win_amd64.whl"
    provenance = json.loads(wheel.with_name("provenance.json").read_text())
    assert digest(wheel) == WHEEL_SHA == provenance["wheel"]["sha256"]
    assert provenance["workflow_run_id"] == "43178376925"
    assert provenance["verified_native_import_and_roundtrip"] is True
    assert provenance["requirements_build_sha256"] == digest(source / "scripts/requirements-build.txt")
    run([python, "-m", "pip", "install", "--no-index", "--no-deps", wheel])
    run([python, "-m", "pip", "install", "--no-index", "-r", source / "scripts/requirements-build.txt"])
    metadata = ROOT / "metadata-source"
    metadata.mkdir(exist_ok=True)
    for name in ("pyproject.toml", "README.md"):
        shutil.copy2(source / name, metadata / name)
    shutil.copytree(source / "src/aha", metadata / "src/aha", dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    run([python, "-m", "pip", "install", "--no-build-isolation", "--no-deps", metadata])
    probe = r'''
import hashlib, importlib.metadata, json, platform, sqlite3, struct, sys, zstandard
from pathlib import Path
assert sqlite3.sqlite_version_info == (3, 53, 4)
assert sys.prefix != sys.base_prefix and zstandard.backend == "cext"
sample = b"aha synthetic compression roundtrip" * 1000
assert zstandard.ZstdDecompressor().decompress(zstandard.ZstdCompressor().compress(sample)) == sample
source = Path(sys.argv[1])
packages = {line.split("==")[0]:importlib.metadata.version(line.split("==")[0])
    for line in (source/"scripts/requirements-build.txt").read_text().splitlines()
    if line and not line.startswith("#")}
runtime = {"python":list(sys.version_info[:3]),"sqlite":list(sqlite3.sqlite_version_info),
    "sqlite_version":sqlite3.sqlite_version,"windows":True,"bits":struct.calcsize("P")*8,
    "machine":platform.machine(),"packages":packages}
sys.path.insert(0,str(source/"scripts"))
import release
digest = release.runtime_digest(source,"WORKTREE",runtime)
print(json.dumps({"verified":True,"runtime":runtime,"runtime_sha256":digest,
    "native_zstandard_roundtrip":True,"qa_python":sys.executable}))
'''
    checked = subprocess.run([str(python), "-B", "-c", probe, str(source)], cwd=ROOT,
                             env=env, check=True, capture_output=True, text=True, encoding="utf-8")
    report = json.loads(checked.stdout)
    assert report["runtime_sha256"] == RUNTIME_SHA
    assert {name: digest(base / "DLLs" / name) for name in original} == original
    report.update(task=TASK, completed_at=datetime.now(timezone.utc).isoformat(),
                  runtime_matches_public_v050=True, base_runtime_unchanged=True,
                  public_executable_executed=False, public_executable_sha256=PUBLIC_EXE_SHA,
                  extracted_sqlite=extracted, wheel_sha256=WHEEL_SHA)
    (research / "native-environment.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
