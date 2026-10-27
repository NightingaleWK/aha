"""Exclusive usage ownership, immutable revisions and audited claim lifecycle."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

from .claims import evaluate, members_from_analysis, scope_key, semantic_key, validate_members
from .domain import (
    DETAIL_FIELDS,
    ROLLUP_FIELDS,
    AppError,
    content_hash,
    record_key,
    row_fingerprint,
)
from .evidence import build_evidence, validate_claim

if TYPE_CHECKING:
    import sqlite3

    from .storage import Store

STATUSES = {"draft": "草稿", "submitted": "已提交", "reimbursed": "已报销"}
_TRANSIENT = {
    "analysis_id",
    "claim_revision",
    "availability",
    "availability_mode",
    "target_batch_id",
    "expected_generation",
    "expected_active_version",
    "usage_state",
    "usage_owners",
    "usage_reason",
    "semantic_key",
}


def _business(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _business(item) for key, item in value.items() if key not in _TRANSIENT}
    if isinstance(value, list):
        return [_business(item) for item in value]
    return value


def _analysis_hash(analysis: dict[str, Any]) -> str:
    # Freeze business facts, not warning prose or the current availability annotations.
    fields = (
        "capture_id",
        "start_date",
        "end_date",
        "project_id",
        "project_name",
        "classification_revision",
        "schema_version",
        "timezone",
        "metadata_fingerprint",
        "summary",
    )
    facts = {key: analysis.get(key) for key in fields}
    assignments = ("project_id", "project_name", "assignment_origin")
    facts["details"] = [
        {key: row.get(key) for key in (*DETAIL_FIELDS, *assignments)}
        for row in analysis.get("details", [])
    ]
    facts["rollups"] = [
        {key: row.get(key) for key in (*ROLLUP_FIELDS, *assignments)}
        for row in analysis.get("rollups", [])
    ]
    facts["members"] = _business(analysis.get("members", []))
    return content_hash(facts)


def _revision(store: Store, batch_id: str, version: int) -> sqlite3.Row:
    row = store._db.execute(
        "SELECT * FROM revisions WHERE batch_id=? AND version=?", (batch_id, version)
    ).fetchone()
    if row is None:
        raise AppError("revision_not_found", "找不到这份材料，请刷新报销记录。", 404)
    return cast("sqlite3.Row", row)


def _control(store: Store, batch_id: str) -> sqlite3.Row:
    row = store._db.execute("SELECT * FROM batch_control WHERE batch_id=?", (batch_id,)).fetchone()
    if row is None:
        raise AppError("batch_not_found", "找不到这条报销记录，请刷新。", 404)
    return cast("sqlite3.Row", row)


def _check_generation(control: sqlite3.Row, expected: int | None) -> None:
    if expected is not None and (
        not isinstance(expected, int)
        or isinstance(expected, bool)
        or expected != control["generation"]
    ):
        raise AppError("stale_batch", "这条报销记录已更新，请刷新后重试。", 409)


def _effective(
    store: Store, batch_id: str, version: int | None = None
) -> tuple[sqlite3.Row, sqlite3.Row]:
    control = _control(store, batch_id)
    if control["lifecycle"] == "voided":
        raise AppError("batch_voided", "这条报销记录已作废，可查看或下载历史材料。", 409)
    if control["lifecycle"] == "legacy_review":
        raise AppError("migration_conflicts", "这条旧记录需要先核对用量和有效版本。", 409)
    if version is not None and version != control["active_version"]:
        raise AppError("inactive_revision", "这是历史版本，请使用当前记录。", 409)
    return control, _revision(store, batch_id, control["active_version"])


def _revision_result(
    store: Store, row: sqlite3.Row, *, include_analysis: bool = False
) -> dict[str, Any]:
    batch = store._db.execute("SELECT * FROM batches WHERE id=?", (row["batch_id"],)).fetchone()
    control = _control(store, row["batch_id"])
    analysis = store._decode(row["analysis_json"])
    effective = control["lifecycle"] == "active" and control["active_version"] == row["version"]
    draft = effective and row["status"] == "draft"
    result = {
        "id": row["batch_id"],
        "batch_id": row["batch_id"],
        "number": f"AHA-{batch['number']:06d}",
        "batch_number": f"AHA-{batch['number']:06d}",
        "version": row["version"],
        "status": row["status"],
        "created_at": row["created_at"],
        "status_updated_at": row["status_updated_at"],
        "filename": row["file_name"],
        "sha256": row["zip_hash"],
        "zip_sha256": row["zip_hash"],
        "frozen_hash": row["frozen_hash"],
        "total_cost_usd": analysis["summary"]["total_cost_usd"],
        "claim": store._decode(row["claim_json"]),
        "overlaps": store._decode(row["overlaps_json"]),
        "summary": analysis["summary"],
        "capture_id": analysis["capture_id"],
        "start_date": analysis["start_date"],
        "end_date": analysis["end_date"],
        "project_id": analysis.get("project_id", "all"),
        "project_name": analysis.get("project_name", "全部项目"),
        "classification_revision": analysis["classification_revision"],
        "lifecycle": control["lifecycle"],
        "active_version": control["active_version"],
        "generation": control["generation"],
        "is_effective": effective,
        "voided_at": control["voided_at"],
        "void_reason": control["void_reason"],
        "can_edit": draft,
        "can_submit": draft,
        "can_reimburse": effective and row["status"] in {"draft", "submitted"},
        "can_withdraw": effective and row["status"] == "submitted",
        "can_void": effective or control["lifecycle"] == "legacy_review",
        "can_resolve": control["lifecycle"] == "legacy_review",
    }
    if include_analysis:
        result["analysis"] = analysis
    return result


def _current_result(store: Store, batch_id: str) -> dict[str, Any]:
    control = _control(store, batch_id)
    latest = store._db.execute(
        "SELECT MAX(version) FROM revisions WHERE batch_id=?", (batch_id,)
    ).fetchone()[0]
    version = control["active_version"] or latest
    result = _revision_result(store, _revision(store, batch_id, version))
    result["latest_version"] = latest
    return result


def _snapshot_unlocked(store: Store, exclude_batch_id: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "claim_revision": store.claim_revision(),
        "claims": [],
        "legacy_holds": [],
    }
    for table, version_field in (("usage_claims", "owner_version"), ("legacy_holds", "version")):
        rows = store._db.execute(
            f"SELECT u.*,b.number,r.status,c.lifecycle FROM {table} u "
            f"JOIN batches b ON b.id=u.batch_id JOIN revisions r ON "
            f"r.batch_id=u.batch_id AND r.version=u.{version_field} "
            "JOIN batch_control c ON c.batch_id=u.batch_id ORDER BY b.number"
        ).fetchall()
        for row in rows:
            if row["batch_id"] == exclude_batch_id:
                continue
            try:
                member = validate_members([store._decode(row["member_json"])])[0]
                if member["key"] != row["record_key"] or scope_key(member) != row["scope_key"]:
                    raise ValueError
            except (ValueError, AppError) as exc:
                raise AppError(
                    "storage_damaged", "占用资料校验失败，请保留资料目录。", 409
                ) from exc
            result["claims" if table == "usage_claims" else "legacy_holds"].append(
                {
                    "member": member,
                    "owner": {
                        "batch_id": row["batch_id"],
                        "number": f"AHA-{row['number']:06d}",
                        "version": row[version_field],
                        "status": row["status"],
                        "lifecycle": row["lifecycle"],
                    },
                }
            )
    return result


def claim_snapshot(store: Store, exclude_batch_id: str | None = None) -> dict[str, Any]:
    with store._lock:
        store._ensure_open()
        own_read = not store._db.in_transaction
        if own_read:
            store._db.execute("BEGIN")
        try:
            result = _snapshot_unlocked(store, exclude_batch_id)
            if own_read:
                store._db.execute("COMMIT")
            return result
        except BaseException:
            if own_read and store._db.in_transaction:
                store._db.execute("ROLLBACK")
            raise


def overlaps(
    store: Store, analysis: dict[str, Any], exclude_batch_id: str | None = None
) -> list[dict[str, Any]]:
    outcome = evaluate(analysis.get("members", []), claim_snapshot(store), exclude_batch_id)
    groups: dict[tuple[str | None, int | None], dict[str, Any]] = {}
    for excluded in outcome["excluded"]:
        owners = excluded["owners"] or [
            {
                "batch_id": None,
                "version": None,
                "number": None,
                "status": "legacy_review",
                "lifecycle": "legacy_review",
            }
        ]
        for owner in owners:
            key = (owner["batch_id"], owner["version"])
            group = groups.setdefault(
                key,
                {
                    **owner,
                    "batch_number": owner["number"],
                    "types": set(),
                    "certain_count": 0,
                    "possible_count": 0,
                    "blocking": True,
                },
            )
            group["types"].add(excluded["reason"])
            group["certain_count" if excluded["reason"] == "identity" else "possible_count"] += 1
    results = []
    for group in groups.values():
        group["types"] = sorted(group["types"])
        group["message"] = (
            f"部分用量已由 {group['number']} 使用，请查看该记录。"
            if group["number"]
            else "来源中的明细与历史汇总可能重复，请核对数据。"
        )
        results.append(group)
    return results


def add_members(
    store: Store, batch_id: str, version: int, members: list[dict[str, Any]], *, hold: bool = False
) -> None:
    table = "legacy_holds" if hold else "usage_claims"
    version_column = "version" if hold else "owner_version"
    for member in members:
        store._db.execute(
            f"INSERT INTO {table}(record_key,batch_id,{version_column},kind,"
            f"scope_key,semantic_key,member_json) "
            "VALUES(?,?,?,?,?,?,?)",
            (
                member["key"],
                batch_id,
                version,
                member["kind"],
                scope_key(member),
                semantic_key(member),
                store._encode(member),
            ),
        )


def record_event(
    store: Store,
    batch_id: str,
    version: int | None,
    action: str,
    reason: str,
    from_version: int | None,
    to_version: int | None,
    old_status: str | None,
    new_status: str | None,
) -> None:
    store._db.execute(
        "INSERT INTO claim_events(batch_id,version,action,reason,created_at,"
        "from_version,to_version,old_status,new_status) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (
            batch_id,
            version,
            action,
            reason,
            store._now(),
            from_version,
            to_version,
            old_status,
            new_status,
        ),
    )


def _advance(store: Store) -> None:
    store._db.execute(
        "UPDATE settings SET value=CAST(value AS INTEGER)+1 WHERE key='claim_revision'"
    )


def _key(value: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise AppError("invalid_idempotency_key", "操作信息不完整，请刷新后重试。")


def _validate_analysis(analysis: dict[str, Any]) -> None:
    if not isinstance(analysis, dict) or not all(
        isinstance(analysis.get(key), list)
        for key in ("details", "rollups", "daily", "models", "members")
    ):
        raise AppError("invalid_analysis", "用量内容不完整，请更新预览。")
    if (
        not isinstance(analysis.get("summary"), dict)
        or not all(
            isinstance(analysis.get(key), str) for key in ("capture_id", "start_date", "end_date")
        )
        or not isinstance(analysis.get("classification_revision"), int)
    ):
        raise AppError("invalid_analysis", "用量预览无效，请更新预览。")


def _validate_capture(
    store: Store, analysis: dict[str, Any], members: list[dict[str, Any]]
) -> dict[str, Any]:
    capture = store.get_capture(analysis["capture_id"])
    originals = {
        record_key(row, kind): row_fingerprint(row, kind)
        for kind, field in (("detail", "details"), ("rollup", "rollups"))
        for row in capture["data"][field]
    }
    if any(originals.get(member["key"]) != member["content_hash"] for member in members):
        raise AppError("invalid_analysis", "用量与所选数据不一致，请更新预览。", 409)
    return capture


def _check_available(store: Store, members: list[dict[str, Any]], batch_id: str | None) -> None:
    exclusions = evaluate(members, _snapshot_unlocked(store), batch_id)["excluded"]
    if exclusions:
        if any(item["reason"] == "internal_overlap" for item in exclusions):
            raise AppError(
                "usage_internal_overlap", "所选明细和历史汇总可能重复，请更新预览。", 409
            )
        if any(item["reason"] != "identity" for item in exclusions):
            raise AppError("usage_ambiguous", "部分用量可能重复或正在核对，请更新预览。", 409)
        raise AppError("usage_claimed", "部分用量已被其他报销记录占用，请更新预览。", 409)


def replay_create(
    store: Store, idempotency_key: str, request_signature: str
) -> dict[str, Any] | None:
    _key(idempotency_key)
    with store._lock:
        store._ensure_open()
        prior = store._db.execute(
            "SELECT * FROM idempotency WHERE key=?", (idempotency_key,)
        ).fetchone()
        if prior is None:
            if store._db.execute(
                "SELECT 1 FROM action_idempotency WHERE key=?", (idempotency_key,)
            ).fetchone():
                raise AppError("idempotency_conflict", "操作标识已用于其他操作，请重新发起。", 409)
            return None
        if not prior["request_signature"] or prior["request_signature"] != request_signature:
            raise AppError(
                "idempotency_conflict", "请求内容已变化，请从报销记录查看已保存材料。", 409
            )
        download(store, prior["batch_id"], prior["version"])
        return _revision_result(store, _revision(store, prior["batch_id"], prior["version"]))


def create_batch(
    store: Store,
    analysis: dict[str, Any],
    claim: dict[str, Any],
    idempotency_key: str,
    batch_id: str | None = None,
    *,
    expected_generation: int | None = None,
    expected_active_version: int | None = None,
    request_signature: str | None = None,
) -> dict[str, Any]:
    _validate_analysis(analysis)
    claim = validate_claim(claim)
    _key(idempotency_key)
    analysis = store._decode(store._encode(analysis))
    members = members_from_analysis(analysis)
    analysis["members"] = members
    payload_hash = content_hash(
        {"analysis_hash": _analysis_hash(analysis), "claim": claim, "batch_id": batch_id}
    )
    with store._transaction():
        prior = store._db.execute(
            "SELECT * FROM idempotency WHERE key=?", (idempotency_key,)
        ).fetchone()
        if prior is not None:
            if prior["payload_hash"] != payload_hash or (
                request_signature is not None and prior["request_signature"] != request_signature
            ):
                raise AppError("idempotency_conflict", "请求内容已变化，请重新发起操作。", 409)
            download(store, prior["batch_id"], prior["version"])
            return _revision_result(store, _revision(store, prior["batch_id"], prior["version"]))
        if store._db.execute(
            "SELECT 1 FROM action_idempotency WHERE key=?", (idempotency_key,)
        ).fetchone():
            raise AppError("idempotency_conflict", "操作标识已用于其他操作，请重新发起。", 409)
        control = None
        active = None
        if batch_id is not None:
            control, active = _effective(store, batch_id, expected_active_version)
            _check_generation(control, expected_generation)
            if active["status"] != "draft":
                raise AppError(
                    "batch_not_editable", "请先撤回已提交记录；已报销记录需作废后重新填写。", 409
                )
        if analysis.get("target_batch_id") != batch_id:
            raise AppError("analysis_target_mismatch", "预览与报销记录不一致，请重新预览。", 409)
        if analysis.get("availability_mode") != "available":
            raise AppError("readonly_analysis", "全部用量仅供查看，请切换到可用用量。", 409)
        if not members:
            raise AppError("empty_usage", "没有可用用量，无法保存报销记录。", 409)
        frozen_same = active is not None and _analysis_hash(
            store._decode(active["analysis_json"])
        ) == _analysis_hash(analysis)
        if analysis["classification_revision"] != store.config()["revision"] and not frozen_same:
            raise AppError("stale_analysis", "项目归属已变化，请更新预览。", 409)
        if active is not None and frozen_same and store._decode(active["claim_json"]) == claim:
            assert batch_id is not None
            download(store, batch_id, active["version"])
            store._db.execute(
                "INSERT INTO idempotency(key,payload_hash,batch_id,version,"
                "request_signature) VALUES(?,?,?,?,?)",
                (
                    idempotency_key,
                    payload_hash,
                    batch_id,
                    active["version"],
                    request_signature or "",
                ),
            )
            return _revision_result(store, active)
        revision = analysis.get("claim_revision")
        if (
            not isinstance(revision, int)
            or isinstance(revision, bool)
            or revision != store.claim_revision()
        ):
            raise AppError("availability_changed", "可用用量已变化，请更新预览后重试。", 409)
        _check_available(store, members, batch_id)
        capture = _validate_capture(store, analysis, members)
        old_version = None if active is None else active["version"]
        if batch_id is None:
            batch_id = str(uuid4())
            number = store._db.execute("SELECT COALESCE(MAX(number),0)+1 FROM batches").fetchone()[
                0
            ]
            store._db.execute(
                "INSERT INTO batches(id,number,created_at) VALUES(?,?,?)",
                (batch_id, number, store._now()),
            )
        else:
            number = store._db.execute(
                "SELECT number FROM batches WHERE id=?", (batch_id,)
            ).fetchone()[0]
        version = store._db.execute(
            "SELECT COALESCE(MAX(version),0)+1 FROM revisions WHERE batch_id=?", (batch_id,)
        ).fetchone()[0]
        now = store._now()
        batch_info = {
            "id": batch_id,
            "number": f"AHA-{number:06d}",
            "version": version,
            "created_at": now,
        }
        package, filename, _ = build_evidence(analysis, claim, batch_info, capture)
        zip_hash = hashlib.sha256(package).hexdigest()
        relative = f"packages/{batch_id}-v{version}-{zip_hash}.zip"
        store._write_immutable(relative, package)
        if hashlib.sha256(store._read_file(relative)).hexdigest() != zip_hash:
            raise AppError("package_damaged", "材料保存校验失败，请重试。", 500)
        frozen_hash = content_hash({"analysis": analysis, "claim": claim, "batch": batch_info})
        store._db.execute(
            "INSERT INTO revisions(batch_id,version,created_at,status,"
            "status_updated_at,analysis_json,claim_json,"
            "members_json,overlaps_json,zip_path,zip_hash,file_name,frozen_hash,claim_protocol) "
            "VALUES(?,?,?,'draft',?,?,?,?,?,?,?,?,?,2)",
            (
                batch_id,
                version,
                now,
                now,
                store._encode(analysis),
                store._encode(claim),
                store._encode(members),
                "[]",
                relative,
                zip_hash,
                filename,
                frozen_hash,
            ),
        )
        if control is None:
            store._db.execute(
                "INSERT INTO batch_control(batch_id,active_version,lifecycle,"
                "generation) VALUES(?,?,'active',1)",
                (batch_id, version),
            )
        else:
            store._db.execute(
                "UPDATE batch_control SET active_version=?,generation=generation+1 "
                "WHERE batch_id=?",
                (version, batch_id),
            )
            store._db.execute("DELETE FROM usage_claims WHERE batch_id=?", (batch_id,))
        add_members(store, batch_id, version, members)
        store._db.execute(
            "INSERT INTO status_events(batch_id,version,old_status,new_status,"
            "changed_at) VALUES(?,?,NULL,'draft',?)",
            (batch_id, version, now),
        )
        record_event(
            store,
            batch_id,
            version,
            "create" if control is None else "revise",
            "",
            old_version,
            version,
            None if active is None else active["status"],
            "draft",
        )
        store._db.execute(
            "INSERT INTO idempotency(key,payload_hash,batch_id,version,"
            "request_signature) VALUES(?,?,?,?,?)",
            (idempotency_key, payload_hash, batch_id, version, request_signature or ""),
        )
        _advance(store)
        return _revision_result(store, _revision(store, batch_id, version))


def list_batches(store: Store) -> list[dict[str, Any]]:
    with store._lock:
        store._ensure_open()
        return [
            _current_result(store, row[0])
            for row in store._db.execute("SELECT id FROM batches ORDER BY number DESC").fetchall()
        ]


def batch_detail(store: Store, batch_id: str) -> dict[str, Any]:
    with store._lock:
        store._ensure_open()
        result = _current_result(store, batch_id)
        rows = store._db.execute(
            "SELECT * FROM revisions WHERE batch_id=? ORDER BY version", (batch_id,)
        ).fetchall()
        result["latest_version"] = rows[-1]["version"]
        result["revisions"] = [_revision_result(store, row, include_analysis=True) for row in rows]
        result["status_history"] = [
            dict(row)
            for row in store._db.execute(
                "SELECT version,old_status,new_status,changed_at FROM status_events "
                "WHERE batch_id=? ORDER BY id",
                (batch_id,),
            )
        ]
        result["claim_history"] = [
            dict(row)
            for row in store._db.execute(
                "SELECT * FROM claim_events WHERE batch_id=? ORDER BY id", (batch_id,)
            )
        ]
        return result


def _change_status(store: Store, batch_id: str, version: int, status: str) -> None:
    row = _revision(store, batch_id, version)
    now = store._now()
    store._db.execute(
        "UPDATE revisions SET status=?,status_updated_at=?,"
        "write_generation=write_generation+1 WHERE batch_id=? AND version=?",
        (status, now, batch_id, version),
    )
    store._db.execute(
        "UPDATE batch_control SET generation=generation+1 WHERE batch_id=?", (batch_id,)
    )
    store._db.execute(
        "INSERT INTO status_events(batch_id,version,old_status,new_status,"
        "changed_at) VALUES(?,?,?,?,?)",
        (batch_id, version, row["status"], status, now),
    )


def set_status(
    store: Store, batch_id: str, version: int, status: str, expected_generation: int | None = None
) -> dict[str, Any]:
    if status not in STATUSES:
        raise AppError("invalid_status", "请选择有效的报销状态。")
    with store._transaction():
        control, row = _effective(store, batch_id, version)
        _check_generation(control, expected_generation)
        if row["status"] == status:
            return _revision_result(store, row)
        if not (
            (row["status"] == "draft" and status in {"submitted", "reimbursed"})
            or (row["status"] == "submitted" and status == "reimbursed")
        ):
            raise AppError("invalid_transition", "请使用撤回或作废操作更正这条记录。", 409)
        _change_status(store, batch_id, version, status)
        record_event(
            store, batch_id, version, "status", "", version, version, row["status"], status
        )
        _advance(store)
        return _revision_result(store, _revision(store, batch_id, version))


def lifecycle_action(
    store: Store,
    action: str,
    batch_id: str,
    expected_generation: int,
    reason: str,
    idempotency_key: str,
    selected_version: int | None = None,
) -> dict[str, Any]:
    _key(idempotency_key)
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 4000:
        raise AppError("reason_required", "请填写操作原因，最多4000字。")
    reason = reason.strip()
    payload_hash = content_hash(
        {
            "action": action,
            "batch_id": batch_id,
            "generation": expected_generation,
            "reason": reason,
            "selected_version": selected_version,
        }
    )
    with store._transaction():
        prior = store._db.execute(
            "SELECT * FROM action_idempotency WHERE key=?", (idempotency_key,)
        ).fetchone()
        if prior is not None:
            if prior["payload_hash"] != payload_hash:
                raise AppError("idempotency_conflict", "请求内容已变化，请重新发起操作。", 409)
            return _current_result(store, prior["batch_id"])
        if store._db.execute(
            "SELECT 1 FROM idempotency WHERE key=?", (idempotency_key,)
        ).fetchone():
            raise AppError("idempotency_conflict", "操作标识已用于其他操作，请重新发起。", 409)
        control = _control(store, batch_id)
        _check_generation(control, expected_generation)
        if control["lifecycle"] == "voided":
            raise AppError("batch_voided", "这条记录已作废。", 409)
        old_version = control["active_version"]
        old_status = (
            None if old_version is None else _revision(store, batch_id, old_version)["status"]
        )
        if action == "withdraw":
            _, row = _effective(store, batch_id)
            if row["status"] != "submitted":
                raise AppError("invalid_transition", "只有已提交的记录可以撤回。", 409)
            _change_status(store, batch_id, row["version"], "draft")
            record_event(
                store,
                batch_id,
                row["version"],
                action,
                reason,
                old_version,
                old_version,
                old_status,
                "draft",
            )
        elif action == "void":
            store._db.execute(
                "UPDATE batch_control SET lifecycle='voided',generation=generation+1,"
                "voided_at=?,void_reason=? WHERE batch_id=?",
                (store._now(), reason, batch_id),
            )
            store._db.execute("DELETE FROM usage_claims WHERE batch_id=?", (batch_id,))
            store._db.execute("DELETE FROM legacy_holds WHERE batch_id=?", (batch_id,))
            record_event(
                store,
                batch_id,
                old_version,
                action,
                reason,
                old_version,
                old_version,
                old_status,
                old_status,
            )
        elif action == "resolve":
            if (
                control["lifecycle"] != "legacy_review"
                or not isinstance(selected_version, int)
                or isinstance(selected_version, bool)
            ):
                raise AppError("invalid_transition", "请选择需要核对的旧版本。", 409)
            row = _revision(store, batch_id, selected_version)
            analysis = store._decode(row["analysis_json"])
            members = members_from_analysis(analysis)
            _check_available(store, members, batch_id)
            _validate_capture(store, analysis, members)
            download(store, batch_id, selected_version)
            add_members(store, batch_id, selected_version, members)
            store._db.execute("DELETE FROM legacy_holds WHERE batch_id=?", (batch_id,))
            store._db.execute(
                "UPDATE batch_control SET lifecycle='active',active_version=?,"
                "generation=generation+1 WHERE batch_id=?",
                (selected_version, batch_id),
            )
            record_event(
                store,
                batch_id,
                selected_version,
                action,
                reason,
                old_version,
                selected_version,
                old_status,
                row["status"],
            )
        else:
            raise AppError("invalid_action", "不支持此操作。")
        store._db.execute(
            "INSERT INTO action_idempotency(key,payload_hash,batch_id,operation) VALUES(?,?,?,?)",
            (idempotency_key, payload_hash, batch_id, action),
        )
        _advance(store)
        return _current_result(store, batch_id)


def download(store: Store, batch_id: str, version: int) -> tuple[bytes, str]:
    with store._lock:
        store._ensure_open()
        row = _revision(store, batch_id, version)
        data = store._read_file(row["zip_path"])
        if hashlib.sha256(data).hexdigest() != row["zip_hash"]:
            raise AppError("package_damaged", "材料校验失败，请保留资料目录。", 409)
        return data, row["file_name"]
