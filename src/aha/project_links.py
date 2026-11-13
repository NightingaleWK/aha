"""Durable accepted project links; directory observations are only evidence."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

from .domain import AppError, canonical_bytes
from .projects import _contains, canonical_path

POLICY_KEY = "directory_assignment_policy"


def managed_projects(connection: sqlite3.Connection) -> set[str]:
    """Only explicitly confirmed projects adopt directory-wide authority."""
    row = connection.execute("SELECT value FROM settings WHERE key=?", (POLICY_KEY,)).fetchone()
    if row is None:
        return set()
    try:
        value = json.loads(row[0])
        if (not isinstance(value, dict) or set(value) != {"version", "projects"}
                or type(value["version"]) is not int or value["version"] != 1
                or not isinstance(value["projects"], list)
                or any(not isinstance(item, str) or not item for item in value["projects"])):
            raise ValueError
        result = set(value["projects"])
        existing = {r[0] for r in connection.execute("SELECT id FROM projects")}
        if result - existing:
            raise ValueError
        return result
    except (ValueError, TypeError, KeyError):
        raise AppError(
            "invalid_directory_policy", "目录关联设置无法识别，请使用完整备份核对资料。", 409
        ) from None


def directory_rules(connection: sqlite3.Connection) -> list[tuple[int, str, str]]:
    rules = []
    for project in connection.execute("SELECT id,directories_json FROM projects"):
        for raw in json.loads(project["directories_json"]):
            directory = canonical_path(raw)
            rules.append((len(directory), directory, project["id"]))
    return sorted(rules, reverse=True)


def match_directory(cwd: str | None, rules: list[tuple[int, str, str]]) -> str | None:
    from .domain import AppError

    if not cwd:
        return None
    try:
        candidate = canonical_path(cwd)
    except AppError:
        return None
    return next(
        (project for _, directory, project in rules if _contains(directory, candidate)), None
    )


def choose_project(
    cwd: str | None,
    rules: list[tuple[int, str, str]],
    *,
    fingerprint: str,
    manual: tuple[str, str] | None = None,
    retained: tuple[str | None, str] | None = None,
    session: tuple[str, str] | None = None,
    managed: set[str] | None = None,
) -> tuple[str | None, str]:
    """Single precedence contract for pure classification and indexed projection refreshes."""
    authoritative = match_directory(cwd, [r for r in rules if r[2] in (managed or set())])
    if authoritative:
        return authoritative, "directory_binding"
    if manual and manual[1] == fingerprint:
        return manual[0], "manual"
    if retained is not None:
        project, basis = retained
        return project, (
            "session_binding"
            if project and basis == "session_binding"
            else "identity_confirmation"
            if project and basis == "identity_confirmation"
            else "directory_rule"
            if project
            else "unassigned"
        )
    if session and session[0] not in (managed or set()):
        return session[0], "directory_rule" if session[1] == "directory_rule" else "session_binding"
    project = match_directory(cwd, rules)
    return project, "directory_rule" if project else "unassigned"


def link_record(
    connection: sqlite3.Connection,
    key: str,
    project: str | None,
    basis: str,
    evidence: dict[str, Any],
    *,
    operation: str,
    reason: str,
    now: str | None = None,
    replace_basis: bool = False,
    force: bool = False,
) -> bool:
    old = connection.execute(
        "SELECT project_id,basis FROM record_project_links WHERE record_key=?", (key,)
    ).fetchone()
    if old and old[0] == project and (not replace_basis or old[1] == basis) and not force:
        return False
    previous = connection.execute(
        "SELECT project_id,session_id FROM usage_records WHERE record_key=?", (key,)
    ).fetchone()
    timestamp = now or datetime.now(UTC).isoformat(timespec="microseconds")
    connection.execute(
        """INSERT INTO record_project_links(record_key,project_id,basis,basis_json,
        created_at,updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(record_key) DO UPDATE SET
        project_id=excluded.project_id,basis=excluded.basis,basis_json=excluded.basis_json,
        generation=record_project_links.generation+1,updated_at=excluded.updated_at""",
        (key, project, basis, canonical_bytes(evidence).decode(), timestamp, timestamp),
    )
    connection.execute(
        """INSERT INTO project_assignment_events(operation_id,record_key,session_id,
        old_project_id,project_id,basis,reason,created_at) VALUES(?,?,?,?,?,?,?,?)""",
        (
            operation,
            key,
            previous["session_id"],
            previous["project_id"] or None,
            project,
            basis,
            reason,
            timestamp,
        ),
    )
    return True


def bind_session(
    connection: sqlite3.Connection,
    session_id: str,
    project: str,
    basis: str,
    evidence: dict[str, Any],
    *,
    replace: bool = False,
    now: str | None = None,
) -> None:
    timestamp = now or datetime.now(UTC).isoformat(timespec="microseconds")
    suffix = (
        "DO UPDATE SET project_id=excluded.project_id,basis=excluded.basis,"
        "basis_json=excluded.basis_json,generation=session_project_bindings.generation+1,"
        "updated_at=excluded.updated_at"
        if replace
        else "DO NOTHING"
    )
    connection.execute(
        "INSERT INTO session_project_bindings(session_id,project_id,basis,basis_json,"
        "created_at,updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(session_id) " + suffix,
        (session_id, project, basis, canonical_bytes(evidence).decode(), timestamp, timestamp),
    )


def forget_directory_links(connection: sqlite3.Connection, session_id: str) -> None:
    """An explicit accepted contrary directory can revisit automatic links, never exceptions."""
    connection.execute(
        "DELETE FROM record_project_links WHERE basis IN ('directory_rule','history_restore') "
        "AND record_key IN (SELECT record_key FROM usage_records WHERE session_id=?)",
        (session_id,),
    )
    connection.execute(
        "DELETE FROM session_project_bindings WHERE session_id=? AND basis='directory_rule'",
        (session_id,),
    )


def require_directory_target(
    connection: sqlite3.Connection, session_id: str | None, target: str | None
) -> None:
    """Legacy actions may not create exceptions within an authoritative directory."""
    if not session_id:
        return
    row = connection.execute("SELECT cwd,status FROM sessions WHERE id=?", (session_id,)).fetchone()
    if row is None or row["status"] != "matched":
        return
    managed = managed_projects(connection)
    owner = match_directory(row["cwd"], [r for r in directory_rules(connection) if r[2] in managed])
    if owner and target != owner:
        raise AppError(
            "directory_assignment_required",
            "这个目录的记录整体归属同一项目，请在项目管理中调整目录。", 409,
        )
