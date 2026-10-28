"""Project directory matching and fingerprint-bound manual assignments."""

from __future__ import annotations

import ntpath
import posixpath
import re
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from .domain import AppError, record_key, row_fingerprint

if TYPE_CHECKING:
    from .storage import Store


def canonical_path(path: str) -> str:
    """Normalize an absolute path using its own platform's path rules."""
    if not isinstance(path, str) or not path.strip() or len(path) > 8192 or "\0" in path:
        raise AppError("invalid_directory", "请填写有效的绝对目录。")
    path = path.strip()
    if path.startswith("\\\\?\\"):
        path = path[4:]
        if path[:4].lower() == "unc\\":
            path = "\\\\" + path[4:]
    windows = bool(re.match(r"^[A-Za-z]:[\\/]", path)) or path.startswith(("\\\\", "//"))
    if windows:
        normalized = ntpath.normpath(path).replace("\\", "/").casefold()
        if normalized.startswith("//") and len(normalized.strip("/").split("/")) < 2:
            raise AppError("invalid_directory", "Windows 网络目录需要服务器和共享名称。")
        return normalized.rstrip("/") if not re.fullmatch(r"[a-z]:/", normalized) else normalized
    if not path.startswith("/"):
        raise AppError("invalid_directory", "目录必须使用 Windows 或 Linux 绝对路径。")
    return posixpath.normpath(path)


def _contains(directory: str, candidate: str) -> bool:
    def windows(path: str) -> bool:
        return bool(re.match(r"^[a-z]:/", path)) or path.startswith("//")

    if windows(directory) != windows(candidate):
        return False
    return candidate == directory or candidate.startswith(directory.rstrip("/") + "/")


def classify(
    row: dict[str, Any], metadata: dict[str, Any], config: dict[str, Any], grain: str = "detail"
) -> dict[str, Any]:
    """Give each original row at most one project, without changing the row."""
    project_map = {p["id"]: p for p in config.get("projects", [])}
    override = config.get("overrides", {}).get(record_key(row, grain))
    cwd = None
    if grain == "detail":
        session = metadata.get("sessions", {}).get(str(row.get("session_id", "")), {})
        if session.get("status") == "matched" and isinstance(session.get("cwd"), str):
            cwd = session["cwd"]
    project_id = None
    origin = "unassigned"
    if (
        override
        and override.get("content_hash") == row_fingerprint(row, grain)
        and override.get("project_id") in project_map
    ):
        project_id, origin = override["project_id"], "manual"
    elif cwd:
        try:
            candidate = canonical_path(cwd)
        except AppError:
            candidate = None
        matches = []
        if candidate is not None:
            for project in project_map.values():
                for directory in project.get("directories", []):
                    normalized = canonical_path(directory)
                    if _contains(normalized, candidate):
                        matches.append((len(normalized), project["id"]))
        if matches:
            _, project_id = max(matches)
            origin = "directory_rule"
    return {
        "project_id": project_id,
        "project_name": project_map[project_id]["name"] if project_id else "未归属",
        "assignment_origin": origin,
        "cwd": cwd,
    }


def configuration(store: Store, connection: Any = None) -> dict[str, Any]:
    if connection is None:
        with store.read_connection() as reader:
            return configuration(store, reader)
    projects = [
        {
            "id": row["id"],
            "name": row["name"],
            "description": row["description"],
            "directories": store._decode(row["directories_json"]),
        }
        for row in connection.execute("SELECT * FROM projects ORDER BY name,id")
    ]
    return {
        "revision": store.revisions(connection)["classification_revision"],
        "projects": projects,
        "override_count": connection.execute("SELECT COUNT(*) FROM overrides").fetchone()[0],
    }


