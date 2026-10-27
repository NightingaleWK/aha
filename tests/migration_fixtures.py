"""An actual schema-1 writer used solely with synthetic, task-owned directories."""

from __future__ import annotations

import hashlib
import sqlite3
import threading
from pathlib import Path
from typing import Any

from test_storage_helpers import claim, metadata, source_data

from aha.analysis import analyze
from aha.domain import canonical_bytes, content_hash
from aha.evidence import build_evidence
from aha.storage import _SCHEMA, Store

OLD_INSERT = (
    "INSERT INTO revisions(batch_id,version,created_at,status,status_updated_at,"
    "analysis_json,claim_json,members_json,overlaps_json,zip_path,zip_hash,file_name,frozen_hash) "
    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)"
)
OLD_UPDATE = "UPDATE revisions SET status=?,status_updated_at=? WHERE batch_id=? AND version=?"


def legacy_store(root: Path) -> Store:
    root.mkdir(parents=True, exist_ok=True)
    (root / "objects").mkdir(exist_ok=True)
    (root / "packages").mkdir(exist_ok=True)
    connection = sqlite3.connect(
        root / "aha.sqlite3", isolation_level=None, check_same_thread=False
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.executescript(_SCHEMA + "\nPRAGMA user_version=1;")
    store = Store.__new__(Store)
    store.data_dir = root
    store._lock = threading.RLock()
    store._closed = False
    store._db = connection
    return store


def legacy_analysis(store: Store, data: dict[str, Any] | None = None) -> dict[str, Any]:
    capture = store.retain(data or source_data(), metadata())
    loaded = store.get_capture(capture["id"])
    result = analyze(loaded["data"], loaded["metadata"], store.config(), "2026-10-24", "2026-10-26")
    # Keep the schema-1 projection even as the current pure analyzer gains v2 annotations.
    for key in ("availability", "claim_revision", "availability_mode", "target_batch_id"):
        result.pop(key, None)
    result["capture_id"] = capture["id"]
    return result


def seed_revision(
    store: Store,
    batch_id: str,
    number: int,
    version: int,
    analysis: dict[str, Any],
    *,
    status: str = "draft",
    purpose: str = "项目开发",
) -> dict[str, Any]:
    now = f"2026-10-27T01:00:{version:02d}+00:00"
    if not store._db.execute("SELECT 1 FROM batches WHERE id=?", (batch_id,)).fetchone():
        store._db.execute("INSERT INTO batches VALUES(?,?,?)", (batch_id, number, now))
    info = {"id": batch_id, "number": f"AHA-{number:06d}", "version": version, "created_at": now}
    capture = store.get_capture(analysis["capture_id"])
    request = claim(purpose=purpose)
    package, filename, _ = build_evidence(analysis, request, info, capture)
    digest = hashlib.sha256(package).hexdigest()
    relative = f"packages/{batch_id}-v{version}-{digest}.zip"
    store._write_immutable(relative, package)
    values = (
        batch_id,
        version,
        now,
        status,
        now,
        canonical_bytes(analysis).decode(),
        canonical_bytes(request).decode(),
        canonical_bytes(analysis["members"]).decode(),
        "[]",
        relative,
        digest,
        filename,
        content_hash({"analysis": analysis, "claim": request, "batch": info}),
    )
    store._db.execute(OLD_INSERT, values)
    store._db.execute(
        "INSERT INTO status_events(batch_id,version,old_status,new_status,changed_at) "
        "VALUES(?,?,NULL,?,?)",
        (batch_id, version, status, now),
    )
    return {"package": package, "filename": filename, "values": values, "analysis": analysis}
