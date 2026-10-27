"""Local HTTP boundary. All usage arithmetic stays in the analysis layer."""

from __future__ import annotations

import base64
import binascii
import copy
import json
import re
import secrets
import threading
from collections import Counter, OrderedDict
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PureWindowsPath
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlsplit

from . import __version__, analysis, session_meta, sources, sql_dump
from .domain import AppError, content_hash, record_key
from .storage import Store

SQL_LIMIT = 128 * 1024 * 1024
JSON_LIMIT = 2 * 1024 * 1024
UPLOAD_LIMIT = ((SQL_LIMIT + 2) // 3) * 4 + JSON_LIMIT
BEIJING = timezone(timedelta(hours=8))
SAFE_ID = r"([A-Za-z0-9_-]{1,128})"
WEB_DIR = Path(__file__).with_name("web")
ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/mark.svg": ("mark.svg", "image/svg+xml"),
}


def _equal(value: str, expected: str) -> bool:
    return secrets.compare_digest(value.encode("utf-8"), expected.encode("utf-8"))


def _string(body: dict[str, Any], key: str, default: str = "", limit: int = 4096) -> str:
    value = body.get(key, default)
    if not isinstance(value, str) or len(value) > limit or "\x00" in value:
        raise AppError("invalid_field", "表单内容不完整或格式不正确，请检查后重试。")
    return value.strip()


def _strings(body: dict[str, Any], key: str, maximum: int = 1000) -> list[str]:
    value = body.get(key, [])
    if not isinstance(value, list) or len(value) > maximum:
        raise AppError("invalid_field", "所选内容格式不正确，请重新选择。")
    if any(not isinstance(item, str) or len(item) > 4096 or "\x00" in item for item in value):
        raise AppError("invalid_field", "所选内容包含无效项，请重新选择。")
    return [item.strip() for item in value if item.strip()]


def _project_id(body: dict[str, Any]) -> str | None:
    value = body.get("project_id")
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(SAFE_ID, value):
        raise AppError("invalid_project", "请选择有效项目。")
    return value


