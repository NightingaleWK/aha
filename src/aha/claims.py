"""Canonical usage identities and one pure availability decision for every caller."""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from datetime import datetime
from typing import Any

from .domain import (
    BEIJING,
    AppError,
    content_hash,
    fresh_input,
    integer_value,
    parse_date,
    record_key,
    row_fingerprint,
)

TOKEN_FIELDS = (
    "fresh_input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_creation_tokens",
    "total_tokens",
)


def scope_key(member: dict[str, Any]) -> str:
    return content_hash(
        [member.get(key, "") for key in ("app_type", "data_source", "provider_id", "date", "model")]
    )


def semantic_key(member: dict[str, Any]) -> str | None:
    if member.get("kind") != "detail" or not member.get("session_id"):
        return None
    if member.get("created_at") is None:
        return None
    return content_hash(
        [
            member.get(key, "")
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
        ]
    )


def member_from_row(row: dict[str, Any], kind: str) -> dict[str, Any]:
    if kind not in {"detail", "rollup"}:
        raise AppError("invalid_analysis", "用量内容无效，请重新预览。")
    fresh = fresh_input(row)
    member = {
        "kind": kind,
        "key": record_key(row, kind),
        "content_hash": row_fingerprint(row, kind),
        "date": row["date"]
        if kind == "rollup"
        else datetime.fromtimestamp(integer_value(row["created_at"]), BEIJING).date().isoformat(),
        "model": row["model"],
        "app_type": row["app_type"],
        "data_source": row["data_source"] if kind == "detail" else "codex_session",
        "provider_id": row["provider_id"],
        "fresh_input_tokens": fresh,
        **{
            key: integer_value(row[key])
            for key in (
                "output_tokens",
                "cache_read_tokens",
                "cache_creation_tokens",
            )
        },
    }
    member["total_tokens"] = sum(member[key] for key in TOKEN_FIELDS[:-1])
    if kind == "detail":
        member.update(session_id=row.get("session_id"), created_at=integer_value(row["created_at"]))
        member["semantic_key"] = semantic_key(member)
    else:
        member.update(
            request_count=integer_value(row["request_count"]),
            request_model=row["request_model"],
            pricing_model=row["pricing_model"],
        )
    return member


def validate_members(value: Any) -> list[dict[str, Any]]:
    """Validate persisted members without trusting a stored semantic hash."""
    if not isinstance(value, list):
        raise AppError("invalid_analysis", "用量内容不完整，请重新预览。")
    keys: set[str] = set()
    result = []
    try:
        for original in value:
            if not isinstance(original, dict):
                raise ValueError
            member = dict(original)
            kind = member.get("kind")
            if kind not in {"detail", "rollup"}:
                raise ValueError
            for key in (
                "key",
                "content_hash",
                "date",
                "model",
                "app_type",
                "data_source",
                "provider_id",
            ):
                if not isinstance(member.get(key), str) or not member[key]:
                    raise ValueError
            if member["key"] in keys or not member["key"].startswith(kind + ":"):
                raise ValueError
            keys.add(member["key"])
            if member["app_type"] != "codex" or member["data_source"] != "codex_session":
                raise ValueError
            parse_date(member["date"])
            for key in TOKEN_FIELDS:
                member[key] = integer_value(
                    member[key], maximum=(2**63 - 1) * (4 if key == "total_tokens" else 1)
                )
            if member["total_tokens"] != sum(member[key] for key in TOKEN_FIELDS[:-1]):
                raise ValueError
            if kind == "detail":
                member["created_at"] = integer_value(member["created_at"])
                if (
                    datetime.fromtimestamp(member["created_at"], BEIJING).date().isoformat()
                    != member["date"]
                ):
                    raise ValueError
                if member.get("session_id") is not None and not isinstance(
                    member["session_id"], str
                ):
                    raise ValueError
                member["semantic_key"] = semantic_key(member)
            else:
                member["request_count"] = integer_value(member["request_count"])
            result.append(member)
    except (KeyError, TypeError, ValueError, OverflowError, OSError) as exc:
        raise AppError("invalid_analysis", "用量内容无效，请重新预览。") from exc
    return result


