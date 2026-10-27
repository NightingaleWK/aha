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


def configuration(store: Store) -> dict[str, Any]:
    with store._lock:
        store._ensure_open()
        revision = int(
            store._db.execute("SELECT value FROM settings WHERE key='revision'").fetchone()[0]
        )
        projects = [
            {
                "id": row["id"],
                "name": row["name"],
                "description": row["description"],
                "directories": store._decode(row["directories_json"]),
            }
            for row in store._db.execute("SELECT * FROM projects ORDER BY name,id")
        ]
        overrides = {
            row["record_key"]: {
                "project_id": row["project_id"],
                "content_hash": row["content_hash"],
            }
            for row in store._db.execute("SELECT * FROM overrides ORDER BY record_key")
        }
        return {"revision": revision, "projects": projects, "overrides": overrides}


def save_project(
    store: Store, project_id: str | None, name: str, description: str, directories: list[str]
) -> dict[str, Any]:
    if not isinstance(name, str) or not name.strip() or len(name) > 160:
        raise AppError("invalid_project", "项目名称不能为空，且最多为 160 个字符。")
    if not isinstance(description, str) or len(description) > 4000:
        raise AppError("invalid_project", "项目说明最多为 4000 个字符。")
    if not isinstance(directories, list) or len(directories) > 200:
        raise AppError("invalid_directory", "每个项目最多绑定 200 个目录。")
    normalized: dict[str, str] = {}
    for directory in directories:
        normalized.setdefault(canonical_path(directory), directory.strip())
    with store._transaction():
        config = configuration(store)
        if project_id is not None and project_id not in {p["id"] for p in config["projects"]}:
            raise AppError("project_not_found", "项目不存在，请刷新项目列表。", 404)
        for existing in config["projects"]:
            if existing["id"] != project_id:
                if any(canonical_path(d) in normalized for d in existing["directories"]):
                    raise AppError(
                        "directory_conflict", "该目录已绑定其他项目，请先调整原绑定。", 409
                    )
        project_id = project_id or str(uuid4())
        saved = {
            "id": project_id,
            "name": name.strip(),
            "description": description.strip(),
            "directories": list(normalized.values()),
        }
        store._db.execute(
            "INSERT INTO projects(id,name,description,directories_json) VALUES(?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET name=excluded.name,description=excluded.description,"
            "directories_json=excluded.directories_json",
            (project_id, saved["name"], saved["description"], store._encode(saved["directories"])),
        )
        store._advance_revision()
        result = configuration(store)
        result["project"] = saved
        return result


def assign(
    store: Store, rows: list[dict[str, Any]], project_id: str | None, grain: str = "detail"
) -> dict[str, Any]:
    if grain not in {"detail", "rollup"} or not isinstance(rows, list):
        raise AppError("invalid_assignment", "请选择有效的明细或完整日汇总记录。")
    identities = [(record_key(row, grain), row_fingerprint(row, grain)) for row in rows]
    with store._transaction():
        config = configuration(store)
        if project_id is not None and project_id not in {p["id"] for p in config["projects"]}:
            raise AppError("project_not_found", "项目不存在，请刷新项目列表。", 404)
        for key, fingerprint in identities:
            if project_id is None:
                store._db.execute("DELETE FROM overrides WHERE record_key=?", (key,))
            else:
                store._db.execute(
                    "INSERT INTO overrides(record_key,content_hash,project_id) VALUES(?,?,?) "
                    "ON CONFLICT(record_key) DO UPDATE SET content_hash=excluded.content_hash,"
                    "project_id=excluded.project_id",
                    (key, fingerprint, project_id),
                )
        if identities:
            store._advance_revision()
        return configuration(store)
