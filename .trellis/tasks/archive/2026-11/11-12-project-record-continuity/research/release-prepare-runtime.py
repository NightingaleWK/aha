"""Prepare a private CPython315 runtime using hash-verified public SQLite files.

The public EXE is parsed only as a PyInstaller archive; it is never executed.
No base interpreter, real user data, desktop file, or product source is modified.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import shutil
import sqlite3
import struct
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


EXPECTED_EXE_SHA = "0c25c25da9df56f7b82e7fe4cbce9f20613e1e82172c2ac9b620c2b77b0e8f58"
PUBLIC_EXE = "https://github.com/NightingaleWK/aha/releases/download/v0.4.1/aha-0.4.1-windows-x64.exe"
EXPECTED_RUNTIME_SHA = "2d64ab084e0aa6c3d8ffab874ef7a08fd35b4fbf452dc1353e89d06dc7ea8642"
PROBE = r'''
import ctypes, hashlib, importlib.metadata, json, platform, sqlite3, struct, sys, _sqlite3
from pathlib import Path
kernel = ctypes.WinDLL("kernel32", use_last_error=True)
kernel.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
kernel.GetModuleHandleW.restype = ctypes.c_void_p
kernel.GetModuleFileNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint32]
buffer = ctypes.create_unicode_buffer(32768)
module = kernel.GetModuleHandleW("sqlite3.dll")
if not module or not kernel.GetModuleFileNameW(module, buffer, len(buffer)):
    raise RuntimeError("Cannot identify the loaded SQLite DLL.")
paths = {"sqlite3.dll": Path(buffer.value).resolve(), "_sqlite3.pyd": Path(_sqlite3.__file__).resolve()}
print(json.dumps({"python":list(sys.version_info[:3]),"sqlite":list(sqlite3.sqlite_version_info),
    "sqlite_version":sqlite3.sqlite_version,"windows":sys.platform=="win32",
    "bits":struct.calcsize("P")*8,"machine":platform.machine(),"isolated":sys.prefix!=sys.base_prefix,
    "prefix":sys.prefix,"base_prefix":sys.base_prefix,"executable":sys.executable,
    "loaded_files":{name:{"path":str(path),"sha256":hashlib.sha256(path.read_bytes()).hexdigest()}
                    for name,path in paths.items()},
    "packages":{item.metadata["Name"].lower().replace("_","-"):item.version
                for item in importlib.metadata.distributions()}},sort_keys=True))
'''


def require(condition, code):
    if not condition:
        raise RuntimeError(code)


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def atomic_json(path, value):
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    research = Path(__file__).resolve().parent
    source = Path(__file__).resolve().parents[4]
    report = {"verified": False, "started_at": datetime.now(timezone.utc).isoformat(),
              "task": "project-record-continuity", "purpose": "release-v050",
              "public_executable_executed": False, "global_runtime_modified": False,
              "real_profile_used": False, "full_installed_runtime_verified": False}
    stage = "validate_task_and_base"
    try:
        require(sys.platform == "win32" and tuple(sys.version_info[:3]) == (3, 15, 2)
                and struct.calcsize("P") * 8 == 64, "expected_native_cpython315_required")
        base = Path(sys.base_prefix).resolve()
        require(base == Path("C:/Users/djsyw/AppData/Roaming/uv/python/cpython-3.15.2-windows-x86_64-none"),
                "unexpected_base_interpreter")
        task = Path("C:/Users/djsyw/AppData/Local/Temp/aha-release-v050-20261112").resolve()
        marker = json.loads((task / "task-ownership.json").read_text(encoding="utf-8"))
        require(marker.get("task") == report["task"] and marker.get("purpose") == report["purpose"],
                "task_ownership_mismatch")
        qa = task / "qa315"
        require((qa / "pyvenv.cfg").is_file(), "existing_task_qa_venv_missing")
        profile = task / "runtime-preparation-profile"
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
                   XDG_DATA_HOME=str(profile / ".local/share"),
                   PYTHONPYCACHEPREFIX=str(task / "pycache"), PYTHONDONTWRITEBYTECODE="1",
                   PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PIP_CACHE_DIR=str(task / "pip-cache"))
        os.environ.update(env)
        from_sqlite = {"sqlite3.dll": base / "DLLs/sqlite3.dll",
                       "_sqlite3.pyd": base / "DLLs/_sqlite3.pyd"}
        original_hashes = {name: sha(path) for name, path in from_sqlite.items()}
        report["initial_base_sqlite"] = sqlite3.sqlite_version
        report["base_sqlite_files_sha256"] = original_hashes
        provenance = task / "runtime-provenance"
        provenance.mkdir(exist_ok=True)
        expected = json.loads((research / "release-previous-public-runtime.json").read_text(encoding="utf-8"))
        require(expected["executable"]["sha256"] == EXPECTED_EXE_SHA
                and expected["runtime_sha256"] == EXPECTED_RUNTIME_SHA,
                "previous_public_runtime_evidence_mismatch")
        report["public_source"] = {"version": expected["version"], "source_sha": expected["source_sha"],
                                   "url": PUBLIC_EXE, "executable_sha256": EXPECTED_EXE_SHA}
        stage = "download_and_verify_public_executable"
        archive = provenance / "aha-0.4.1-windows-x64.exe"
        if not archive.exists():
            temporary = archive.with_suffix(".download-" + uuid4().hex)
            try:
                request = urllib.request.Request(PUBLIC_EXE, headers={"User-Agent": "aha-release-qa"})
                with urllib.request.urlopen(request, timeout=60) as response, temporary.open("xb") as output:
                    size = 0
                    while chunk := response.read(1024 * 1024):
                        size += len(chunk)
                        require(size <= 40 * 1024 * 1024, "public_executable_exceeds_expected_bound")
                        output.write(chunk)
                require(sha(temporary) == EXPECTED_EXE_SHA, "public_executable_hash_mismatch")
                os.replace(temporary, archive)
            finally:
                temporary.unlink(missing_ok=True)
        require(archive.is_file() and not archive.is_symlink() and sha(archive) == EXPECTED_EXE_SHA,
                "downloaded_public_executable_changed")
        require(archive.stat().st_size == expected["executable"]["size"], "public_executable_size_mismatch")
        stage = "parse_only_verified_carchive_sqlite_files"
        sys.path.insert(0, str(qa / "Lib/site-packages"))
        require(importlib.metadata.version("pyinstaller") == "6.22.3", "pyinstaller_version_drift")
        from PyInstaller.archive.readers import CArchiveReader

        reader = CArchiveReader(str(archive))
        extracted = {}
        for wanted in ("sqlite3.dll", "_sqlite3.pyd"):
            entries = [name for name in reader.toc if name.replace("\\", "/").split("/")[-1].lower() == wanted]
            require(len(entries) == 1 and reader.toc[entries[0]][-1] == "b", "ambiguous_public_sqlite_entry")
            raw = reader.extract(entries[0])
            require(raw.startswith(b"MZ") and len(raw) <= 8 * 1024 * 1024, "invalid_public_sqlite_binary")
            destination = provenance / wanted
            if destination.exists():
                require(destination.read_bytes() == raw, "previous_extracted_sqlite_changed")
            else:
                destination.write_bytes(raw)
            extracted[wanted] = {"archive_member": entries[0], "size": len(raw), "sha256": sha(destination)}
        report["extracted_files"] = extracted
        stage = "copy_private_standard_runtime"
        runtime = task / "runtime315-sqlite3534"
        runtime_marker = runtime / "runtime-ownership.json"
        if runtime.exists():
            owned = json.loads(runtime_marker.read_text(encoding="utf-8"))
            require(owned.get("task") == report["task"] and owned.get("purpose") == report["purpose"],
                    "private_runtime_ownership_mismatch")
        else:
            runtime.mkdir(exist_ok=False)
            atomic_json(runtime_marker, {"task": report["task"], "purpose": report["purpose"],
                        "base": str(base), "cleanup_after_release": True})
        require(runtime.resolve().is_relative_to(task) and not runtime.is_symlink(), "private_runtime_outside_task")
        copied = []
        for item in base.iterdir():
            if item.is_file() and (item.suffix.lower() in {".dll", ".exe", ".txt", ".json"} or item.name == "BUILD"):
                require(not item.is_symlink(), "base_runtime_file_is_link")
                shutil.copy2(item, runtime / item.name)
                copied.append(item.name)
        for directory in ("DLLs", "Lib", "include", "libs", "tcl"):
            require((base / directory).is_dir() and not (base / directory).is_symlink(), "standard_runtime_directory_invalid")
            shutil.copytree(base / directory, runtime / directory, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("site-packages", "__pycache__", "*.pyc"))
            copied.append(directory + "/")
        for wanted in extracted:
            shutil.copy2(provenance / wanted, runtime / "DLLs" / wanted)
        report["private_runtime"] = str(runtime)
        report["copied_standard_runtime_entries"] = copied
        stage = "probe_private_runtime_before_venv_rebind"
        private_python = runtime / "python.exe"

        def probe(python):
            checked = subprocess.run([str(python), "-X", "utf8", "-B", "-c", PROBE],
                                     cwd=task, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     text=True, encoding="utf-8", timeout=60)
            require(checked.returncode == 0, "private_runtime_probe_process_failed")
            facts = json.loads(checked.stdout)
            require(facts["python"] == [3, 15, 2] and facts["sqlite"] == [3, 53, 4]
                    and facts["bits"] == 64 and facts["windows"] is True,
                    "private_runtime_does_not_match_public_versions")
            for name, value in facts["loaded_files"].items():
                require(Path(value["path"]).is_relative_to(runtime)
                        and value["sha256"] == extracted[name]["sha256"], "private_runtime_loaded_unexpected_sqlite")
            return facts

        private_probe = probe(private_python)
        report["private_base_probe"] = private_probe
        stage = "rebind_existing_task_venv_without_reinstalling_packages"
        initial_cfg = provenance / "qa315-pyvenv-initial.cfg"
        if not initial_cfg.exists():
            shutil.copy2(qa / "pyvenv.cfg", initial_cfg)
        upgraded = subprocess.run([str(private_python), "-X", "utf8", "-B", "-m", "venv",
                                  "--upgrade", "--without-pip", str(qa)], cwd=task, env=env,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                  encoding="utf-8", timeout=120)
        report["venv_rebind_returncode"] = upgraded.returncode
        require(upgraded.returncode == 0, "task_venv_rebind_failed")
        facts = probe(qa / "Scripts/python.exe")
        require(facts["isolated"] is True and Path(facts["base_prefix"]).resolve() == runtime,
                "venv_did_not_bind_private_runtime")
        for field in ("python", "sqlite", "sqlite_version", "windows", "bits", "machine"):
            require(facts[field] == expected["build_runtime"][field], "runtime_field_differs_from_public_production")
        report["qa_runtime_probe"] = facts
        pins = {}
        for line in (source / "scripts/requirements-build.txt").read_text(encoding="utf-8").splitlines():
            if line and not line.startswith("#"):
                name, separator, version = line.partition("==")
                require(separator, "unfixed_build_dependency")
                pins[name.lower().replace("_", "-")] = version
        sys.path.insert(0, str(source / "scripts"))
        import release

        declared_runtime = {**facts, "packages": pins}
        digest = release.runtime_digest(source, "WORKTREE", declared_runtime)
        require(digest == EXPECTED_RUNTIME_SHA, "declared_recipe_runtime_digest_differs_from_public")
        report["declared_recipe_runtime_sha256"] = digest
        report["declared_recipe_runtime_matches_public"] = True
        report["declared_digest_uses_fixed_recipe_pins_not_claimed_installed_zstandard"] = True
        report["missing_or_drifted_fixed_packages"] = {
            name: {"expected": version, "actual": facts["packages"].get(name)}
            for name, version in pins.items() if facts["packages"].get(name) != version}
        report["full_installed_runtime_verified"] = not report["missing_or_drifted_fixed_packages"]
        require({name: sha(path) for name, path in from_sqlite.items()} == original_hashes,
                "original_base_sqlite_files_changed")
        report.update(verified=True, runtime_fields_match_public=True, base_runtime_unchanged=True,
                      completed_at=datetime.now(timezone.utc).isoformat(),
                      awaiting_trusted_zstandard_wheel=not report["full_installed_runtime_verified"])
        atomic_json(research / "release-private-runtime.json", report)
        print(json.dumps({"verified": True, "private_runtime": str(runtime), "qa_python": str(qa / "Scripts/python.exe"),
                          "python": facts["python"], "sqlite": facts["sqlite_version"],
                          "declared_recipe_runtime_sha256": digest,
                          "missing_fixed_packages": list(report["missing_or_drifted_fixed_packages"])}, indent=2))
        return 0
    except Exception as error:
        report.update(verified=False, failure_stage=stage, failure_type=type(error).__name__,
                      completed_at=datetime.now(timezone.utc).isoformat())
        atomic_json(research / "release-private-runtime.json", report)
        print(json.dumps({"verified": False, "stage": stage, "type": type(error).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