def members_from_analysis(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    """Ensure the claimed members describe the actual rows being exported."""
    try:
        result = [
            member_from_row(row, kind)
            for kind, field in (("detail", "details"), ("rollup", "rollups"))
            for row in analysis[field]
        ]
        result = validate_members(result)
        declared = validate_members(analysis["members"])
        by_key = {member["key"]: member for member in result}
        if set(by_key) != {member["key"] for member in declared}:
            raise ValueError
        for member in declared:
            expected = by_key[member["key"]]
            for key in expected:
                if member.get(key) != expected[key]:
                    raise ValueError
        return sorted(result, key=lambda member: (member["kind"], member["key"]))
    except (KeyError, TypeError, ValueError, OverflowError, OSError) as exc:
        raise AppError("invalid_analysis", "用量明细与预览不一致，请重新预览。") from exc


def evaluate(
    members: list[dict[str, Any]],
    snapshot: dict[str, Any],
    exclude_batch_id: str | None = None,
) -> dict[str, Any]:
    members = validate_members(members)
    candidate_scopes: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for member in members:
        candidate_scopes[scope_key(member)].append(member)
    internal: set[str] = set()
    for group in candidate_scopes.values():
        if any(member["kind"] == "rollup" for member in group) and len(group) > 1:
            internal.update(member["key"] for member in group)

    by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    rollup_scopes: dict[str, list[dict[str, Any]]] = defaultdict(list)
    detail_scopes: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_semantic: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in snapshot.get("claims", []):
        if entry["owner"]["batch_id"] == exclude_batch_id:
            continue
        saved = entry["member"]
        item = {"member": saved, "owner": entry["owner"]}
        by_key[saved["key"]].append(item)
        (rollup_scopes if saved["kind"] == "rollup" else detail_scopes)[scope_key(saved)].append(
            item
        )
        semantic = semantic_key(saved)
        if semantic:
            by_semantic[semantic].append(item)
    available: list[str] = []
    excluded: list[dict[str, Any]] = []
    for member in members:
        reasons: set[str] = set()
        owners: dict[tuple[str, int], dict[str, Any]] = {}
        if member["key"] in internal:
            reasons.add("internal_overlap")
        related: list[tuple[str, dict[str, Any]]] = [
            ("identity", item) for item in by_key.get(member["key"], [])
        ]
        related_scope = list(rollup_scopes.get(scope_key(member), []))
        if member["kind"] == "rollup":
            related_scope.extend(detail_scopes.get(scope_key(member), []))
        for item in related_scope:
            other = item["member"]
            if member["key"] == other["key"]:
                continue
            if member["kind"] == "rollup" or other["kind"] == "rollup":
                related.append(
                    (
                        "rollup_scope" if member["kind"] == other["kind"] else "cross_grain",
                        item,
                    )
                )
        semantic = semantic_key(member)
        if semantic:
            related.extend(
                ("suspected_rebuild", item)
                for item in by_semantic.get(semantic, [])
                if item["member"]["key"] != member["key"]
            )
        for reason, item in related:
            reasons.add(reason)
            owner = item["owner"]
            owners[(owner["batch_id"], owner["version"])] = dict(owner)
        if not reasons:
            available.append(member["key"])
        else:
            precedence = (
                "internal_overlap",
                "identity",
                "cross_grain",
                "rollup_scope",
                "suspected_rebuild",
            )
            excluded.append(
                {
                    "key": member["key"],
                    "reason": next(reason for reason in precedence if reason in reasons),
                    "reasons": sorted(reasons),
                    "owners": sorted(
                        owners.values(), key=lambda owner: (owner["number"], owner["version"])
                    ),
                }
            )
    return {
        "claim_revision": snapshot.get("claim_revision", 0),
        "available_keys": available,
        "excluded": excluded,
    }


def indexed_exclusion(
    connection: sqlite3.Connection,
    member: dict[str, Any],
    exclude_batch_id: str | None = None,
    *,
    owner_limit: int = 32,
) -> dict[str, Any] | None:
    """Explain one page member using only related key/scope/semantic index ranges."""
    member = validate_members([member])[0]
    limit = min(max(owner_limit, 1), 100)
    reasons: set[str] = set()
    owners: dict[tuple[str, int], dict[str, Any]] = {}
    truncated = False
    selections: list[tuple[str, tuple[Any, ...], str]] = [
        ("u.record_key=?", (member["key"],), "identity")
    ]
    if member["kind"] == "detail":
        selections.append(
            (
                "u.scope_key=? AND u.kind='rollup' AND u.record_key<>?",
                (scope_key(member), member["key"]),
                "cross_grain",
            )
        )
    else:
        selections.append(
            ("u.scope_key=? AND u.record_key<>?", (scope_key(member), member["key"]), "scope")
        )
    semantic = semantic_key(member)
    if semantic is not None:
        selections.append(
            ("u.semantic_key=? AND u.record_key<>?", (semantic, member["key"]), "suspected_rebuild")
        )
    for predicate, values, reason in selections:
        rows = connection.execute(
            "SELECT u.*,b.number,b.lifecycle,r.status FROM usage_claims u "
            "JOIN batches b ON b.id=u.batch_id JOIN revisions r "
            "ON r.batch_id=u.batch_id AND r.version=u.owner_version WHERE "
            + predicate
            + " AND (? IS NULL OR u.batch_id<>?) ORDER BY b.number,u.owner_version LIMIT ?",
            (*values, exclude_batch_id, exclude_batch_id, limit + 1),
        ).fetchall()
        truncated = truncated or len(rows) > limit
        for row in rows[:limit]:
            try:
                saved = validate_members([json.loads(row["member_json"])])[0]
                if saved["key"] != row["record_key"] or scope_key(saved) != row["scope_key"]:
                    raise ValueError
            except (ValueError, TypeError, AppError) as exc:
                raise AppError(
                    "storage_damaged", "占用资料校验失败，请保留本地资料。", 409
                ) from exc
            actual_reason = (
                ("rollup_scope" if row["kind"] == "rollup" else "cross_grain")
                if reason == "scope"
                else reason
            )
            reasons.add(actual_reason)
            owner = {
                "batch_id": row["batch_id"],
                "version": row["owner_version"],
                "number": f"AHA-{row['number']:06d}",
                "status": row["status"],
                "lifecycle": row["lifecycle"],
            }
            owners[(owner["batch_id"], owner["version"])] = owner
    if not reasons:
        return None
    precedence = ("identity", "cross_grain", "rollup_scope", "suspected_rebuild")
    return {
        "key": member["key"],
        "reason": next(item for item in precedence if item in reasons),
        "reasons": sorted(reasons),
        "owners": sorted(owners.values(), key=lambda item: (item["number"], item["version"])),
        "owners_truncated": truncated,
    }
