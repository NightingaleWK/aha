"""Real loopback routes with synthetic CCS input and isolated persistent files."""

from __future__ import annotations

import base64
import csv
import hashlib
import http.client
import io
import json
import tempfile
import threading
import unittest
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from test_sources import database, detail, dump, price, rollup

from aha.server import JSON_LIMIT, create_server


class HTTPTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.server = create_server(self.root / "data")
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

    def load_capture(self, count: int = 55) -> dict[str, Any]:
        roots = self.root / "codex"
        sessions = roots / "sessions"
        sessions.mkdir(parents=True, exist_ok=True)
        (sessions / "rollout-s1.jsonl").write_text(
            json.dumps({"type": "session_meta", "payload": {"id": "s1", "cwd": "/work/demo"}})
            + "\nPRIVATE_CHAT_BODY_MUST_NOT_BE_READ\n",
            encoding="utf-8",
        )
        self.server.app.metadata_roots = [roots]
        event = int(datetime.fromisoformat("2026-10-26T08:00:00+08:00").timestamp())
        raw = dump(
            [
                detail(request_id=f"request-{index}", created_at=event + index)
                for index in range(count)
            ],
            [rollup()],
            [price()],
        )
        return self.json(
            "POST",
            "/api/source/sql",
            {
                "name": r"C:\private\usage.sql",
                "content_base64": base64.b64encode(raw).decode(),
            },
        )

    def analyze(self, capture_id: str, project_id: str = "all") -> dict[str, Any]:
        return self.json(
            "POST",
            "/api/analysis",
            {
                "capture_id": capture_id,
                "start_date": "2026-09-01",
                "end_date": "2026-10-26",
                "project_id": project_id,
            },
        )

    def test_auth_origin_csrf_static_and_payload_boundaries(self) -> None:
        for path in ("/", "/api/status", "/app.js", "/licenses"):
            self.assertEqual(self.request("GET", path, authenticated=False)[0], 401)
        self.assertEqual(self.request("GET", "/?token=%E4%B8%AD%E6%96%87")[0], 401)
        for headers in (
            {"Host": "attacker.invalid"},
            {"Origin": "https://attacker.invalid"},
            {"Sec-Fetch-Site": "cross-site"},
        ):
            self.assertEqual(self.request("GET", "/api/status", headers=headers)[0], 403)
        for headers in ({"Origin": "null"}, {"X-AHA-CSRF": "wrong"}):
            self.assertEqual(self.request("POST", "/api/projects", {}, headers)[0], 403)
        self.assertEqual(self.request("GET", "/%2e%2e/private")[0], 400)
        self.assertEqual(self.request("GET", "/private-file")[0], 404)
        self.assertEqual(self.request("POST", "/api/projects", b'{"name":"a","name":"b"}')[0], 400)
        self.assertEqual(self.request("POST", "/api/projects", b'{"name":NaN}')[0], 400)
        self.assertEqual(self.request("POST", "/api/projects", b"[]")[0], 400)
        self.assertEqual(
            self.request(
                "POST",
                "/api/projects",
                {},
                {
                    "Content-Length": str(JSON_LIMIT + 1),
                },
            )[0],
            413,
        )
        status, headers, payload = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertEqual(headers["Referrer-Policy"], "no-referrer")
        self.assertIn("用量导出", payload.decode())
        self.assertNotIn(self.server.app.bootstrap_token, payload.decode())
        self.assertEqual(self.request("GET", "/app.js")[0], 200)
        self.assertEqual(self.request("GET", "/style.css")[0], 200)
        self.assertEqual(self.request("GET", "/licenses")[0], 200)

    def test_source_project_assignment_batches_and_original_download(self) -> None:
        capture = self.load_capture()
        self.assertEqual(capture["source"]["name"], "usage.sql")
        self.assertEqual(capture["counts"]["detail_count"], 55)
        self.assertEqual(capture["metadata_coverage"]["matched_sessions"], 1)
        self.assertEqual(capture["directories"][0]["path"], "/work/demo")
        self.assertNotIn("PRIVATE_CHAT_BODY", str(capture))
        project = self.json(
            "POST",
            "/api/projects",
            {
                "name": "项目 <b>甲</b>",
                "description": "测试",
                "directories": ["/work/demo"],
            },
        )["project"]
        preview = self.analyze(capture["id"], project["id"])
        self.assertEqual(preview["summary"]["detail_count"], 55)
        self.assertEqual(preview["summary"]["total_cost_usd"], "10.45")
        first = self.json("GET", f"/api/analysis/{preview['analysis_id']}/details?size=50")
        second = self.json("GET", f"/api/analysis/{preview['analysis_id']}/details?size=50&page=2")
        self.assertEqual(len(first["rows"]), 50)
        self.assertEqual(len(second["rows"]), 5)
        all_preview = self.analyze(capture["id"])
        historical = self.json(
            "GET",
            f"/api/analysis/{all_preview['analysis_id']}/details?kind=rollup",
        )["rows"][0]
        self.json(
            "POST",
            "/api/assignments",
            {
                "capture_id": capture["id"],
                "kind": "rollup",
                "keys": [historical["record_key"]],
                "project_id": project["id"],
            },
        )
        status, _, raw = self.request("GET", f"/api/analysis/{preview['analysis_id']}/details")
        self.assertEqual(status, 409)
        self.assertEqual(json.loads(raw)["code"], "analysis_expired")
        preview = self.analyze(capture["id"], project["id"])
        self.assertEqual(preview["summary"]["record_count"], 63)
        body = {
            "analysis_id": preview["analysis_id"],
            "idempotency_key": "http-repeat-operation-123",
            "claim": {
                "purpose": "开发用途",
                "amount": "0",
                "currency": "CNY",
                "amount_note": "金额为零的测试依据",
            },
        }
        batch = self.json("POST", "/api/batches", body)
        duplicate = self.json("POST", "/api/batches", body)
        self.assertEqual((batch["id"], batch["version"]), (duplicate["id"], duplicate["version"]))
        self.assertEqual(batch["status"], "draft")
        path = f"/api/batches/{batch['id']}/revisions/1/download"
        status, headers, original = self.request("GET", path)
        self.assertEqual(status, 200)
        self.assertIn("filename*=UTF-8''", headers["Content-Disposition"])
        with zipfile.ZipFile(io.BytesIO(original)) as package:
            rows = list(csv.reader(io.StringIO(package.read("使用明细.csv").decode("utf-8-sig"))))
            self.assertEqual(len(rows), 56)  # Header plus every record, including page two.
        self.json(
            "POST", f"/api/batches/{batch['id']}/revisions/1/status", {"status": "reimbursed"}
        )
        overlap = self.json("POST", "/api/batches/preview", {"analysis_id": preview["analysis_id"]})
        self.assertEqual(overlap["overlaps"][0]["status"], "reimbursed")
        self.json(
            "POST",
            f"/api/projects/{project['id']}",
            {
                "name": "重命名",
                "description": "",
                "directories": ["/elsewhere"],
            },
        )
        revision = self.json(
            "POST",
            f"/api/batches/{batch['id']}/revisions",
            {
                "base_version": 1,
                "idempotency_key": "http-revision-operation-123",
                "claim": {"purpose": "新说明", "amount": "", "currency": "USD", "amount_note": ""},
            },
        )
        self.assertEqual(revision["version"], 2)
        self.assertEqual(revision["status"], "draft")
        self.assertEqual(
            hashlib.sha256(self.request("GET", path)[2]).digest(), hashlib.sha256(original).digest()
        )
        history = self.json("GET", f"/api/batches/{batch['id']}")
        self.assertEqual(history["revisions"][0]["status"], "reimbursed")
        self.assertEqual(len(self.json("GET", "/api/batches")["batches"]), 1)

    def test_failed_import_expires_previous_analysis_and_history_remains(self) -> None:
        capture = self.load_capture(1)
        preview = self.analyze(capture["id"])
        status, _, _ = self.request(
            "POST",
            "/api/source/sql",
            {
                "name": "bad.sql",
                "content_base64": base64.b64encode(b"invalid SQL").decode(),
            },
        )
        self.assertEqual(status, 400)
        self.assertEqual(
            self.request("GET", f"/api/analysis/{preview['analysis_id']}/details")[0], 409
        )
        self.assertIsNone(self.json("GET", "/api/status")["current_capture_id"])
        self.assertEqual(
            self.json("GET", f"/api/captures/{capture['id']}")["counts"]["detail_count"], 1
        )
        self.assertEqual(self.analyze(capture["id"])["summary"]["detail_count"], 1)

    def test_browser_batch_preview_optional_id_and_frozen_revision(self) -> None:
        capture = self.load_capture(1)
        preview = self.analyze(capture["id"])
        # Preserve the complete shape sent by the browser, including blank claim fields.
        # Older open pages sent batch_id:null for a new batch; it has the same meaning
        # as the current page omitting this optional field.
        body = {
            "analysis_id": preview["analysis_id"],
            "claim": {"purpose": "浏览器申请", "amount": "", "currency": "CNY", "amount_note": ""},
            "idempotency_key": "browser-new-batch-operation-123",
        }
        for payload in ({**body, "batch_id": None}, body):
            with self.subTest(batch_id=payload.get("batch_id", "omitted")):
                result = self.json("POST", "/api/batches/preview", payload)
                self.assertEqual(result["overlaps"], [])
        self.assertEqual(self.json("GET", "/api/batches")["batches"], [])
        batch = self.json("POST", "/api/batches", body)
        self.assertEqual(batch["status"], "draft")
        # Revision previews carry a real ID and exclude their own batch, both when
        # changing the selected analysis and when reusing an earlier frozen version.
        for payload in (
            {**body, "batch_id": batch["id"]},
            {"base_version": 1, "claim": body["claim"], "batch_id": batch["id"]},
        ):
            self.assertEqual(self.json("POST", "/api/batches/preview", payload)["overlaps"], [])
        status, _, _ = self.request("POST", "/api/batches/preview", {**body, "batch_id": 123})
        self.assertEqual(status, 400)
        self.assertEqual(len(self.json("GET", "/api/batches")["batches"]), 1)

    def test_sqlite_route_and_explicit_metadata_refresh_make_new_capture(self) -> None:
        path = self.root / "source.db"
        connection = database(path, [detail()])
        connection.close()
        original = hashlib.sha256(path.read_bytes()).hexdigest()
        capture = self.json("POST", "/api/source/sqlite", {"path": str(path)})
        preview = self.analyze(capture["id"])
        roots = self.root / "new-codex" / "sessions"
        roots.mkdir(parents=True)
        (roots / "rollout-s1.jsonl").write_text(
            json.dumps(
                {
                    "type": "session_meta",
                    "payload": {"id": "s1", "cwd": "/work/another"},
                }
            )
            + "\n",
            encoding="utf-8",
        )
        refreshed = self.json(
            "POST",
            "/api/session-metadata",
            {
                "capture_id": capture["id"],
                "roots": [str(roots.parent)],
            },
        )
        self.assertNotEqual(capture["id"], refreshed["id"])
        self.assertEqual(refreshed["directories"][0]["path"], "/work/another")
        self.assertEqual(
            self.request("GET", f"/api/analysis/{preview['analysis_id']}/details")[0], 409
        )
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), original)
        self.assertEqual(len(self.json("GET", "/api/captures")["captures"]), 2)


if __name__ == "__main__":
    unittest.main()
