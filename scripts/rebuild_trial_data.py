"""Preserve historical usage, then explicitly rebuild only inspected aha trial files.

The default inspect command is read-only. This one-time operator tool does not
migrate projects, claims, batches, or old application protocols into the product.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MAX_OBJECT_BYTES = 512 * 1024 * 1024
OBJECT = re.compile(r"(?:usage|metadata)-[0-9a-f]{64}\.json\.gz\Z")
USAGE = re.compile(r"usage-([0-9a-f]{64})\.json\.gz\Z")
PACKAGE = re.compile(r"[0-9a-f-]{36}-v[1-9][0-9]*-[0-9a-f]{64}\.zip\Z")
BACKUP = re.compile(r"aha-v[12]-[A-Za-z0-9-]+\.sqlite3\Z")


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def fingerprint(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def is_link(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()


def inside(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def safe_root(path: Path, *, exists: bool = True) -> Path:
    original = path.absolute()
    for candidate in (original, *original.parents):
        if is_link(candidate):
            raise ValueError("Symbolic links and junctions are not allowed for rebuild paths.")
    root = original.resolve(strict=exists)
    if exists and not root.is_dir():
        raise ValueError("The selected trial directory is not a directory.")
    return root


def protected_paths(paths: list[Path]) -> list[Path]:
    return [path.absolute().resolve() for path in [Path.home() / ".cc-switch", *paths]]


def ensure_not_protected(path: Path, protected: list[Path]) -> None:
    if any(inside(path.resolve(), source) or path.resolve() == source for source in protected):
        raise ValueError("A selected path belongs to protected CCS source data.")


def safe_child(root: Path, relative: str, protected: list[Path]) -> Path:
    part = Path(relative)
    if part.is_absolute() or not part.parts or any(x in {".", ".."} for x in part.parts):
        raise ValueError("Invalid relative file in rebuild manifest.")
    # A Windows path must not become a harmless-looking filename on Linux.
    if "\\" in relative or ":" in relative:
        raise ValueError("Cross-platform or drive paths are not accepted in a manifest.")
    path = root / part
    for candidate in (path, *path.parents):
        if candidate == root.parent:
            break
        if is_link(candidate):
            raise ValueError("A rebuild candidate is a symbolic link or junction.")
    if not inside(path.resolve(), root):
        raise ValueError("A rebuild candidate escapes the trial directory.")
    ensure_not_protected(path, protected)
    return path


def recognized(relative: str) -> bool:
    part = Path(relative)
    if relative in {"aha.sqlite3", "aha.sqlite3-wal", "aha.sqlite3-shm", "runtime.json"}:
        return True
    if len(part.parts) != 2:
        return False
    parent, name = part.parts
    return bool(
        parent == "objects"
        and OBJECT.fullmatch(name)
        or parent == "packages"
        and PACKAGE.fullmatch(name)
        or parent == "backups"
        and BACKUP.fullmatch(name)
    )


def assert_trial_database(root: Path) -> None:
    path = root / "aha.sqlite3"
    if not path.is_file():
        return
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.25)
    try:
        connection.execute("PRAGMA query_only=ON")
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if version not in {1, 2} or not {"settings", "projects", "captures", "batches"}.issubset(
            tables
        ):
            raise ValueError("The application database is not a recognized aha trial database.")
    finally:
        connection.close()


def process_alive(pid: int) -> bool:
    if pid <= 0:
        raise ValueError("Invalid process identifier in the launch descriptor.")
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() == 5
        try:
            code = wintypes.DWORD()
            return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def assert_stopped(root: Path) -> None:
    descriptor = root / "runtime.json"
    if descriptor.exists():
        data = json.loads(descriptor.read_text())
        pid = data.get("pid")
        if isinstance(pid, bool) or not isinstance(pid, int) or process_alive(pid):
            raise ValueError("The old program may still be running; close it before rebuilding.")


def inspect(root: Path, protected: list[Path]) -> dict[str, Any]:
    root = safe_root(root)
    ensure_not_protected(root, protected)
    files, untouched = [], []
    for directory, directories, names in os.walk(root, followlinks=False):
        parent = Path(directory)
        for name in list(directories):
            candidate = parent / name
            if is_link(candidate):
                directories.remove(name)
                untouched.append(candidate.relative_to(root).as_posix())
        for name in sorted(names):
            path = parent / name
            relative = path.relative_to(root).as_posix()
            if not recognized(relative) or is_link(path):
                untouched.append(relative)
                continue
            safe_child(root, relative, protected)
            files.append(
                {"relative": relative, "bytes": path.stat().st_size, "sha256": fingerprint(path)}
            )
    assert_trial_database(root)
    return {
        "format_version": 1,
        "data_dir": str(root),
        "created_at": datetime.now(UTC).isoformat(),
        "protected_sources": [str(p) for p in protected],
        "files": sorted(files, key=lambda x: x["relative"]),
        "untouched": sorted(untouched),
    }


def load_usage(path: Path) -> dict[str, Any]:
    match = USAGE.fullmatch(path.name)
    if match is None:
        raise ValueError("Not a historical usage object.")
    with gzip.open(path, "rb") as source:
        raw = source.read(MAX_OBJECT_BYTES + 1)
    if len(raw) > MAX_OBJECT_BYTES:
        raise ValueError("Historical usage object exceeds the extraction limit.")
    data = json.loads(raw)
    if not isinstance(data, dict) or hashlib.sha256(canonical(data)).hexdigest() != match[1]:
        raise ValueError("Historical usage object checksum failed.")
    if (
        data.get("format_version") != 1
        or data.get("adapter_version") != 1
        or data.get("schema_version") != 23
    ):
        raise ValueError("Unsupported historical usage projection.")
    return data


def extract(root: Path, output: Path) -> dict[str, Any]:
    from aha.domain import build_source_data

    root = safe_root(root)
    output = safe_root(output, exists=False)
    if inside(output, root) or inside(root, output) or output.exists():
        raise ValueError("Extraction requires a new directory outside the trial directory.")
    output.mkdir(parents=True)
    entries = []
    for path in sorted((root / "objects").glob("usage-*.json.gz")):
        safe_child(root, path.relative_to(root).as_posix(), [])
        data = load_usage(path)
        projected = build_source_data(
            data.get("details", []),
            data.get("rollups", []),
            data.get("pricing", []),
            {
                "kind": "historical_projection",
                "name": path.name,
                "fingerprint_kind": "allowed_projection_sha256",
                "fingerprint": hashlib.sha256(canonical(data)).hexdigest(),
                "observed_at": datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
            },
        )
        name = "history-" + hashlib.sha256(canonical(projected)).hexdigest() + ".json.gz"
        target = output / name
        with target.open("xb") as destination:
            destination.write(gzip.compress(canonical(projected), mtime=0))
            destination.flush()
            os.fsync(destination.fileno())
        entries.append(
            {
                "input_relative": path.relative_to(root).as_posix(),
                "input_sha256": fingerprint(path),
                "output_relative": name,
                "output_sha256": fingerprint(target),
                "detail_count": len(projected["details"]),
                "rollup_count": len(projected["rollups"]),
            }
        )
    index = {"format_version": 1, "entries": entries}
    (output / "history-index.json").write_bytes(canonical(index))
    return index


def preserved_usage(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rb") as source:
        raw = source.read(MAX_OBJECT_BYTES + 1)
    if len(raw) > MAX_OBJECT_BYTES:
        raise ValueError("Preserved history input exceeds the import limit.")
    data = json.loads(raw)
    if (
        not isinstance(data, dict)
        or data.get("schema_version") != 23
        or set(data) != {"schema_version", "details", "rollups", "pricing", "source"}
    ):
        raise ValueError("Invalid preserved history projection.")
    return data


def read_index(path: Path) -> tuple[Path, dict[str, dict[str, Any]]]:
    parent = safe_root(path.parent)
    if is_link(path):
        raise ValueError("History index must not be a symbolic link.")
    index = json.loads(path.read_text())
    if not isinstance(index, dict) or index.get("format_version") != 1:
        raise ValueError("Unsupported history index.")
    entries = index.get("entries")
    if not isinstance(entries, list):
        raise ValueError("Invalid history index entries.")
    result = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Invalid history entry.")
        relative = entry.get("input_relative")
        if (
            not isinstance(relative, str)
            or relative in result
            or not relative.startswith("objects/usage-")
        ):
            raise ValueError("Invalid or duplicate history input.")
        target = safe_child(parent, entry["output_relative"], [])
        if not target.is_file() or fingerprint(target) != entry["output_sha256"]:
            raise ValueError("Preserved history input is missing or changed.")
        match = USAGE.fullmatch(Path(relative).name)
        if len(Path(relative).parts) != 2 or Path(relative).parts[0] != "objects" or match is None:
            raise ValueError("Invalid history input path.")
        if preserved_usage(target).get("source", {}).get("fingerprint") != match[1]:
            raise ValueError("Preserved history provenance does not match its input.")
        result[relative] = entry
    return parent, result


def copy_verified(source: Path, target: Path, expected: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as incoming, target.open("xb") as outgoing:
        shutil.copyfileobj(incoming, outgoing, length=1024 * 1024)
        outgoing.flush()
        os.fsync(outgoing.fileno())
    if fingerprint(target) != expected:
        raise ValueError("Backup checksum failed; trial data was not cleared.")


def apply_manifest(
    root: Path, manifest: dict[str, Any], backup: Path, history_index: Path, protected: list[Path]
) -> dict[str, Any]:
    if not isinstance(manifest, dict):
        raise ValueError("Invalid rebuild manifest.")
    root = safe_root(root)
    declared = manifest.get("protected_sources", [])
    if not isinstance(declared, list) or any(not isinstance(value, str) for value in declared):
        raise ValueError("Invalid protected source list.")
    protected = [*protected, *protected_paths([Path(value) for value in declared])]
    ensure_not_protected(root, protected)
    if manifest.get("format_version") != 1 or Path(manifest.get("data_dir", "")).resolve() != root:
        raise ValueError("Manifest does not belong to the selected trial directory.")
    assert_stopped(root)
    assert_trial_database(root)
    history_root, preserved = read_index(history_index)
    candidates = manifest.get("files")
    if not isinstance(candidates, list):
        raise ValueError("Invalid rebuild manifest.")
    selected: list[tuple[Path, str, str]] = []
    seen = set()
    for item in candidates:
        if not isinstance(item, dict) or not isinstance(item.get("relative"), str):
            raise ValueError("Invalid rebuild candidate.")
        relative = item["relative"]
        if relative in seen or not recognized(relative):
            raise ValueError("The manifest contains duplicate or unrecognized files.")
        seen.add(relative)
        path = safe_child(root, relative, protected)
        if not path.is_file() or fingerprint(path) != item["sha256"]:
            raise ValueError("Trial data changed since inspection; inspect again.")
        if (
            USAGE.fullmatch(path.name)
            and preserved.get(relative, {}).get("input_sha256") != item["sha256"]
        ):
            raise ValueError("Historical usage has not been preserved; cleanup refused.")
        if USAGE.fullmatch(path.name):
            original = load_usage(path)
            saved = preserved_usage(
                safe_child(history_root, preserved[relative]["output_relative"], [])
            )
            if any(
                saved[key] != original[key]
                for key in ("schema_version", "details", "rollups", "pricing")
            ):
                raise ValueError("Preserved history does not contain the complete original usage.")
        selected.append((path, relative, item["sha256"]))
    actual = inspect(root, protected)
    if {entry["relative"] for entry in actual["files"]} != seen:
        raise ValueError("Trial file set changed since inspection; inspect again.")
    backup = safe_root(backup, exists=False)
    ensure_not_protected(backup, protected)
    if backup.exists() or inside(backup, root) or inside(root, backup):
        raise ValueError("Backup must be a new directory outside the trial directory.")
    backup.mkdir(parents=True)
    for path, relative, digest in selected:
        copy_verified(path, backup / relative, digest)
    report = {
        "format_version": 1,
        "data_dir": str(root),
        "files": candidates,
        "status": "preserved",
        "untouched": manifest.get("untouched", []),
    }
    (backup / "rebuild-manifest.json").write_bytes(canonical(report))
    removed = []
    try:
        assert_stopped(root)
        for _, relative, digest in selected:
            path = safe_child(root, relative, protected)
            if fingerprint(path) != digest:
                raise ValueError("Trial data changed while preparing the rebuild.")
            path.unlink()
            removed.append(relative)
    except BaseException:
        for relative in removed:
            target = safe_child(root, relative, protected)
            if not target.exists():
                copy_verified(backup / relative, target, fingerprint(backup / relative))
        raise
    report["status"] = "completed"
    report["removed_count"] = len(removed)
    (backup / "rebuild-manifest.json").write_bytes(canonical(report))
    return report


def import_history(data_dir: Path, history_index: Path) -> dict[str, Any]:
    from aha.storage import Store

    data_dir = safe_root(data_dir, exists=data_dir.exists())
    ensure_not_protected(data_dir, protected_paths([]))
    parent, entries = read_index(history_index)
    results = []
    store = Store(data_dir)
    try:
        for entry in entries.values():
            path = safe_child(parent, entry["output_relative"], [])
            with gzip.open(path, "rb") as source:
                raw = source.read(MAX_OBJECT_BYTES + 1)
            if len(raw) > MAX_OBJECT_BYTES:
                raise ValueError("Preserved history input exceeds the import limit.")
            results.append(store.sync_data(json.loads(raw), trust="backup", trigger="manual"))
        return {"runs": results, "ledger": store.ledger_status()}
    finally:
        store.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect or explicitly rebuild aha trial data")
    parser.add_argument("command", choices=("inspect", "extract", "apply", "import-history"))
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--protected-source", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--history-index", type=Path)
    args = parser.parse_args()
    try:
        protected = protected_paths(args.protected_source)
        if args.output is not None:
            ensure_not_protected(args.output, protected)
            if args.output.exists():
                raise ValueError("Output file already exists; choose a new output file.")
        if args.command in {"extract", "import-history"}:
            source_root = Path(__file__).resolve().parents[1] / "src"
            if source_root.is_dir():
                sys.path.insert(0, str(source_root))
        if args.command == "inspect":
            result = inspect(args.data_dir, protected)
        elif args.command == "extract":
            if args.output_dir is None:
                parser.error("extract requires --output-dir")
            ensure_not_protected(args.output_dir, protected)
            result = extract(args.data_dir, args.output_dir)
        elif args.command == "apply":
            if args.manifest is None or args.backup_dir is None or args.history_index is None:
                parser.error("apply requires --manifest, --backup-dir and --history-index")
            if is_link(args.manifest):
                raise ValueError("The rebuild manifest must not be a symbolic link.")
            manifest = json.loads(args.manifest.read_text())
            result = apply_manifest(
                args.data_dir, manifest, args.backup_dir, args.history_index, protected
            )
        else:
            if args.history_index is None:
                parser.error("import-history requires --history-index")
            ensure_not_protected(args.data_dir, protected)
            result = import_history(args.data_dir, args.history_index)
        encoded = canonical(result)
        if args.output is not None:
            with args.output.open("xb") as output:
                output.write(encoded + b"\n")
        else:
            print(encoded.decode())
    except (OSError, ValueError, sqlite3.Error, KeyError, TypeError) as error:
        parser.exit(1, f"Rebuild stopped: {error}\n")


if __name__ == "__main__":
    main()
