"""Authenticated loopback flows use the local ledger and finite explicit sync jobs."""

from __future__ import annotations

import base64
import hashlib
import http.client
import http.cookiejar
import io
import json
import sqlite3
import tempfile
import threading
import time
import unittest
import zipfile
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch
from urllib.parse import urlsplit
from urllib.request import HTTPCookieProcessor, build_opener

from test_sources import database, detail, dump, price, rollup

from aha.server import JSON_LIMIT, create_server


class HTTPTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        source_patch = patch(
            "aha.server.default_sqlite_path", return_value=self.root / "synthetic-source.db"
        )
        source_patch.start()
        self.addCleanup(source_patch.stop)
        self.server = create_server(self.root / "data")
        self.server.app.metadata_roots = [self.root / "isolated-codex"]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.cookie = ""
        self.csrf = ""
        self.authenticate()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.server.app.close()
        self.temporary.cleanup()

    def request(
        self,
        method: str,
        path: str,
        body: Any = None,
        headers: dict[str, str] | None = None,
        *,
        authenticated: bool = True,
    ) -> tuple[int, dict[str, str], bytes]:
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        request_headers = {"Cookie": self.cookie} if authenticated else {}
        payload = None
        if body is not None:
            payload = body if isinstance(body, bytes) else json.dumps(body).encode()
            request_headers.update(
                {
                    "Content-Type": "application/json",
                    "Origin": self.server.origin,
                    "X-AHA-CSRF": self.csrf,
                }
            )
        request_headers.update(headers or {})
        try:
            connection.request(method, path, body=payload, headers=request_headers)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def json(self, method: str, path: str, body: Any = None) -> dict[str, Any]:
        status, _, payload = self.request(method, path, body)
        result = json.loads(payload)
        self.assertEqual(status, 200, result)
        self.assertIsInstance(result, dict)
        return result

    def authenticate(self) -> None:
        query = urlsplit(self.server.bootstrap_url).query
        status, headers, _ = self.request("GET", "/?" + query, authenticated=False)
        self.assertEqual(status, 303)
        self.assertEqual(headers["Location"], "/")
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        self.assertIn("SameSite=Strict", headers["Set-Cookie"])
        self.cookie = headers["Set-Cookie"].split(";", 1)[0]
        self.csrf = self.json("GET", "/api/status")["csrf_token"]

    def wait_sync(self, job: dict[str, Any]) -> dict[str, Any]:
        deadline = time.monotonic() + 10
        while job["status"] == "running":
            if time.monotonic() >= deadline:
                self.fail("finite sync did not finish")
            time.sleep(0.01)
            job = self.json("GET", "/api/sync/" + job["id"])
        return job

    def load_usage(self, count: int = 55) -> dict[str, Any]:
        event = int(datetime.fromisoformat("2026-10-26T08:00:00+08:00").timestamp())
        raw = dump(
            [detail(request_id=f"request-{i}", created_at=event + i) for i in range(count)],
            [],
            [price()],
        )
        job = self.json(
            "POST",
            "/api/source/sql",
            {
                "name": r"C:\private\usage.sql",
                "content_base64": base64.b64encode(raw).decode(),
            },
        )
        completed = self.wait_sync(job)
        self.assertEqual(completed["status"], "completed", completed)
        return completed

    def analyze(self, project_id: str = "all", *, mode: str = "available") -> dict[str, Any]:
        return self.json(
            "POST",
            "/api/analysis",
            {
                "start_date": "2026-09-01",
                "end_date": "2026-10-26",
                "project_id": project_id,
                "availability_mode": mode,
            },
        )

    @staticmethod
    def claim(purpose: str = "项目开发") -> dict[str, Any]:
        return {"purpose": purpose, "amount": "", "currency": "CNY", "amount_note": ""}

    def save(self, analysis: dict[str, Any], key: str = "http-create-key-0001") -> dict[str, Any]:
        return self.json(
            "POST",
            "/api/batches",
            {
                "analysis_id": analysis["analysis_id"],
                "claim": self.claim(),
                "idempotency_key": key,
            },
        )

    def test_auth_origin_csrf_static_and_payload_boundaries(self) -> None:
        for path in ("/", "/api/status", "/app.js", "/licenses"):
            self.assertEqual(self.request("GET", path, authenticated=False)[0], 401)
        for headers in (
            {"Host": "attacker.invalid"},
            {"Origin": "https://attacker.invalid"},
            {"Sec-Fetch-Site": "cross-site"},
        ):
            self.assertEqual(self.request("GET", "/api/status", headers=headers)[0], 403)
        for headers in ({"Origin": "null"}, {"X-AHA-CSRF": "wrong"}):
            self.assertEqual(self.request("POST", "/api/projects", {}, headers)[0], 403)
        self.assertEqual(self.request("GET", "/%2e%2e/private")[0], 400)
        self.assertEqual(self.request("GET", "/api/captures")[0], 404)
        for raw in (b'{"name":"a","name":"b"}', b'{"name":NaN}', b"[]"):
            self.assertEqual(self.request("POST", "/api/projects", raw)[0], 400)
        self.assertEqual(
            self.request("POST", "/api/projects", {}, {"Content-Length": str(JSON_LIMIT + 1)})[0],
            413,
        )
        status, headers, payload = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertEqual(headers["Referrer-Policy"], "no-referrer")
        self.assertIn("本地用量台账", payload.decode())
        self.assertNotIn(self.server.app.bootstrap_token, payload.decode())
        self.assertEqual(self.request("GET", "/app.js")[0], 200)
        self.assertEqual(self.request("GET", "/licenses")[0], 200)

    def test_startup_is_once_per_launch_and_queries_are_not_locked_by_sync(self) -> None:
        entered, release = threading.Event(), threading.Event()

        def sync(*args: Any, **kwargs: Any) -> dict[str, Any]:
            entered.set()
            release.wait(timeout=5)
            return {"status": "completed"}

        with patch.object(self.server.app.store, "sync_sqlite", side_effect=sync) as mocked:
            first = self.json("POST", "/api/sync", {"trigger": "startup"})
            self.assertTrue(entered.wait(timeout=2))
            try:
                second = self.json("POST", "/api/sync", {"trigger": "startup"})
                self.assertEqual(first["id"], second["id"])
                began = time.monotonic()
                self.json("GET", "/api/ledger")
                self.assertLess(time.monotonic() - began, 1)
                self.assertEqual(self.request("POST", "/api/sync", {})[0], 409)
            finally:
                release.set()
            self.assertEqual(self.wait_sync(first)["status"], "completed")
            self.assertEqual(
                self.json("POST", "/api/sync", {"trigger": "startup"})["id"], first["id"]
            )
            self.assertEqual(mocked.call_count, 1)

    def test_failed_sync_keeps_local_data_and_previous_preview(self) -> None:
        self.load_usage()
        analysis = self.analyze()
        before = self.json("GET", "/api/ledger")
        job = self.json(
            "POST",
            "/api/source/sql",
            {
                "name": "invalid.sql",
                "content_base64": base64.b64encode(b"invalid SQL").decode(),
            },
        )
        self.assertEqual(self.wait_sync(job)["status"], "failed")
        after = self.json("GET", "/api/ledger")
        self.assertEqual(before["data_revision"], after["data_revision"])
        self.assertEqual(before["counts"], after["counts"])
        with patch.object(
            self.server.app.store, "sync_sqlite", side_effect=AssertionError("query read source")
        ):
            page = self.json("GET", f"/api/analysis/{analysis['analysis_id']}/details?kind=detail")
            self.assertEqual(len(page["rows"]), 50)
            self.json("GET", "/api/ledger")

    def test_source_needing_review_finishes_without_becoming_success(self) -> None:
        source = self.root / "synthetic-ccs.db"
        with closing(database(source, [detail(request_id=f"request-{i}") for i in range(3)])):
            pass
        self.server.app.metadata_roots = [self.root / "isolated-codex"]
        initial = self.wait_sync(self.json("POST", "/api/sync", {"path": str(source)}))
        self.assertEqual(initial["status"], "completed")
        before = self.json("GET", "/api/ledger")
        with closing(sqlite3.connect(source)) as connection:
            connection.execute("DELETE FROM proxy_request_logs WHERE request_id!='request-0'")
            connection.commit()
        job = self.wait_sync(self.json("POST", "/api/sync", {"path": str(source)}))
        self.assertEqual(job["status"], "needs_review")
        self.assertEqual(job["result"]["state"], "needs_review")
        self.assertIn("finished_at", job)
        self.assertEqual(self.json("GET", "/api/status")["sync"], job)
        after = self.json("GET", "/api/ledger")
        self.assertEqual(after["last_successful_sync_at"], before["last_successful_sync_at"])
        self.assertEqual(after["counts"]["detail_count"], 3)
        analysis = self.analyze(mode="all")
        rows = self.json("GET", f"/api/analysis/{analysis['analysis_id']}/details?kind=detail")
        self.assertEqual(len(rows["rows"]), 3)
        self.assertTrue(self.json("GET", "/api/reconciliations")["cases"])

    def test_all_preview_tabs_use_local_cursor_pages_and_revision_binding(self) -> None:
        self.load_usage()
        analysis = self.analyze(mode="all")
        self.assertNotIn("details", analysis)
        self.assertNotIn("members", analysis)
        self.assertNotIn("daily", analysis)
        path = f"/api/analysis/{analysis['analysis_id']}/details"
        first = self.json("GET", path + "?kind=detail&size=50")
        self.assertEqual(len(first["rows"]), 50)
        from urllib.parse import quote

        second = self.json(
            "GET", path + "?kind=detail&size=50&cursor=" + quote(first["next_cursor"])
        )
        self.assertEqual(len(second["rows"]), 5)
        self.assertFalse(
            {r["record_key"] for r in first["rows"]} & {r["record_key"] for r in second["rows"]}
        )
        self.assertEqual(self.request("GET", path + "?size=201")[0], 400)
        for kind in ("daily", "models", "rollup"):
            page = self.json("GET", path + "?kind=" + kind)
            self.assertLessEqual(len(page["rows"]), 50)
        self.load_usage(56)
        self.assertEqual(self.request("GET", path + "?kind=detail")[0], 409)

    def test_assignment_and_project_queries_use_local_records(self) -> None:
        self.load_usage(3)
        analysis = self.analyze()
        rows = self.json("GET", f"/api/analysis/{analysis['analysis_id']}/details")["rows"]
        project = self.json("POST", "/api/projects", {"name": "本地项目"})["project"]
        self.json(
            "POST",
            "/api/assignments",
            {"keys": [rows[0]["record_key"]], "project_id": project["id"]},
        )
        self.assertEqual(int(self.analyze(project["id"])["summary"]["detail_count"]), 1)
        self.assertEqual(
            self.request("GET", f"/api/analysis/{analysis['analysis_id']}/details")[0], 409
        )

    def test_target_preview_cannot_be_used_for_new_batch_and_frozen_revision_is_stable(
        self,
    ) -> None:
        self.load_usage(3)
        saved = self.save(self.analyze())
        batch_id = saved.get("batch_id", saved["id"])
        batch = self.json("GET", "/api/batches/" + batch_id)
        preview = self.json(
            "POST",
            f"/api/batches/{batch_id}/analysis",
            {
                "start_date": "2026-09-01",
                "end_date": "2026-10-26",
                "base_version": 1,
                "expected_generation": batch["generation"],
            },
        )
        code, _, body = self.request(
            "POST",
            "/api/batches",
            {
                "analysis_id": preview["analysis_id"],
                "claim": self.claim(),
                "idempotency_key": "http-borrow-target-key",
            },
        )
        self.assertEqual(code, 409, body)
        self.assertEqual(json.loads(body)["code"], "analysis_target_mismatch")
        old_path = f"/api/batches/{batch_id}/revisions/1/download"
        original = self.request("GET", old_path)[2]
        self.json("POST", "/api/projects", {"name": "后来新增项目"})
        revised = self.json(
            "POST",
            f"/api/batches/{batch_id}/revisions",
            {
                "base_version": 1,
                "expected_generation": batch["generation"],
                "claim": self.claim("修改用途"),
                "idempotency_key": "http-frozen-revision-key",
            },
        )
        self.assertEqual(revised["version"], 2)
        self.assertEqual(original, self.request("GET", old_path)[2])

    def test_download_streams_original_package_and_head_has_no_body(self) -> None:
        self.load_usage(3)
        saved = self.save(self.analyze())
        batch_id = saved.get("batch_id", saved["id"])
        path = f"/api/batches/{batch_id}/revisions/{saved['version']}/download"
        with patch.object(Path, "read_bytes", side_effect=AssertionError("whole package read")):
            status, headers, raw = self.request("GET", path)
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/zip")
        self.assertIn("filename*=UTF-8''", headers["Content-Disposition"])
        self.assertEqual(hashlib.sha256(raw).hexdigest(), saved["sha256"])
        status, head, body = self.request("HEAD", path)
        self.assertEqual(status, 200)
        self.assertEqual(body, b"")
        self.assertEqual(int(head["Content-Length"]), len(raw))
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            self.assertEqual(
                set(archive.namelist()),
                {"使用明细.csv", "每日汇总.csv", "费用说明.html", "导出信息.json"},
            )

    def test_persistent_idempotency_replays_after_preview_cache_is_cleared(self) -> None:
        self.load_usage(3)
        analysis = self.analyze()
        payload = {
            "analysis_id": analysis["analysis_id"],
            "claim": self.claim(),
            "idempotency_key": "http-persistent-replay-key",
        }
        first = self.json("POST", "/api/batches", payload)
        self.server.app.invalidate()
        replay = self.json("POST", "/api/batches", payload)
        self.assertEqual(first["id"], replay["id"])
        self.assertEqual(first["version"], replay["version"])
        self.assertEqual(len(self.json("GET", "/api/batches")["batches"]), 1)

    def test_two_instances_keep_sessions_in_one_browser_cookie_jar(self) -> None:
        other = create_server(self.root / "other-data")
        thread = threading.Thread(target=other.serve_forever, daemon=True)
        thread.start()
        browser = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
        try:
            for server in (self.server, other):
                with browser.open(server.bootstrap_url, timeout=10) as response:
                    self.assertEqual(response.status, 200)
            for server in (self.server, other):
                with browser.open(server.origin + "/api/status", timeout=10) as response:
                    status = json.load(response)
                self.assertEqual(status["version"], "0.3.0")
        finally:
            other.shutdown()
            other.server_close()
            thread.join(timeout=3)
            other.app.close()

    def test_time_range_status_assets_and_invalid_requests_do_not_create_previews(self) -> None:
        with patch("aha.time_ranges.current_time", return_value=datetime.fromisoformat(
            "2026-10-26T08:00:59+08:00"
        )):
            status = self.json("GET", "/api/status")
        self.assertEqual(status["now"], "2026-10-26T08:00:59+08:00")
        self.assertEqual(status["today"], "2026-10-26")
        for asset in ("/form-controls.js", "/time-range-picker.js"):
            status_code, headers, body = self.request("GET", asset)
            self.assertEqual(status_code, 200)
            self.assertEqual(headers["Content-Type"], "text/javascript; charset=utf-8")
            self.assertTrue(body)
        valid = {"kind": "custom", "start": "2026-10-26T08:00",
                 "end": "2026-10-26T08:00", "follow_now": False}
        before = len(self.server.app.analyses)
        for body in (
            {"time_range": None},
            {"time_range": valid, "start_date": "2026-10-26"},
            {"time_range": valid, "end_date": "2026-10-26"},
            {"time_range": {**valid, "start": "2026-10-26T08:00Z"}},
            {"time_range": {**valid, "rollup_policy": "all"}},
            {"time_range": {"kind": "preset", "preset": "all", "follow_now": False}},
        ):
            with self.subTest(body=body):
                code, _, raw = self.request("POST", "/api/analysis", body)
                self.assertEqual(code, 400, raw)
                self.assertEqual(json.loads(raw)["code"], "invalid_time_range")
                self.assertEqual(len(self.server.app.analyses), before)

    def test_exact_time_analysis_both_routes_save_and_old_download(self) -> None:
        self.load_usage(55)
        selected = {"kind": "preset", "preset": "last_24h", "follow_now": False,
                    "end_before": "2026-10-26T08:00:10+08:00"}
        analysis = self.json("POST", "/api/analysis", {"time_range": selected})
        self.assertEqual(analysis["summary"]["record_count"], 10)
        self.assertEqual(analysis["time_range"]["start_at"], "2026-10-25T08:00:10+08:00")
        self.assertTrue(analysis["summary_complete"])
        for kind in ("detail", "daily", "models"):
            page = self.json("GET", f"/api/analysis/{analysis['analysis_id']}/details?kind={kind}")
            represented = len(page["rows"]) if kind == "detail" else sum(
                row["record_count"] for row in page["rows"])
            self.assertEqual(represented, 10)
        with patch("aha.time_ranges.current_time", side_effect=AssertionError("save read clock")):
            saved = self.save(analysis, "precise-http-create")
        batch_id = saved["id"]
        old_url = f"/api/batches/{batch_id}/revisions/1/download"
        original = self.request("GET", old_url)[2]
        with zipfile.ZipFile(io.BytesIO(original)) as package:
            manifest = json.loads(package.read("导出信息.json"))
            self.assertEqual(manifest["manifest_version"], 4)
            self.assertEqual(manifest["selection"]["time_range"], analysis["time_range"])
            self.assertEqual(len(manifest["members"]), 10)
        own = self.json("POST", f"/api/batches/{batch_id}/analysis", {
            "time_range": selected, "base_version": 1, "expected_generation": saved["generation"],
        })
        self.assertEqual(own["summary"], analysis["summary"])
        self.assertEqual(own["availability"]["excluded_summary"]["record_count"], 0)
        status_code, _, raw = self.request("POST", "/api/batches", {
            "analysis_id": own["analysis_id"], "claim": self.claim(),
            "idempotency_key": "cannot-reuse-target",
        })
        self.assertEqual(status_code, 409, raw)
        self.assertEqual(json.loads(raw)["code"], "analysis_target_mismatch")
        revision = self.json("POST", f"/api/batches/{batch_id}/revisions", {
            "analysis_id": own["analysis_id"], "claim": self.claim("补充用途"),
            "base_version": 1, "expected_generation": saved["generation"],
            "idempotency_key": "precise-current-revision",
        })
        self.assertEqual(revision["version"], 2)
        self.assertEqual(revision["time_range"], own["time_range"])
        self.assertEqual(self.request("GET", old_url)[2], original)

    def test_partial_day_rollup_http_saves_certain_members_and_keeps_incompleteness(self) -> None:
        event = int(datetime.fromisoformat("2026-10-26T08:00:00+08:00").timestamp())
        raw = dump([detail(created_at=event)],
                   [rollup(date="2026-10-26", model="rollup-only-model")], [price()])
        job = self.json("POST", "/api/source/sql", {
            "name": "synthetic-range.sql", "content_base64": base64.b64encode(raw).decode(),
        })
        self.assertEqual(self.wait_sync(job)["status"], "completed")
        analysis = self.json("POST", "/api/analysis", {"time_range": {
            "kind": "custom", "start": "2026-10-26T08:00", "end": "2026-10-26T08:00",
            "follow_now": False,
        }})
        self.assertFalse(analysis["summary_complete"])
        self.assertEqual(analysis["pending_count"], 0)
        self.assertEqual(analysis["summary"]["record_count"], 1)
        self.assertEqual(analysis["availability"]["excluded_summary"]["total_cost_usd"], "0")
        self.assertEqual(analysis["time_coverage"]["omitted_days"], ["2026-10-26"])
        self.assertFalse(self.json("POST", "/api/batches/preview", {
            "analysis_id": analysis["analysis_id"], "claim": self.claim(),
        })["blocking"])
        saved = self.save(analysis, "http-incomplete-save")
        package_url = f"/api/batches/{saved['id']}/revisions/1/download"
        with zipfile.ZipFile(io.BytesIO(self.request("GET", package_url)[2])) as package:
            manifest = json.loads(package.read("导出信息.json"))
            self.assertEqual(manifest["summary"]["record_count"], 1)
            self.assertFalse(manifest["summary_complete"])
            self.assertEqual(manifest["time_coverage"], analysis["time_coverage"])


if __name__ == "__main__":
    unittest.main()
