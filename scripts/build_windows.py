"""Build Windows artifacts with an isolated interpreter, without a shell script."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

RUNTIME_PROBE = """
import json, platform, sqlite3, struct, sys
print(json.dumps({"windows": sys.platform == "win32", "bits": struct.calcsize("P") * 8,
                  "isolated": sys.prefix != sys.base_prefix,
                  "python": list(sys.version_info[:2]), "machine": platform.machine(),
                  "sqlite": list(sqlite3.sqlite_version_info),
                  "sqlite_version": sqlite3.sqlite_version}))
"""


def version_parts(version: object) -> tuple[int, int, int, int]:
    if (
        not isinstance(version, str)
        or re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", version) is None
    ):
        raise ValueError("aha version must be a stable X.Y.Z string.")
    major, minor, patch = (int(part) for part in version.split("."))
    if max(major, minor, patch) > 65535:
        raise ValueError("Version components must fit Windows 16-bit version fields.")
    return major, minor, patch, 0


def read_source_version(source_root: Path) -> str:
    """Read the sole product version without executing package code."""
    tree = ast.parse((source_root / "src" / "aha" / "__init__.py").read_text("utf-8"))
    values = [
        statement.value
        for statement in tree.body
        if isinstance(statement, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "__version__"
                for target in statement.targets)
    ]
    if len(values) != 1 or not isinstance(values[0], ast.Constant):
        raise ValueError("aha.__version__ must be one literal X.Y.Z string.")
    version = values[0].value
    version_parts(version)
    if not isinstance(version, str):
        raise ValueError("aha.__version__ must be a string.")
    config = tomllib.loads((source_root / "pyproject.toml").read_text("utf-8"))
    project = config.get("project", {})
    dynamic = config.get("tool", {}).get("setuptools", {}).get("dynamic", {})
    if (
        "version" in project
        or "version" not in project.get("dynamic", [])
        or dynamic.get("version", {}).get("attr") != "aha.__version__"
    ):
        raise ValueError("Package metadata must derive its version from aha.__version__.")
    return version


def version_resource(version: str) -> str:
    """Generate PyInstaller's Windows version resource from the product version."""
    parts = version_parts(version)
    return (
        "VSVersionInfo(\n"
        "  ffi=FixedFileInfo(\n"
        f"    filevers={parts!r}, prodvers={parts!r},\n"
        "    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),\n"
        "  kids=[StringFileInfo([StringTable('040904B0', [\n"
        "    StringStruct('CompanyName', 'aha'),\n"
        "    StringStruct('FileDescription', 'aha usage ledger'),\n"
        f"    StringStruct('FileVersion', {version!r}),\n"
        "    StringStruct('InternalName', 'aha'),\n"
        "    StringStruct('OriginalFilename', 'aha.exe'),\n"
        "    StringStruct('ProductName', 'aha'),\n"
        f"    StringStruct('ProductVersion', {version!r})\n"
        "  ])]), VarFileInfo([VarStruct('Translation', [1033, 1200])])])\n"
    )


def inspect_runtime(python_exe: Path) -> dict[str, Any]:
    probe = subprocess.run(
        [str(python_exe), "-"],
        input=RUNTIME_PROBE,
        text=True,
        capture_output=True,
        check=True,
    )
    runtime = json.loads(probe.stdout)
    if not isinstance(runtime, dict):
        raise ValueError("Cannot inspect the selected Python runtime.")
    if not runtime.get("windows") or runtime.get("bits") != 64 or not runtime.get("isolated"):
        raise ValueError("Use a 64-bit Windows Python venv; Linux output is not a Windows app.")
    version = runtime.get("python", [])
    if not isinstance(version, list) or len(version) != 2 or version[0] != 3 or version[1] < 12:
        raise ValueError("Python 3.12 or newer is required.")
    sqlite_version = runtime.get("sqlite", [])
    if (
        not isinstance(sqlite_version, list)
        or len(sqlite_version) != 3
        or any(isinstance(part, bool) or not isinstance(part, int) for part in sqlite_version)
    ):
        raise ValueError("Cannot inspect the selected SQLite runtime.")
    release = tuple(sqlite_version)
    fixed = (
        release >= (3, 51, 3)
        or release[:2] == (3, 50)
        and release[2] >= 7
        or release[:2] == (3, 44)
        and release[2] >= 6
    )
    if not fixed:
        raise ValueError("Use a task-isolated SQLite runtime with the WAL-reset fix (3.51.3+).")
    return runtime