def _version(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise AppError("invalid_version", "版本号不正确。")
    return value


def _generation(body: dict[str, Any]) -> int:
    value = body.get("expected_generation")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AppError("invalid_generation", "记录信息不完整，请刷新后重试。")
    return value


def _retry_key(body: dict[str, Any]) -> str:
    key = _string(body, "idempotency_key", limit=128)
    if len(key) < 16:
        raise AppError("idempotency_required", "操作信息不完整，请刷新后重试。")
    return key


def default_sqlite_path() -> Path:
    return Path.home() / ".cc-switch" / "cc-switch.db"


class Application:
    """Owns per-launch state; Store owns all persistent state and transactions."""

    def __init__(self, data_dir: Path) -> None:
        self.store = Store(data_dir)
        self.lock = threading.RLock()
        self.bootstrap_token = secrets.token_urlsafe(32)
        self.session_token = secrets.token_urlsafe(32)
        self.csrf_token = secrets.token_urlsafe(32)
        self.metadata_roots = [Path.home() / ".codex"]
        self.current_capture_id: str | None = None
        self.analyses: OrderedDict[str, tuple[int, dict[str, Any]]] = OrderedDict()
        self.generation = 0

    def close(self) -> None:
        self.analyses.clear()
        self.store.close()

    def invalidate(self) -> None:
        self.generation += 1
        self.analyses.clear()

    def status(self) -> dict[str, Any]:
        return {
            "version": __version__,
            "today": datetime.now(BEIJING).date().isoformat(),
            "timezone": "Asia/Shanghai",
            "csrf_token": self.csrf_token,
            "default_source": {
                "name": "cc-switch.db",
                "available": default_sqlite_path().is_file(),
            },
            "current_capture_id": self.current_capture_id,
            "sql_limit_bytes": SQL_LIMIT,
        }

    def capture_info(self, capture_id: str) -> dict[str, Any]:
        capture = self.store.get_capture(capture_id)
        info = {key: value for key, value in capture.items() if key not in {"data", "metadata"}}
        metadata = capture["metadata"]
        data = capture["data"]
        sessions = metadata.get("sessions", {})
        records = Counter(str(row.get("session_id", "")) for row in data["details"])
        directories: dict[str, dict[str, Any]] = {}
        missing = []
        for session_id, session in sessions.items():
            cwd = session.get("cwd")
            if cwd and session.get("status") == "matched":
                entry = directories.setdefault(
                    cwd, {"path": cwd, "session_count": 0, "detail_count": 0}
                )
                entry["session_count"] += 1
                entry["detail_count"] += records[session_id]
            else:
                missing.append(
                    {
                        "session_id": session_id,
                        "status": session.get("status", "missing"),
                        "detail_count": records[session_id],
                    }
                )
        info["directories"] = sorted(
            directories.values(), key=lambda entry: entry["path"].casefold()
        )
        errors = metadata.get("errors", [])
        error_count = (
            sum(item.get("count", 0) for item in errors) if isinstance(errors, list) else 0
        )
        info["metadata_coverage"] = {
            "matched_sessions": metadata.get("matched_sessions", 0),
            "total_sessions": metadata.get("total_sessions", len(records)),
            "error_count": error_count,
        }
        info["unresolved_sessions"] = missing
        return info

    def _retain_source(self, data: dict[str, Any]) -> dict[str, Any]:
        session_ids = {str(row["session_id"]) for row in data["details"] if row.get("session_id")}
        metadata = session_meta.scan_metadata(session_ids, self.metadata_roots)
        capture = self.store.retain(data, metadata)
        self.current_capture_id = capture["id"]
        return self.capture_info(capture["id"])

    def _analysis(
        self, analysis_id: str, *, check_availability: bool = True
    ) -> dict[str, Any]:
        entry = self.analyses.get(analysis_id)
        if entry is None or entry[0] != self.generation:
            raise AppError("analysis_expired", "预览已过期，请更新预览后保存。", 409)
        result = entry[1]
        if result["classification_revision"] != self.store.config()["revision"]:
            self.invalidate()
            raise AppError("analysis_expired", "项目归属已变化，请更新预览后保存。", 409)
        if check_availability:
            if result["claim_revision"] != self.store.claim_revision():
                raise AppError(
                    "availability_changed", "可用用量已变化，请更新预览后重试。", 409
                )
            if target := result.get("target_batch_id"):
                batch = self.store.batch_detail(target)
                if (
                    not batch["can_edit"]
                    or batch["generation"] != result["expected_generation"]
                    or batch["active_version"] != result["expected_active_version"]
                ):
                    raise AppError("stale_batch", "报销记录已变化，请刷新后重试。", 409)
        return result

    def _editable_batch(self, body: dict[str, Any], batch_id: str) -> dict[str, Any]:
        generation = _generation(body)
        version = _version(body.get("base_version"))
        batch = self.store.batch_detail(batch_id)
        if batch["lifecycle"] == "voided":
            raise AppError("batch_voided", "这条报销记录已作废，请新建记录。", 409)
        if not batch["can_edit"]:
            raise AppError("inactive_revision", "当前记录不能修改，请先核对报销状态。", 409)
        if batch["generation"] != generation or batch["active_version"] != version:
            raise AppError("stale_batch", "报销记录已变化，请刷新后重试。", 409)
        return batch

    def _batch_analysis(
        self, body: dict[str, Any], batch_id: str | None, *, for_save: bool = False
    ) -> dict[str, Any]:
        if body.get("analysis_id"):
            result = self._analysis(
                _string(body, "analysis_id", limit=128), check_availability=not for_save
            )
            if result["target_batch_id"] != batch_id:
                raise AppError("analysis_target_mismatch", "请为这条报销记录重新预览用量。", 409)
            if batch_id is not None:
                if (
                    result["expected_generation"] != _generation(body)
                    or result["expected_active_version"] != _version(body.get("base_version"))
                ):
                    raise AppError("stale_batch", "报销记录已变化，请刷新后重试。", 409)
            return result
        if batch_id is None:
            raise AppError("analysis_required", "请先更新用量预览。")
        batch = self._editable_batch(body, batch_id)
        current = next(
            item for item in batch["revisions"] if item["version"] == batch["active_version"]
        )
        result = copy.deepcopy(current["analysis"])
        result.update({
            "claim_revision": self.store.claim_revision(),
            "availability_mode": "available",
            "target_batch_id": batch_id,
            "expected_generation": batch["generation"],
            "expected_active_version": batch["active_version"],
        })
        result["availability"] = {
            "mode": "available",
            "claim_revision": result["claim_revision"],
            "matched_summary": copy.deepcopy(result["summary"]),
            "available_summary": copy.deepcopy(result["summary"]),
            "excluded_summary": analysis.empty_summary(),
            "excluded_groups": [],
        }
        return result

    def _new_analysis(self, body: dict[str, Any], batch_id: str | None = None) -> Any:
        if batch_id is None and any(
            key in body for key in ("target_batch_id", "exclude_batch_id", "batch_id")
        ):
            raise AppError("invalid_analysis_target", "请通过报销记录选择要修改的用量。")
        batch = self._editable_batch(body, batch_id) if batch_id is not None else None
        mode = _string(body, "availability_mode", "available", 16)
        if batch_id is not None and mode != "available":
            raise AppError("read_only_analysis", "修改报销记录时请选择可用用量。")
        capture_id = _string(body, "capture_id", limit=128)
        capture = self.store.get_capture(capture_id)
        config = self.store.config()
        revision = body.get("classification_revision", config["revision"])
        if isinstance(revision, bool) or not isinstance(revision, int):
            raise AppError("classification_changed", "项目归属已变化，请更新预览。", 409)
        if revision != config["revision"]:
            raise AppError("classification_changed", "项目归属已变化，请更新预览。", 409)
        result = analysis.analyze(
            capture["data"], capture["metadata"], config,
            _string(body, "start_date", limit=10),
            _string(body, "end_date", limit=10),
            _string(body, "project_id", "all", 128),
            claim_snapshot=self.store.claim_snapshot(batch_id),
            availability_mode=mode,
            target_batch_id=batch_id,
            expected_generation=batch["generation"] if batch else None,
            expected_active_version=batch["active_version"] if batch else None,
        )
        result["capture_id"] = capture_id
        result["source"] = capture["source"]
        for key in (
            "usage_snapshot_id", "metadata_snapshot_id", "created_at", "counts", "coverage"
        ):
            if key in capture:
                result[key] = capture[key]
        analysis_id = secrets.token_urlsafe(24)
        result["analysis_id"] = analysis_id
        result["metadata_coverage"] = self.capture_info(capture_id)["metadata_coverage"]
        result["unassigned_count"] = result["unassigned_record_count"]
        self.analyses[analysis_id] = (self.generation, result)
        while len(self.analyses) > 24:
            self.analyses.popitem(last=False)
        return {
            key: value for key, value in result.items()
            if key not in {"details", "rollups", "members"}
        }

    def _claim(self, body: dict[str, Any]) -> dict[str, Any]:
        claim = body.get("claim", {})
        if not isinstance(claim, dict):
            raise AppError("invalid_claim", "申请说明格式不正确。")
        amount = claim.get("amount")
        if amount is not None and (not isinstance(amount, str) or len(amount) > 128):
            raise AppError("invalid_amount", "申请金额格式不正确。")
        return {
            "purpose": _string(claim, "purpose", limit=4000),
            "amount": amount,
            "currency": _string(claim, "currency", "CNY", 3),
            "amount_note": _string(claim, "amount_note", limit=4000),
        }

    def get(self, path: str, query: dict[str, list[str]]) -> Any:
        if path == "/api/status":
            return self.status()
        if path == "/api/captures":
            return {"captures": self.store.list_captures()}
        if match := re.fullmatch(r"/api/captures/" + SAFE_ID, path):
            return self.capture_info(match[1])
        if path == "/api/projects":
            return self.store.config()
        if path == "/api/batches":
            return {"batches": self.store.list_batches()}
        if match := re.fullmatch(r"/api/batches/" + SAFE_ID, path):
            return self.store.batch_detail(match[1])
        if match := re.fullmatch(r"/api/analysis/" + SAFE_ID + r"/details", path):
            result = self._analysis(match[1])
            kind = query.get("kind", ["detail"])[0]
            if kind not in {"detail", "rollup"}:
                raise AppError("invalid_grain", "请选择明细或历史日汇总。")
            try:
                page = int(query.get("page", ["1"])[0])
                size = int(query.get("size", ["50"])[0])
            except ValueError:
                raise AppError("invalid_page", "分页参数不正确。") from None
            if page < 1 or size < 1 or size > 200:
                raise AppError("invalid_page", "每页可查看 1 至 200 条记录。")
            rows = result["details" if kind == "detail" else "rollups"]
            start = (page - 1) * size
            return {
                "rows": rows[start : start + size],
                "total": len(rows),
                "page": page,
                "size": size,
                "kind": kind,
            }
        raise AppError("not_found", "未找到此内容。", 404)

    def post(self, path: str, body: dict[str, Any]) -> Any:
        if path in {"/api/source/sqlite", "/api/source/sql"}:
            self.invalidate()
            self.current_capture_id = None
            if path.endswith("sqlite"):
                file_path = _string(body, "path")
                data = sources.load_sqlite(Path(file_path) if file_path else default_sqlite_path())
            else:
                encoded = _string(body, "content_base64", limit=UPLOAD_LIMIT)
                if len(encoded) > ((SQL_LIMIT + 2) // 3) * 4:
                    raise AppError("file_too_large", "SQL 文件不能超过 128 MiB。", 413)
                try:
                    raw = base64.b64decode(encoded, validate=True)
                except (ValueError, binascii.Error):
                    raise AppError(
                        "invalid_upload", "文件读取失败，请重新选择 SQL 备份。"
                    ) from None
                if len(raw) > SQL_LIMIT:
                    raise AppError("file_too_large", "SQL 文件不能超过 128 MiB。", 413)
                name = PureWindowsPath(_string(body, "name", "backup.sql", 255)).name
                data = sql_dump.load_sql_dump(raw, name)
            return self._retain_source(data)
        if path == "/api/session-metadata":
            self.invalidate()
            capture_id = _string(body, "capture_id", self.current_capture_id or "", 128)
            capture = self.store.get_capture(capture_id)
            if "roots" in body:
                roots = _strings(body, "roots", 32)
                self.metadata_roots = [Path(root).expanduser() for root in roots] or [
                    Path.home() / ".codex"
                ]
            return self._retain_source(capture["data"])
        if path == "/api/projects" or re.fullmatch(r"/api/projects/" + SAFE_ID, path):
            project_id = None if path == "/api/projects" else path.rsplit("/", 1)[1]
            result = self.store.save_project(
                project_id,
                _string(body, "name", limit=160),
                _string(body, "description", limit=4000),
                _strings(body, "directories", 500),
            )
            self.invalidate()
            return result
        if path == "/api/assignments":
            capture = self.store.get_capture(_string(body, "capture_id", limit=128))
            grain = _string(body, "kind", "detail", 16)
            if grain not in {"detail", "rollup"}:
                raise AppError("invalid_grain", "请选择明细或完整历史日汇总。")
            keys = set(_strings(body, "keys"))
            sessions = set(_strings(body, "session_ids"))
            if not keys and not sessions:
                raise AppError("selection_required", "请先选择需要修正归属的记录。")
            if keys and sessions or grain == "rollup" and sessions:
                raise AppError("invalid_selection", "一次只能按记录或会话选择。")
            rows = capture["data"]["details" if grain == "detail" else "rollups"]
            selected = [
                row
                for row in rows
                if record_key(row, grain) in keys
                or grain == "detail"
                and str(row.get("session_id", "")) in sessions
            ]
            if keys and {record_key(row, grain) for row in selected} != keys:
                raise AppError("selection_expired", "部分记录不属于所选留存，请刷新后重选。", 409)
            if sessions and {str(row.get("session_id", "")) for row in selected} != sessions:
                raise AppError("selection_expired", "部分会话不属于所选留存，请刷新后重选。", 409)
            result = self.store.assign(selected, _project_id(body), grain)
            self.invalidate()
            return result
        if path == "/api/analysis":
            return self._new_analysis(body)
        if match := re.fullmatch(r"/api/batches/" + SAFE_ID + r"/analysis", path):
            return self._new_analysis(body, match[1])
        if path == "/api/batches/preview":
            batch_id = (
                None if body.get("batch_id") is None
                else _string(body, "batch_id", limit=128)
            )
            batch_id = batch_id or None
            result = self._batch_analysis(body, batch_id)
            if result["availability_mode"] != "available":
                raise AppError("read_only_analysis", "全部用量仅供查看，请切换到可用用量。", 409)
            if not result["members"]:
                raise AppError("empty_analysis", "当前没有可用用量，请调整项目或日期。", 409)
            conflicts = analysis.selection_conflicts(
                result, self.store.claim_snapshot(batch_id), batch_id
            )
            return {"overlaps": conflicts, "conflicts": conflicts, "blocking": bool(conflicts)}
        if path == "/api/batches" or re.fullmatch(r"/api/batches/" + SAFE_ID + r"/revisions", path):
            batch_id = None if path == "/api/batches" else path.split("/")[3]
            key = _retry_key(body)
            signature = content_hash({"path": path, "body": body})
            if prior := self.store.replay_create(key, signature):
                return prior
            result = self._batch_analysis(body, batch_id, for_save=True)
            return self.store.create_batch(
                result, self._claim(body), key, batch_id,
                expected_generation=_generation(body) if batch_id else None,
                expected_active_version=_version(body.get("base_version")) if batch_id else None,
                request_signature=signature,
            )
        if match := re.fullmatch(r"/api/batches/" + SAFE_ID + r"/(withdraw|void|resolve)", path):
            batch_id, operation = match[1], match[2]
            generation = _generation(body)
            reason = _string(body, "reason", limit=4000)
            key = _retry_key(body)
            if operation == "withdraw":
                return self.store.withdraw_batch(batch_id, generation, reason, key)
            if operation == "void":
                return self.store.void_batch(batch_id, generation, reason, key)
            return self.store.resolve_legacy(
                batch_id, _version(body.get("selected_version")), generation, reason, key
            )
        if match := re.fullmatch(r"/api/batches/" + SAFE_ID + r"/revisions/([0-9]+)/status", path):
            return self.store.set_status(
                match[1], _version(int(match[2])), _string(body, "status", limit=32),
                expected_generation=_generation(body),
            )
        raise AppError("not_found", "未找到此操作。", 404)


class LocalHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False
    allow_reuse_address = False
    request_queue_size = 16

    def __init__(self, app: Application, port: int = 0) -> None:
        self.app = app
        super().__init__(("127.0.0.1", port), RequestHandler)
        self.origin = f"http://127.0.0.1:{self.server_port}"
        self.session_cookie_name = f"aha_session_{self.server_port}"

    @property
    def bootstrap_url(self) -> str:
        return f"{self.origin}/?token={self.app.bootstrap_token}"

    def handle_error(self, request: Any, client_address: Any) -> None:
        # The base class prints tracebacks and paths. User-facing errors use JSON instead.
        return


class RequestHandler(BaseHTTPRequestHandler):
    server: LocalHTTPServer
    server_version = "aha"
    sys_version = ""

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(20)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send(
        self, status: int, payload: bytes, content_type: str, headers: dict[str, str] | None = None
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; script-src 'self'; "
            "style-src 'self'; img-src 'self'; connect-src 'self'; "
            "base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
        )
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def _json(self, status: int, payload: Any) -> None:
        self._send(
            status,
            json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8"),
            "application/json; charset=utf-8",
        )

    def _error(self, error: AppError) -> None:
        self._json(error.status, {"code": error.code, "message": error.message})

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        self._json(code, {"code": "http_error", "message": "请求格式不受支持。"})

    def _boundary(self) -> tuple[str, dict[str, list[str]]]:
        hosts = self.headers.get_all("Host", [])
        expected = f"127.0.0.1:{self.server.server_port}"
        if hosts != [expected] or self.client_address[0] != "127.0.0.1":
            raise AppError("local_only", "仅允许从本机启动地址访问。", 403)
        origins = self.headers.get_all("Origin", [])
        if origins and origins != [self.server.origin]:
            raise AppError("invalid_origin", "请求来源不正确，请从程序打开的页面访问。", 403)
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            raise AppError("invalid_origin", "请求来源不正确。", 403)
        if len(self.path) > 4096:
            raise AppError("invalid_path", "请求地址过长。", 400)
        parsed = urlsplit(self.path)
        path = unquote(parsed.path)
        if (
            parsed.scheme
            or parsed.netloc
            or "\\" in path
            or "\x00" in path
            or ".." in path.split("/")
        ):
            raise AppError("invalid_path", "请求地址不正确。", 400)
        try:
            return path, parse_qs(parsed.query, max_num_fields=16)
        except ValueError:
            raise AppError("invalid_query", "请求参数过多。") from None

    def _authenticated(self) -> None:
        try:
            cookies = SimpleCookie()
            cookies.load(self.headers.get("Cookie", ""))
            cookie = cookies.get(self.server.session_cookie_name)
        except CookieError:
            cookie = None
        if cookie is None or not _equal(cookie.value, self.server.app.session_token):
            raise AppError(
                "authentication_required", "访问凭证已失效，请从程序启动地址重新打开。", 401
            )

    def _body(self) -> dict[str, Any]:
        if self.headers.get_all("Origin", []) != [self.server.origin]:
            raise AppError("invalid_origin", "请求来源不正确，请重新打开本机页面。", 403)
        if not _equal(self.headers.get("X-AHA-CSRF", ""), self.server.app.csrf_token):
            raise AppError("invalid_csrf", "操作凭证已失效，请刷新页面。", 403)
        lengths = self.headers.get_all("Content-Length", [])
        if self.headers.get("Transfer-Encoding") or len(lengths) != 1 or not lengths[0].isdigit():
            raise AppError("invalid_length", "请求长度不正确。", 400)
        length = int(lengths[0])
        limit = UPLOAD_LIMIT if self.path == "/api/source/sql" else JSON_LIMIT
        if length > limit:
            raise AppError("request_too_large", "请求过大；SQL 文件上限为 128 MiB。", 413)
        if self.headers.get_content_type() != "application/json":
            raise AppError("invalid_content_type", "请求必须使用 JSON。", 415)
        raw = self.rfile.read(length)
        if len(raw) != length:
            raise AppError("incomplete_request", "读取请求失败，请重试。", 400)

        def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in items:
                if key in result:
                    raise ValueError("duplicate key")
                result[key] = value
            return result

        def invalid_constant(value: str) -> None:
            raise ValueError("invalid constant")

        try:
            result = json.loads(
                raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=invalid_constant
            )
        except (UnicodeError, ValueError, RecursionError):
            raise AppError("invalid_json", "请求内容不是有效的 JSON。") from None
        if not isinstance(result, dict):
            raise AppError("invalid_json", "请求内容必须是 JSON 对象。")
        return result

    def do_GET(self) -> None:
        try:
            path, query = self._boundary()
            app = self.server.app
            if path == "/" and "token" in query:
                tokens = query["token"]
                if len(tokens) != 1 or not _equal(tokens[0], app.bootstrap_token):
                    raise AppError(
                        "authentication_required", "启动地址已失效，请重新运行程序。", 401
                    )
                self._send(
                    HTTPStatus.SEE_OTHER,
                    b"",
                    "text/plain",
                    {
                        "Location": "/",
                        "Set-Cookie": (
                            f"{self.server.session_cookie_name}={app.session_token}; Path=/; "
                            "HttpOnly; SameSite=Strict"
                        ),
                    },
                )
                return
            self._authenticated()
            if path == "/licenses":
                notices = Path(__file__).with_name("licenses") / "THIRD_PARTY_NOTICES.txt"
                payload = (
                    notices.read_bytes()
                    if notices.is_file()
                    else (
                        "aha 源码运行模式\n\n"
                        "Python 与 zstandard 的许可证随各自运行环境和安装包提供。\n"
                        "Windows 成品内置本次构建实际运行时、zstandard、zstd 和 "
                        "PyInstaller 的许可证原文，可在此页面查看。\n"
                        "CC Switch 数据语义参考与固定提交见项目 README。\n"
                    ).encode()
                )
                self._send(HTTPStatus.OK, payload, "text/plain; charset=utf-8")
                return
            if path in ASSETS:
                name, content_type = ASSETS[path]
                self._send(HTTPStatus.OK, (WEB_DIR / name).read_bytes(), content_type)
                return
            with app.lock:
                if match := re.fullmatch(
                    r"/api/batches/" + SAFE_ID + r"/revisions/([0-9]+)/download", path
                ):
                    payload, filename = app.store.download(match[1], _version(int(match[2])))
                    self._send(
                        HTTPStatus.OK,
                        payload,
                        "application/zip",
                        {
                            "Content-Disposition": "attachment; filename=aha-evidence.zip; "
                            "filename*=UTF-8''" + quote(filename),
                        },
                    )
                else:
                    self._json(HTTPStatus.OK, app.get(path, query))
        except AppError as error:
            self._error(error)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            return
        except Exception:
            self._json(
                500,
                {
                    "code": "internal_error",
                    "message": "操作未完成。请重试或重新启动程序；已保存资料会保留。",
                },
            )

    def do_POST(self) -> None:
        try:
            path, _ = self._boundary()
            self._authenticated()
            body = self._body()
            if path == "/api/shutdown":
                self._json(HTTPStatus.OK, {"message": "程序已退出，已保存资料会保留。"})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            with self.server.app.lock:
                self._json(HTTPStatus.OK, self.server.app.post(path, body))
        except AppError as error:
            self._error(error)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            return
        except Exception:
            self._json(
                500,
                {
                    "code": "internal_error",
                    "message": "操作未完成。请重试或重新启动程序；已保存资料会保留。",
                },
            )


def create_server(data_dir: Path, port: int = 0) -> LocalHTTPServer:
    app = Application(data_dir)
    try:
        return LocalHTTPServer(app, port)
    except BaseException:
        app.close()
        raise
