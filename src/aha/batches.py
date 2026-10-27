"""Immutable claim revisions, manual states, idempotency and overlap reminders."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

from .domain import AppError, content_hash
from .evidence import build_evidence, validate_claim

if TYPE_CHECKING:
    import sqlite3

    from .storage import Store

STATUSES = {"draft": "草稿", "submitted": "已提交", "reimbursed": "已报销"}


def _analysis_hash(analysis: dict[str, Any]) -> str:
    # An in-memory preview handle is not part of the frozen business content.
    return content_hash({key: value for key, value in analysis.items() if key != "analysis_id"})


def _scope(member: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        str(member.get(key, ""))
        for key in ("app_type", "data_source", "provider_id", "date", "model")
    )


def _semantic(member: dict[str, Any]) -> tuple[str, ...] | None:
    if not member.get("session_id") or member.get("created_at") is None:
        return None
    return tuple(
        str(member.get(key, ""))
        for key in (
            "app_type",
            "data_source",
            "provider_id",
            "session_id",
            "created_at",
            "model",
            "fresh_input_tokens",
            "output_tokens",
            "cache_read_tokens",
            "cache_creation_tokens",
        )
    )


def overlaps(
    store: Store, analysis: dict[str, Any], exclude_batch_id: str | None = None
) -> list[dict[str, Any]]:
    details = {}
    detail_scopes = set()
    rollup_scopes = set()
    semantics: dict[tuple[str, ...], set[str]] = defaultdict(set)
    for member in analysis.get("members", []):
        if member["kind"] == "detail":
            details[member["key"]] = member
            detail_scopes.add(_scope(member))
            semantic = _semantic(member)
            if semantic:
                semantics[semantic].add(member["key"])
        else:
            rollup_scopes.add(_scope(member))
    results = []
    with store._lock:
        store._ensure_open()
        rows = store._db.execute(
            "SELECT r.*,b.number FROM revisions r JOIN batches b ON b.id=r.batch_id "
            "ORDER BY b.number,r.version"
        ).fetchall()
        for row in rows:
            if row["batch_id"] == exclude_batch_id:
                continue
            counts: dict[str, int] = defaultdict(int)
            ranges = set()
            for member in store._decode(row["members_json"]):
                scope = _scope(member)
                reasons = []
                if member["kind"] == "detail":
                    if member["key"] in details:
                        reasons.append("detail_identity")
                    if scope in rollup_scopes:
                        reasons.append("cross_grain")
                    semantic = _semantic(member)
                    if semantic and semantics.get(semantic, set()) - {member["key"]}:
                        reasons.append("suspected_rebuild")
                else:
                    if scope in rollup_scopes:
                        reasons.append("rollup_scope")
                    if scope in detail_scopes:
                        reasons.append("cross_grain")
                for reason in reasons:
                    counts[reason] += 1
                    ranges.add((scope[3], scope[4]))
            if not counts:
                continue
            number = f"AHA-{row['number']:06d}"
            certain = counts.get("detail_identity", 0)
            possible = sum(count for kind, count in counts.items() if kind != "detail_identity")
            parts = []
            if certain:
                parts.append(f"{certain} 条来源请求身份相同")
            if "cross_grain" in counts or "rollup_scope" in counts:
                parts.append("历史汇总覆盖范围可能重叠")
            if "suspected_rebuild" in counts:
                parts.append("不同请求键的会话与 Token 特征相同，疑似重建记录")
            results.append(
                {
                    "batch_id": row["batch_id"],
                    "number": number,
                    "batch_number": number,
                    "version": row["version"],
                    "status": row["status"],
                    "types": sorted(counts),
                    "certain_count": certain,
                    "possible_count": possible,
                    "ranges": [{"date": date, "model": model} for date, model in sorted(ranges)],
                    "message": f"{number} v{row['version']}（{STATUSES[row['status']]}）："
                    + "；".join(parts)
                    + "。可核对后继续，金额未自动扣减。",
                }
            )
    return results


def _revision(store: Store, batch_id: str, version: int) -> sqlite3.Row:
    row = store._db.execute(
        "SELECT * FROM revisions WHERE batch_id=? AND version=?", (batch_id, version)
    ).fetchone()
    if row is None:
        raise AppError("revision_not_found", "该批次版本不存在，请刷新报销记录。", 404)
    return cast("sqlite3.Row", row)


def _revision_result(
    store: Store, row: sqlite3.Row, *, include_analysis: bool = False
) -> dict[str, Any]:
    batch = store._db.execute("SELECT * FROM batches WHERE id=?", (row["batch_id"],)).fetchone()
    analysis = store._decode(row["analysis_json"])
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
    }
    if include_analysis:
        result["analysis"] = analysis
    return result


def _validate_analysis(analysis: dict[str, Any]) -> None:
    if not isinstance(analysis, dict):
        raise AppError("invalid_analysis", "请先完成用量预览。")
    if not all(
        isinstance(analysis.get(key), list)
        for key in ("details", "rollups", "daily", "models", "members")
    ):
        raise AppError("invalid_analysis", "分析内容不完整，请重新预览。")
    if (
        not isinstance(analysis.get("summary"), dict)
        or not all(
            isinstance(analysis.get(key), str) for key in ("capture_id", "start_date", "end_date")
        )
        or not isinstance(analysis.get("classification_revision"), int)
    ):
        raise AppError("invalid_analysis", "分析身份无效，请重新预览。")


def create_batch(
    store: Store,
    analysis: dict[str, Any],
    claim: dict[str, Any],
    idempotency_key: str,
    batch_id: str | None = None,
) -> dict[str, Any]:
    _validate_analysis(analysis)
    claim = validate_claim(claim)
    if (
        not isinstance(idempotency_key, str)
        or not idempotency_key.strip()
        or len(idempotency_key) > 200
    ):
        raise AppError("invalid_idempotency_key", "创建材料需要有效的重试标识。")
    # Copy before locking so callers cannot later mutate the frozen result by reference.
    analysis = store._decode(store._encode(analysis))
    payload_hash = content_hash(
        {"analysis_hash": _analysis_hash(analysis), "claim": claim, "batch_id": batch_id}
    )
    with store._transaction():
        prior = store._db.execute(
            "SELECT * FROM idempotency WHERE key=?", (idempotency_key,)
        ).fetchone()
        if prior is not None:
            if prior["payload_hash"] != payload_hash:
                raise AppError(
                    "idempotency_conflict", "同一重试标识对应了不同内容，请重新发起操作。", 409
                )
            row = _revision(store, prior["batch_id"], prior["version"])
            download(store, prior["batch_id"], prior["version"])
            return _revision_result(store, row)
        batch = None
        if batch_id is not None:
            batch = store._db.execute("SELECT * FROM batches WHERE id=?", (batch_id,)).fetchone()
            if batch is None:
                raise AppError("batch_not_found", "该报销批次不存在。", 404)
        current_revision = store.config()["revision"]
        if analysis["classification_revision"] != current_revision:
            old_analyses = (
                []
                if batch_id is None
                else store._db.execute(
                    "SELECT analysis_json FROM revisions WHERE batch_id=?", (batch_id,)
                ).fetchall()
            )
            if not any(
                _analysis_hash(store._decode(row[0])) == _analysis_hash(analysis)
                for row in old_analyses
            ):
                raise AppError("stale_analysis", "项目归属已变化，请重新预览后创建材料。", 409)
        if batch_id is not None:
            latest = store._db.execute(
                "SELECT * FROM revisions WHERE batch_id=? ORDER BY version DESC LIMIT 1",
                (batch_id,),
            ).fetchone()
            if (
                latest is not None
                and _analysis_hash(store._decode(latest["analysis_json"]))
                == _analysis_hash(analysis)
                and store._decode(latest["claim_json"]) == claim
            ):
                download(store, batch_id, latest["version"])
                store._db.execute(
                    "INSERT INTO idempotency(key,payload_hash,batch_id,version) VALUES(?,?,?,?)",
                    (idempotency_key, payload_hash, batch_id, latest["version"]),
                )
                return _revision_result(store, latest)
        capture = store.get_capture(analysis["capture_id"])
        if batch is None:
            batch_id = str(uuid4())
            number = store._db.execute("SELECT COALESCE(MAX(number),0)+1 FROM batches").fetchone()[
                0
            ]
            store._db.execute(
                "INSERT INTO batches(id,number,created_at) VALUES(?,?,?)",
                (batch_id, number, store._now()),
            )
        else:
            number = batch["number"]
        version = store._db.execute(
            "SELECT COALESCE(MAX(version),0)+1 FROM revisions WHERE batch_id=?", (batch_id,)
        ).fetchone()[0]
        created_at = store._now()
        batch_info = {
            "id": batch_id,
            "number": f"AHA-{number:06d}",
            "version": version,
            "created_at": created_at,
        }
        warnings = overlaps(store, analysis, exclude_batch_id=batch_id)
        package, filename, _ = build_evidence(analysis, claim, batch_info, capture)
        zip_hash = hashlib.sha256(package).hexdigest()
        relative = f"packages/{batch_id}-v{version}-{zip_hash}.zip"
        store._write_immutable(relative, package)
        if hashlib.sha256(store._read_file(relative)).hexdigest() != zip_hash:
            raise AppError("package_damaged", "材料保存后的校验失败，未创建成功版本。", 500)
        frozen_hash = content_hash({"analysis": analysis, "claim": claim, "batch": batch_info})
        store._db.execute(
            "INSERT INTO revisions(batch_id,version,created_at,status,status_updated_at,"
            "analysis_json,claim_json,members_json,overlaps_json,zip_path,zip_hash,file_name,"
            "frozen_hash) VALUES(?,?,?,'draft',?,?,?,?,?,?,?,?,?)",
            (
                batch_id,
                version,
                created_at,
                created_at,
                store._encode(analysis),
                store._encode(claim),
                store._encode(analysis["members"]),
                store._encode(warnings),
                relative,
                zip_hash,
                filename,
                frozen_hash,
            ),
        )
        store._db.execute(
            "INSERT INTO status_events(batch_id,version,old_status,new_status,changed_at) "
            "VALUES(?,?,NULL,'draft',?)",
            (batch_id, version, created_at),
        )
        store._db.execute(
            "INSERT INTO idempotency(key,payload_hash,batch_id,version) VALUES(?,?,?,?)",
            (idempotency_key, payload_hash, batch_id, version),
        )
        return _revision_result(store, _revision(store, str(batch_id), version))


def list_batches(store: Store) -> list[dict[str, Any]]:
    with store._lock:
        store._ensure_open()
        rows = store._db.execute(
            "SELECT r.* FROM revisions r JOIN batches b ON b.id=r.batch_id "
            "WHERE r.version=(SELECT MAX(rr.version) FROM revisions rr "
            "WHERE rr.batch_id=r.batch_id) ORDER BY b.number DESC"
        ).fetchall()
        results = []
        for row in rows:
            result = _revision_result(store, row)
            result["latest_version"] = row["version"]
            results.append(result)
        return results


def batch_detail(store: Store, batch_id: str) -> dict[str, Any]:
    with store._lock:
        store._ensure_open()
        rows = store._db.execute(
            "SELECT * FROM revisions WHERE batch_id=? ORDER BY version", (batch_id,)
        ).fetchall()
        if not rows:
            raise AppError("batch_not_found", "该报销批次不存在。", 404)
        result = _revision_result(store, rows[-1])
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
        return result


def set_status(store: Store, batch_id: str, version: int, status: str) -> dict[str, Any]:
    if status not in STATUSES:
        raise AppError("invalid_status", "请选择草稿、已提交或已报销。")
    with store._transaction():
        row = _revision(store, batch_id, version)
        if row["status"] != status:
            changed_at = store._now()
            store._db.execute(
                "UPDATE revisions SET status=?,status_updated_at=? WHERE batch_id=? AND version=?",
                (status, changed_at, batch_id, version),
            )
            store._db.execute(
                "INSERT INTO status_events(batch_id,version,old_status,new_status,changed_at) "
                "VALUES(?,?,?,?,?)",
                (batch_id, version, row["status"], status, changed_at),
            )
        return _revision_result(store, _revision(store, batch_id, version))


def download(store: Store, batch_id: str, version: int) -> tuple[bytes, str]:
    with store._lock:
        store._ensure_open()
        row = _revision(store, batch_id, version)
        data = store._read_file(row["zip_path"])
        if hashlib.sha256(data).hexdigest() != row["zip_hash"]:
            raise AppError(
                "package_damaged",
                "原证据包校验失败，无法下载；请保留原资料并创建明确的新版本。",
                409,
            )
        return data, row["file_name"]