def save_project(
    store: Store, project_id: str | None, name: str, description: str, directories: list[str]
) -> dict[str, Any]:
    from . import ledger

    if not isinstance(name, str) or not name.strip() or len(name) > 160:
        raise AppError("invalid_project", "项目名称不能为空，且最多为 160 个字符。")
    if not isinstance(description, str) or len(description) > 4000:
        raise AppError("invalid_project", "项目说明最多为 4000 个字符。")
    if not isinstance(directories, list) or len(directories) > 200:
        raise AppError("invalid_directory", "每个项目最多绑定 200 个目录。")
    normalized = {canonical_path(directory): directory.strip() for directory in directories}
    with store._transaction():
        connection = store._db
        config = configuration(store, connection)
        existing = next((p for p in config["projects"] if p["id"] == project_id), None)
        if project_id is not None and existing is None:
            raise AppError("project_not_found", "项目不存在，请刷新。", 404)
        for project in config["projects"]:
            if project["id"] != project_id and any(
                canonical_path(d) in normalized for d in project["directories"]
            ):
                raise AppError("directory_conflict", "该目录已绑定其他项目。", 409)
        identity = project_id or str(uuid4())
        old_directories = existing["directories"] if existing else []
        scopes = _affected_directories(
            connection, [*old_directories, *normalized.values()], identity
        )
        saved = {
            "id": identity,
            "name": name.strip(),
            "description": description.strip(),
            "directories": list(normalized.values()),
        }
        connection.execute(
            (
                "INSERT INTO projects VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE S"
                "ET name=excluded.name,description=excluded.description,directori"
                "es_json=excluded.directories_json"
            ),
            (identity, saved["name"], saved["description"], store._encode(saved["directories"])),
        )
        store._advance_revision()
        ledger.reclassify(connection, scopes)
        ledger.refresh_availability(connection, scopes)
        return {**configuration(store, connection), "project": saved}


def _affected_directories(connection: Any, directories: list[str], project_id: str) -> set[str]:
    scopes = {
        r[0]
        for r in connection.execute(
            "SELECT DISTINCT scope_key FROM usage_records WHERE project_id=?", (project_id,)
        )
    }
    # Sessions are the smaller metadata domain; no full fact/override list is materialised.
    rules = [canonical_path(d) for d in directories]
    if rules:
        for session in connection.execute(
            "SELECT id,cwd FROM sessions WHERE status='matched' AND cwd IS NOT NULL"
        ):
            try:
                candidate = canonical_path(session["cwd"])
            except AppError:
                continue
            if any(_contains(rule, candidate) for rule in rules):
                scopes.update(
                    r[0]
                    for r in connection.execute(
                        "SELECT DISTINCT scope_key FROM usage_records WHERE session_id=?",
                        (session["id"],),
                    )
                )
    return scopes


def assign_keys(store: Store, keys: list[str], project_id: str | None) -> dict[str, Any]:
    from . import ledger

    if (
        not isinstance(keys, list)
        or not keys
        or len(keys) > 10000
        or not all(isinstance(key, str) for key in keys)
    ):
        raise AppError("invalid_assignment", "请选择有效用量，单次最多一万行。")
    with store._transaction():
        connection = store._db
        _validate_project(connection, project_id)
        scopes: set[str] = set()
        for key in dict.fromkeys(keys):
            row = connection.execute(
                "SELECT content_hash,scope_key FROM usage_records WHERE record_key=?", (key,)
            ).fetchone()
            if row is None:
                raise AppError("record_not_found", "所选用量不存在，请刷新。", 404)
            _override(connection, key, row["content_hash"], project_id)
            scopes.add(row["scope_key"])
        store._advance_revision()
        ledger.reclassify(connection, scopes)
        ledger.refresh_availability(connection, scopes)
        return configuration(store, connection)


def _validate_project(connection: Any, project_id: str | None) -> None:
    if (
        project_id is not None
        and connection.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone()
        is None
    ):
        raise AppError("project_not_found", "所选项目不存在。", 404)


def _override(connection: Any, key: str, fingerprint: str, project_id: str | None) -> None:
    if project_id is None:
        connection.execute("DELETE FROM overrides WHERE record_key=?", (key,))
    else:
        connection.execute(
            (
                "INSERT INTO overrides VALUES(?,?,?) ON CONFLICT(record_key) DO U"
                "PDATE SET content_hash=excluded.content_hash,project_id=excluded"
                ".project_id"
            ),
            (key, fingerprint, project_id),
        )


def assign_sessions(store: Store, session_ids: list[str], project_id: str | None) -> dict[str, Any]:
    from . import ledger

    if (
        not isinstance(session_ids, list)
        or not session_ids
        or len(session_ids) > 1000
        or not all(isinstance(s, str) for s in session_ids)
    ):
        raise AppError("invalid_assignment", "请选择有效会话。")
    with store._transaction():
        connection = store._db
        _validate_project(connection, project_id)
        scopes: set[str] = set()
        for session_id in dict.fromkeys(session_ids):
            cursor = connection.execute(
                "SELECT record_key,content_hash,scope_key FROM usage_records WHERE session_id=?",
                (session_id,),
            )
            while rows := cursor.fetchmany(512):
                for row in rows:
                    _override(connection, row["record_key"], row["content_hash"], project_id)
                    scopes.add(row["scope_key"])
        store._advance_revision()
        ledger.reclassify(connection, scopes)
        ledger.refresh_availability(connection, scopes)
        return configuration(store, connection)