def build(
    python_exe: Path,
    build_root: Path,
    source_root: Path,
    stage: str,
) -> Path:
    if stage not in {"Directory", "OneFile"}:
        raise ValueError("Unknown build stage.")
    version = read_source_version(source_root)
    runtime = inspect_runtime(python_exe)
    script_dir = source_root / "scripts"
    requirements = script_dir / "requirements-build.txt"
    collector = script_dir / "collect_licenses.py"
    launcher = script_dir / "launch.py"
    web_dir = source_root / "src" / "aha" / "web"
    if (
        not all(path.is_file() for path in (requirements, collector, launcher))
        or not web_dir.is_dir()
    ):
        raise ValueError("SourceRoot must contain the aha sources and build helpers.")
    build_root.mkdir(parents=True, exist_ok=True)
    version_file = build_root / "aha-version.txt"
    version_file.write_text(version_resource(version), encoding="utf-8")
    runtime["application_version"] = version
    (build_root / "runtime-versions.json").write_text(
        json.dumps(runtime, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    subprocess.run(
        [
            str(python_exe),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "-r",
            str(requirements),
        ],
        check=True,
    )
    license_dir = build_root / "licenses"
    subprocess.run([str(python_exe), str(collector), str(license_dir)], check=True)
    stage_name = "directory" if stage == "Directory" else "portable"
    dist = build_root / "release" / stage_name
    work = build_root / "pyinstaller" / stage_name
    spec = build_root / "spec" / stage_name
    for directory in (dist, work, spec):
        directory.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            str(python_exe),
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--windowed",
            "--onedir" if stage == "Directory" else "--onefile",
            "--name",
            "aha",
            "--icon",
            str(web_dir / "mark.ico"),
            "--version-file",
            str(version_file),
            "--paths",
            str(source_root / "src"),
            "--collect-all",
            "zstandard",
            "--copy-metadata",
            "zstandard",
            "--add-data",
            f"{web_dir};aha/web",
            "--add-data",
            f"{license_dir};aha/licenses",
            "--distpath",
            str(dist),
            "--workpath",
            str(work),
            "--specpath",
            str(spec),
            str(launcher),
        ],
        check=True,
    )
    executable = dist / "aha" / "aha.exe" if stage == "Directory" else dist / "aha.exe"
    if not executable.is_file():
        raise ValueError("PyInstaller did not produce the expected executable.")
    with executable.open("rb") as artifact:
        fingerprint = hashlib.file_digest(artifact, "sha256").hexdigest()
    print(f"AHA_EXECUTABLE={executable}", flush=True)
    print(f"AHA_SHA256={fingerprint}", flush=True)
    print(f"AHA_VERSION={version}", flush=True)
    if stage == "Directory":
        print("Next: verify the directory build on Windows, then build OneFile.", flush=True)
    return executable


def main() -> None:
    parser = argparse.ArgumentParser(description="Build aha in an isolated Windows Python venv")
    parser.add_argument("--python-exe", type=Path, default=Path(sys.executable))
    parser.add_argument("--build-root", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--stage", choices=("Directory", "OneFile"), default="Directory")
    parser.add_argument("--directory-verified", action="store_true")
    args = parser.parse_args()
    if args.stage == "OneFile" and not args.directory_verified:
        parser.error("Verify the Directory build on Windows first, then pass --directory-verified.")
    try:
        python_exe = args.python_exe.resolve(strict=True)
        source_root = args.source_root.resolve(strict=True)
        build_root = args.build_root.resolve()
        if build_root == source_root:
            raise ValueError("BuildRoot must be a separate task-owned directory.")
        if sys.platform != "win32":
            raise ValueError("Run this build entry point on Windows.")
        build(python_exe, build_root, source_root, args.stage)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Build failed: {error}\n")


if __name__ == "__main__":
    main()
