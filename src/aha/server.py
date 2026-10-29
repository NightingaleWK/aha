"""Local HTTP boundary. All usage arithmetic stays in the analysis layer."""

from __future__ import annotations

import base64
import binascii
import copy
import json
import re
import secrets
import threading
from collections import OrderedDict
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PureWindowsPath
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlsplit

from . import __version__, time_ranges
from .domain import AppError, content_hash
from .instance import PROTOCOL_VERSION, profile_id
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
    "/form-controls.js": ("form-controls.js", "text/javascript; charset=utf-8"),
    "/time-range-picker.js": ("time-range-picker.js", "text/javascript; charset=utf-8"),
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
    """Own per-launch previews and finite sync jobs; Store owns durable state."""

    def __init__(self, data_dir: Path) -> None:
        self.store = Store(data_dir)
        self.lock = threading.RLock()
        self.bootstrap_token = secrets.token_urlsafe(32)
        self.session_token = secrets.token_urlsafe(32)
        self.csrf_token = secrets.token_urlsafe(32)
        self.launch_id = secrets.token_hex(16)
        self.metadata_roots = [Path.home() / ".codex"]
        self.analyses: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self.jobs: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self.workers: dict[str, threading.Thread] = {}
        self.cancel = threading.Event()
        self.startup_job: str | None = None
        self.closed = False

    def close(self) -> None:
        self.cancel.set()
        with self.lock:
            self.closed = True
            workers = list(self.workers.values())
        for worker in workers:
            worker.join()
        with self.lock:
            self.analyses.clear()
        self.store.close()

    def invalidate(self) -> None:
        with self.lock:
            self.analyses.clear()

    def status(self) -> dict[str, Any]:
        with self.lock:
            latest_job = max(self.jobs.values(), key=lambda job: job["started_at"], default=None)
            current_sync = copy.deepcopy(latest_job)
        captured = time_ranges.current_time()
        return {
            "version": __version__,
            "today": captured.date().isoformat(),
            "now": captured.isoformat(timespec="seconds"),
            "timezone": "Asia/Shanghai",
            "csrf_token": self.csrf_token,
            "launch_id": self.launch_id,
            "default_source": {
                "name": "cc-switch.db",
                "available": default_sqlite_path().is_file(),
            },
            "sql_limit_bytes": SQL_LIMIT,
            "ledger": self.store.ledger_status(),
            "startup_sync": self._job(self.startup_job) if self.startup_job else None,
            "sync": current_sync,
        }

    def _job(self, job_id: str | None) -> dict[str, Any]:
        with self.lock:
            if job_id is None or job_id not in self.jobs:
                raise AppError("sync_not_found", "未找到这次同步，请重新打开同步状态。", 404)
            return copy.deepcopy(self.jobs[job_id])

    def _sync_worker(self, job_id: str, kind: str, source: Any, name: str, trigger: str) -> None:
        try:
            if kind == "sqlite":
                result = self.store.sync_sqlite(
                    source,
                    self.metadata_roots,
                    trigger=trigger,
                    startup_id=self.launch_id if trigger == "startup" else None,
                    cancel=self.cancel,
                )
            else:
                result = self.store.sync_sql(
                    source, name, self.metadata_roots, trigger=trigger, cancel=self.cancel
                )
            run_state = result.get("state", result.get("status"))
            failed = run_state in {"failed", "cancelled"}
            needs_review = run_state == "needs_review"
            public_status = "failed" if failed else "needs_review" if needs_review else "completed"
            with self.lock:
                self.jobs[job_id].update(
                    {
                        "status": public_status,
                        "result": result,
                        "finished_at": datetime.now(BEIJING).isoformat(),
                    }
                )
                if failed:
                    self.jobs[job_id]["message"] = result.get(
                        "message", "同步未完成，原本地数据已保留。"
                    )
        except AppError as error:
            with self.lock:
                self.jobs[job_id].update(
                    {
                        "status": "failed",
                        "code": error.code,
                        "message": error.message,
                        "finished_at": datetime.now(BEIJING).isoformat(),
                    }
                )
        except Exception:
            with self.lock:
                self.jobs[job_id].update(
                    {
                        "status": "failed",
                        "code": "sync_failed",
                        "message": "同步未完成，原本地数据已保留，请重试。",
                        "finished_at": datetime.now(BEIJING).isoformat(),
                    }
                )
        finally:
            with self.lock:
                self.workers.pop(job_id, None)

    def _start_sync(self, body: dict[str, Any], *, sql: bool = False) -> dict[str, Any]:
        trigger = _string(body, "trigger", "manual", 16)
        if trigger not in {"startup", "manual"} or sql and trigger != "manual":
            raise AppError("invalid_sync_trigger", "请选择打开时同步或手动同步。")
        # Decode/validate an explicit import before allocating a worker.
        source: Any
        name = "cc-switch.db"
        if sql:
            encoded = _string(body, "content_base64", limit=UPLOAD_LIMIT)
            if len(encoded) > ((SQL_LIMIT + 2) // 3) * 4:
                raise AppError("file_too_large", "SQL 文件不能超过 128 MiB。", 413)
            try:
                source = base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error):
                raise AppError("invalid_upload", "文件读取失败，请重新选择 SQL 备份。") from None
            if len(source) > SQL_LIMIT:
                raise AppError("file_too_large", "SQL 文件不能超过 128 MiB。", 413)
            name = PureWindowsPath(_string(body, "name", "backup.sql", 255)).name
        else:
            file_path = _string(body, "path")
            source = Path(file_path) if file_path else default_sqlite_path()
        with self.lock:
            if self.closed:
                raise AppError("application_closed", "程序正在退出，请重新启动。", 409)
            if trigger == "startup" and self.startup_job is not None:
                return self._job(self.startup_job)
            running = next((job for job in self.jobs.values() if job["status"] == "running"), None)
            if running is not None:
                raise AppError("sync_in_progress", "已有同步正在进行，请等待本次完成。", 409)
            job_id = secrets.token_hex(16)
            job = {
                "id": job_id,
                "status": "running",
                "trigger": trigger,
                "source_name": name,
                "started_at": datetime.now(BEIJING).isoformat(),
            }
            self.jobs[job_id] = job
            if trigger == "startup":
                self.startup_job = job_id
            while len(self.jobs) > 32:
                first = next(iter(self.jobs))
                if first == self.startup_job:
                    self.jobs.move_to_end(first)
                    continue
                self.jobs.pop(first)
            worker = threading.Thread(
                target=self._sync_worker,
                args=(job_id, "sql" if sql else "sqlite", source, name, trigger),
                name="aha-explicit-sync",
                daemon=True,
            )
            self.workers[job_id] = worker
            worker.start()
            return copy.deepcopy(job)

    def _analysis(self, analysis_id: str, *, check_claims: bool = True) -> dict[str, Any]:
        with self.lock:
            result = self.analyses.get(analysis_id)
        if result is None:
            raise AppError("analysis_expired", "预览已过期，请更新预览后保存。", 409)
        self.store.validate_analysis(result, check_claims=check_claims)
        if check_claims and result.get("target_batch_id"):
            batch = self.store.batch_detail(result["target_batch_id"])
            if (
                not batch["can_edit"]
                or batch["generation"] != result["expected_generation"]
                or batch["active_version"] != result["expected_active_version"]
            ):
                raise AppError("stale_batch", "报销记录已变化，请刷新后重试。", 409)
        return result

    def _editable_batch(self, body: dict[str, Any], batch_id: str) -> dict[str, Any]:
        batch = self.store.batch_detail(batch_id)
        if batch["lifecycle"] == "voided":
            raise AppError("batch_voided", "这条报销记录已作废，请新建记录。", 409)
        if not batch["can_edit"]:
            raise AppError("inactive_revision", "当前记录不能修改，请先核对报销状态。", 409)
        if batch["generation"] != _generation(body) or batch["active_version"] != _version(
            body.get("base_version")
        ):
            raise AppError("stale_batch", "报销记录已变化，请刷新后重试。", 409)
        return batch

    def _batch_analysis(
        self, body: dict[str, Any], batch_id: str | None, *, for_save: bool = False
    ) -> dict[str, Any]:
        if body.get("analysis_id"):
            result = self._analysis(
                _string(body, "analysis_id", limit=128), check_claims=not for_save
            )
            if result.get("target_batch_id") != batch_id:
                raise AppError("analysis_target_mismatch", "请为这条报销记录重新预览用量。", 409)
            if batch_id is not None and (
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
        result.update(
            {
                "frozen_basis": {"batch_id": batch_id, "version": batch["active_version"]},
                "target_batch_id": batch_id,
                "expected_generation": batch["generation"],
                "expected_active_version": batch["active_version"],
                "availability_mode": "available",
            }
        )
        return result

    def _new_analysis(self, body: dict[str, Any], batch_id: str | None = None) -> dict[str, Any]:
        if batch_id is None and any(
            key in body for key in ("target_batch_id", "exclude_batch_id", "batch_id")
        ):
            raise AppError("invalid_analysis_target", "请通过报销记录选择要修改的用量。")
        batch = self._editable_batch(body, batch_id) if batch_id else None
        mode = _string(body, "availability_mode", "available", 16)
        if batch_id and mode != "available":
            raise AppError("read_only_analysis", "修改报销记录时请选择可用用量。", 409)
        options = {
            "availability_mode": mode,
            "target_batch_id": batch_id,
            "expected_generation": batch["generation"] if batch else None,
            "expected_active_version": batch["active_version"] if batch else None,
        }
        project = _string(body, "project_id", "all", 128)
        if "time_range" in body:
            if "start_date" in body or "end_date" in body:
                raise AppError("invalid_time_range", "请只选择一种时间范围格式。")
            result = self.store.analyze_time_range(body["time_range"], project, **options)
        else:
            result = self.store.analyze(
                _string(body, "start_date", limit=10),
                _string(body, "end_date", limit=10), project, **options,
            )
        requested = body.get("classification_revision", result["classification_revision"])
        if (
            isinstance(requested, bool)
            or not isinstance(requested, int)
            or requested != result["classification_revision"]
        ):
            raise AppError("classification_changed", "项目归属已变化，请更新预览。", 409)
        analysis_id = secrets.token_urlsafe(24)
        result["analysis_id"] = analysis_id
        with self.lock:
            self.analyses[analysis_id] = result
            while len(self.analyses) > 24:
                self.analyses.popitem(last=False)
        return result

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
        if path == "/api/ledger":
            return self.store.ledger_status()
        if match := re.fullmatch(r"/api/sync/" + SAFE_ID, path):
            return self._job(match[1])
        if path == "/api/reconciliations":
            return {"cases": self.store.list_reconciliations()}
        if path == "/api/projects":
            return self.store.config()
        if path == "/api/batches":
            return {"batches": self.store.list_batches()}
        if match := re.fullmatch(r"/api/batches/" + SAFE_ID, path):
            return self.store.batch_detail(match[1])
        if match := re.fullmatch(r"/api/analysis/" + SAFE_ID + r"/details", path):
            result = self._analysis(match[1])
            kind = query.get("kind", ["detail"])[0]
            if kind not in {"detail", "rollup", "daily", "models"}:
                raise AppError("invalid_grain", "请选择明细、汇总或统计。")
            try:
                size = int(query.get("size", ["50"])[0])
            except ValueError:
                raise AppError("invalid_page", "分页参数不正确。") from None
            if not 1 <= size <= 200:
                raise AppError("invalid_page", "每页可查看 1 至 200 条记录。")
            return self.store.analysis_details(
                result, cursor=query.get("cursor", [None])[0], size=size, kind=kind
            )
        raise AppError("not_found", "未找到此内容。", 404)

    def post(self, path: str, body: dict[str, Any]) -> Any:
        if path in {"/api/sync", "/api/source/sqlite"}:
            return self._start_sync(body)
        if path == "/api/source/sql":
            return self._start_sync(body, sql=True)
        if path == "/api/session-metadata":
            roots = _strings(body, "roots", 32)
            self.metadata_roots = [Path(root).expanduser() for root in roots] or [
                Path.home() / ".codex"
            ]
            result = self.store.refresh_metadata(self.metadata_roots)
            self.invalidate()
            return result
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
            keys, sessions = _strings(body, "keys"), _strings(body, "session_ids")
            if bool(keys) == bool(sessions):
                raise AppError("invalid_selection", "一次请按记录或会话选择。")
            if keys:
                result = self.store.assign_keys(keys, _project_id(body))
            else:
                result = self.store.assign_sessions(
                    list(dict.fromkeys(sessions)), _project_id(body)
                )
            self.invalidate()
            return result
        if match := re.fullmatch(r"/api/reconciliations/" + SAFE_ID, path):
            result = self.store.resolve_reconciliation(
                match[1],
                _string(body, "choice", limit=32),
                _string(body, "reason", limit=4000),
                expected_generation=_generation(body),
                idempotency_key=_retry_key(body),
            )
            self.invalidate()
            return result
        if path == "/api/analysis":
            return self._new_analysis(body)
        if match := re.fullmatch(r"/api/batches/" + SAFE_ID + r"/analysis", path):
            return self._new_analysis(body, match[1])
        if path == "/api/batches/preview":
            batch_id = (
                None
                if body.get("batch_id") is None
                else _string(body, "batch_id", limit=128) or None
            )
            result = self._batch_analysis(body, batch_id)
            if result["availability_mode"] != "available":
                raise AppError("read_only_analysis", "全部用量仅供查看，请切换到可用用量。", 409)
            if not result["summary"]["record_count"]:
                raise AppError("empty_analysis", "当前没有可用用量，请调整项目或日期。", 409)
            conflicts = self.store.overlaps(result, batch_id)
            return {"overlaps": conflicts, "conflicts": conflicts, "blocking": bool(conflicts)}
        if path == "/api/batches" or re.fullmatch(r"/api/batches/" + SAFE_ID + r"/revisions", path):
            batch_id = None if path == "/api/batches" else path.split("/")[3]
            key = _retry_key(body)
            signature = content_hash({"path": path, "body": body})
            if prior := self.store.replay_create(key, signature):
                return prior
            result = self._batch_analysis(body, batch_id, for_save=True)
            return self.store.create_batch(
                result,
                self._claim(body),
                key,
                batch_id,
                expected_generation=_generation(body) if batch_id else None,
                expected_active_version=_version(body.get("base_version")) if batch_id else None,
                request_signature=signature,
            )
        if match := re.fullmatch(r"/api/batches/" + SAFE_ID + r"/(withdraw|void)", path):
            batch_id, action = match[1], match[2]
            method = self.store.withdraw_batch if action == "withdraw" else self.store.void_batch
            return method(
                batch_id, _generation(body), _string(body, "reason", limit=4000), _retry_key(body)
            )
        if match := re.fullmatch(r"/api/batches/" + SAFE_ID + r"/revisions/([0-9]+)/status", path):
            return self.store.set_status(
                match[1],
                _version(int(match[2])),
                _string(body, "status", limit=32),
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
        self.on_shutdown: Callable[[], None] | None = None
        self.stopping = threading.Event()
        self._state = "ready"
        self._state_lock = threading.Lock()
        self._requests = threading.Condition()
        self._request_count = 0
        self.profile_id = profile_id(app.store.data_dir)
        super().__init__(("127.0.0.1", port), RequestHandler)
        self.origin = f"http://127.0.0.1:{self.server_port}"
        self.session_cookie_name = f"aha_session_{self.server_port}"

    @property
    def bootstrap_url(self) -> str:
        return f"{self.origin}/?token={self.app.bootstrap_token}"

    def mark_starting(self) -> None:
        with self._state_lock:
            self._state = "starting"

    def mark_ready(self) -> None:
        with self._state_lock:
            if not self.stopping.is_set():
                self._state = "ready"

    def mark_stopping(self) -> None:
        with self._state_lock:
            self.stopping.set()
            self._state = "stopping"
        self.app.cancel.set()
        with self.app.lock:
            self.app.closed = True

    def instance_identity(self) -> dict[str, Any]:
        with self._state_lock:
            return {
                "application": "aha",
                "protocol_version": PROTOCOL_VERSION,
                "run_id": self.app.launch_id,
                "profile_id": self.profile_id,
                "state": self._state,
            }

    def request_shutdown(self) -> None:
        self.mark_stopping()
        if self.on_shutdown is not None:
            self.on_shutdown()
        else:
            threading.Thread(target=self.shutdown, name="aha-shutdown", daemon=True).start()

    def ensure_active(self) -> None:
        if self.stopping.is_set():
            raise AppError("application_closed", "程序正在退出，请稍后重新打开。", 409)

    def process_request(self, request: Any, client_address: Any) -> None:
        # Reserve before starting a worker so shutdown cannot miss an accepted request.
        with self._requests:
            self._request_count += 1
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._request_finished()
            raise

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._request_finished()

    def _request_finished(self) -> None:
        with self._requests:
            self._request_count -= 1
            self._requests.notify_all()

    def wait_for_requests(self) -> None:
        with self._requests:
            self._requests.wait_for(lambda: self._request_count == 0)

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

    def _response_headers(
        self, status: int, length: int, content_type: str, headers: dict[str, str] | None = None
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
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

    def _send(
        self, status: int, payload: bytes, content_type: str, headers: dict[str, str] | None = None
    ) -> None:
        self._response_headers(status, len(payload), content_type, headers)
        if self.command != "HEAD":
            self.wfile.write(payload)

    def _send_file(self, path: Path, filename: str) -> None:
        with path.open("rb") as source:
            self._response_headers(
                HTTPStatus.OK,
                path.stat().st_size,
                "application/zip",
                {
                    "Content-Disposition": "attachment; filename=aha-evidence.zip; "
                    "filename*=UTF-8''" + quote(filename)
                },
            )
            if self.command != "HEAD":
                while chunk := source.read(1024 * 1024):
                    self.wfile.write(chunk)

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
                self.server.ensure_active()
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
            if path == "/api/instance":
                self._json(HTTPStatus.OK, self.server.instance_identity())
                return
            self.server.ensure_active()
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
            if match := re.fullmatch(
                r"/api/batches/" + SAFE_ID + r"/revisions/([0-9]+)/download", path
            ):
                file_path, filename = app.store.download(match[1], _version(int(match[2])))
                self._send_file(file_path, filename)
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

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_POST(self) -> None:
        try:
            path, _ = self._boundary()
            self._authenticated()
            body = self._body()
            if path == "/api/shutdown":
                self.server.request_shutdown()
                self._json(HTTPStatus.OK, {"message": "正在退出程序，已保存资料会保留。"})
                return
            self.server.ensure_active()
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
