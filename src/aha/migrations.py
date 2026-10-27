"""Application schema evolution, serialized by Store's write transaction."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any

from .claims import evaluate, members_from_analysis, validate_members
from .domain import AppError, content_hash

if TYPE_CHECKING:
    from .storage import Store


V2_STATEMENTS = (
    "ALTER TABLE revisions ADD COLUMN claim_protocol INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE revisions ADD COLUMN write_generation INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE idempotency ADD COLUMN request_signature TEXT NOT NULL DEFAULT ''",
    "INSERT INTO settings(key,value) VALUES('claim_revision','0')",
    """CREATE TABLE batch_control(
        batch_id TEXT PRIMARY KEY NOT NULL REFERENCES batches(id),
        active_version INTEGER,
        lifecycle TEXT NOT NULL CHECK(lifecycle IN ('active','voided','legacy_review')),
        generation INTEGER NOT NULL CHECK(generation>=1),
        voided_at TEXT,void_reason TEXT,
        FOREIGN KEY(batch_id,active_version) REFERENCES revisions(batch_id,version),
        CHECK(lifecycle!='active' OR active_version IS NOT NULL))""",
    """CREATE TABLE usage_claims(
        record_key TEXT PRIMARY KEY NOT NULL,
        batch_id TEXT NOT NULL REFERENCES batches(id),owner_version INTEGER NOT NULL,
        kind TEXT NOT NULL CHECK(kind IN ('detail','rollup')),
        scope_key TEXT NOT NULL,semantic_key TEXT,member_json TEXT NOT NULL,
        FOREIGN KEY(batch_id,owner_version) REFERENCES revisions(batch_id,version))""",
    "CREATE INDEX usage_claim_scope ON usage_claims(scope_key,kind)",
    "CREATE INDEX usage_claim_semantic ON usage_claims(semantic_key) "
    "WHERE semantic_key IS NOT NULL",
    "CREATE INDEX usage_claim_owner ON usage_claims(batch_id)",
    """CREATE TABLE legacy_holds(
        record_key TEXT NOT NULL,batch_id TEXT NOT NULL REFERENCES batches(id),
        version INTEGER NOT NULL,kind TEXT NOT NULL,scope_key TEXT NOT NULL,
        semantic_key TEXT,member_json TEXT NOT NULL,
        PRIMARY KEY(record_key,batch_id,version),
        FOREIGN KEY(batch_id,version) REFERENCES revisions(batch_id,version))""",
    "CREATE INDEX legacy_hold_scope ON legacy_holds(scope_key,kind)",
    "CREATE INDEX legacy_hold_semantic ON legacy_holds(semantic_key) "
    "WHERE semantic_key IS NOT NULL",
    "CREATE INDEX legacy_hold_owner ON legacy_holds(batch_id)",
    """CREATE TABLE claim_events(
        id INTEGER PRIMARY KEY,batch_id TEXT NOT NULL REFERENCES batches(id),version INTEGER,
        action TEXT NOT NULL,reason TEXT NOT NULL,created_at TEXT NOT NULL,
        from_version INTEGER,to_version INTEGER,old_status TEXT,new_status TEXT)""",
    """CREATE TABLE action_idempotency(
        key TEXT PRIMARY KEY NOT NULL,payload_hash TEXT NOT NULL,
        batch_id TEXT NOT NULL REFERENCES batches(id),operation TEXT NOT NULL)""",
    """CREATE TRIGGER revisions_protocol BEFORE INSERT ON revisions
        WHEN NEW.claim_protocol IS NOT 2
        BEGIN SELECT RAISE(ABORT,'aha_upgrade_required'); END""",
    """CREATE TRIGGER revisions_status_protocol
        BEFORE UPDATE OF status,status_updated_at ON revisions
        WHEN NEW.write_generation IS NOT OLD.write_generation+1 OR NOT EXISTS(
            SELECT 1 FROM batch_control c WHERE c.batch_id=OLD.batch_id
            AND c.active_version=OLD.version AND c.lifecycle='active')
        BEGIN SELECT RAISE(ABORT,'aha_upgrade_required'); END""",
    """CREATE TRIGGER claim_events_immutable_update BEFORE UPDATE ON claim_events
        BEGIN SELECT RAISE(ABORT,'aha_immutable_history'); END""",
    """CREATE TRIGGER claim_events_immutable_delete BEFORE DELETE ON claim_events
        BEGIN SELECT RAISE(ABORT,'aha_immutable_history'); END""",
)


def initialize(store: Store, base_schema: str) -> None:
    """Called inside BEGIN IMMEDIATE; never use executescript within this boundary."""
    version = store._db.execute("PRAGMA user_version").fetchone()[0]
    if version == 2:
        return
    if version == 0:
        if store._db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone():
            raise AppError("unsupported_store", "无法识别这份资料，请使用对应版本程序。", 409)
        for statement in base_schema.split(";"):
            if statement.strip():
                store._db.execute(statement)
    elif version == 1:
        store._backup_v1()
    else:
        raise AppError("unsupported_store", "这份资料需要其他版本程序，请保留原目录。", 409)
    for statement in V2_STATEMENTS:
        store._db.execute(statement)
    if version == 1:
        _backfill(store)
    if store._db.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise AppError("migration_damaged", "资料关联校验失败，请保留原目录和升级备份。", 409)
    store._db.execute("PRAGMA user_version=2")


def _backfill(store: Store) -> None:
    from .batches import add_members, record_event

    batches = store._db.execute("SELECT * FROM batches ORDER BY number").fetchall()
    all_entries: list[dict[str, Any]] = []
    versions: dict[str, list[dict[str, Any]]] = {}
    review: set[str] = set()
    try:
        for batch in batches:
            rows = store._db.execute(
                "SELECT * FROM revisions WHERE batch_id=? ORDER BY version", (batch["id"],)
            ).fetchall()
            if not rows:
                raise ValueError
            selected = []
            for row in rows:
                analysis = store._decode(row["analysis_json"])
                if not isinstance(analysis, dict):
                    raise ValueError
                members = members_from_analysis(analysis)
                stored_members = validate_members(store._decode(row["members_json"]))
                declared = {item["key"]: item for item in stored_members}
                if len(declared) != len(stored_members) or set(declared) != {
                    m["key"] for m in members
                }:
                    raise ValueError
                for member in members:
                    if any(
                        declared[member["key"]].get(key) != value for key, value in member.items()
                    ):
                        raise ValueError
                batch_info = {
                    "id": batch["id"],
                    "number": f"AHA-{batch['number']:06d}",
                    "version": row["version"],
                    "created_at": row["created_at"],
                }
                frozen = content_hash(
                    {
                        "analysis": analysis,
                        "claim": store._decode(row["claim_json"]),
                        "batch": batch_info,
                    }
                )
                if frozen != row["frozen_hash"]:
                    raise ValueError
                if hashlib.sha256(store._read_file(row["zip_path"])).hexdigest() != row["zip_hash"]:
                    raise ValueError
                owner = {
                    "batch_id": batch["id"],
                    "number": batch_info["number"],
                    "version": row["version"],
                    "status": row["status"],
                    "lifecycle": "legacy_review",
                }
                entries = [{"member": member, "owner": owner} for member in members]
                selected.append({"row": row, "members": members, "entries": entries})
                all_entries.extend(entries)
            versions[batch["id"]] = selected
            # Multiple v1 revisions were independently mutable; never infer a winner.
            if len(rows) != 1:
                review.add(batch["id"])
        snapshot = {"claim_revision": 0, "claims": [], "legacy_holds": all_entries}
        for batch_id, selected in versions.items():
            for item in selected:
                unavailable = evaluate(item["members"], snapshot, batch_id)["excluded"]
                if unavailable:
                    review.add(batch_id)
                    for exclusion in unavailable:
                        review.update(owner["batch_id"] for owner in exclusion["owners"])
        for batch in batches:
            batch_id = batch["id"]
            selected = versions[batch_id]
            is_review = batch_id in review
            active_version = None if is_review else selected[0]["row"]["version"]
            store._db.execute(
                "INSERT INTO batch_control(batch_id,active_version,lifecycle,generation) "
                "VALUES(?,?,?,1)",
                (batch_id, active_version, "legacy_review" if is_review else "active"),
            )
            for item in selected:
                add_members(
                    store,
                    batch_id,
                    item["row"]["version"],
                    item["members"],
                    hold=is_review,
                )
            record_event(
                store,
                batch_id,
                active_version,
                "migrate",
                "旧资料存在多个候选或重复用量，等待核对。" if is_review else "已升级并保留原记录。",
                None,
                active_version,
                None,
                None,
            )
        if batches:
            store._db.execute("UPDATE settings SET value='1' WHERE key='claim_revision'")
    except (KeyError, TypeError, ValueError, AppError) as exc:
        raise AppError(
            "migration_damaged",
            "旧资料校验失败，升级已取消。请保留原资料和升级备份。",
            409,
        ) from exc
