"""Real loopback routes with synthetic CCS input and isolated persistent files."""

from __future__ import annotations

import base64
import csv
import hashlib
import http.client
import http.cookiejar
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
from urllib.request import HTTPCookieProcessor, Request, build_opener

from test_sources import database, detail, dump, price, rollup

from aha.analysis import analyze
from aha.server import JSON_LIMIT, create_server
from aha.storage import Store


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

    def analyze(
        self, capture_id: str, project_id: str = "all", *, mode: str = "available"
    ) -> dict[str, Any]:
        return self.json(
            "POST",
            "/api/analysis",
            {
                "capture_id": capture_id,
                "start_date": "2026-09-01",
                "end_date": "2026-10-26",
                "project_id": project_id,
                "availability_mode": mode,
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
        self.assertIn("用量", payload.decode())
        self.assertNotIn(self.server.app.bootstrap_token, payload.decode())
        self.assertEqual(self.request("GET", "/app.js")[0], 200)
        self.assertEqual(self.request("GET", "/style.css")[0], 200)
        self.assertEqual(self.request("GET", "/licenses")[0], 200)

    def test_two_instances_keep_sessions_in_one_browser_cookie_jar(self) -> None:
        other = create_server(self.root / "other-data")
        thread = threading.Thread(target=other.serve_forever, daemon=True)
        thread.start()
        cookies = http.cookiejar.CookieJar()
        browser = build_opener(HTTPCookieProcessor(cookies))
        try:
            for server in (self.server, other):
                with browser.open(server.bootstrap_url, timeout=10) as response:
                    self.assertEqual(response.status, 200)
            self.assertEqual(len(cookies), 2)
            for index, server in enumerate((self.server, other)):
                with browser.open(server.origin + "/api/status", timeout=10) as response:
                    status = json.load(response)
                project_name = f"实例 {index} 项目"
                request = Request(
                    server.origin + "/api/projects",
                    data=json.dumps({"name": project_name}).encode(),
                    headers={
                        "Content-Type": "application/json",
                        "Origin": server.origin,
                        "X-AHA-CSRF": status["csrf_token"],
                    },
                    method="POST",
                )
                with browser.open(request, timeout=10) as response:
                    self.assertEqual(response.status, 200)
                with browser.open(server.origin + "/api/projects", timeout=10) as response:
                    projects = json.load(response)["projects"]
                self.assertEqual([project["name"] for project in projects], [project_name])
        finally:
            other.shutdown()
            other.server_close()
            thread.join(timeout=3)
            other.app.close()

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
        self.assertEqual(
            self.request("GET", f"/api/analysis/{preview['analysis_id']}/details")[0], 409
        )
        remaining = self.analyze(capture["id"], project["id"])
        self.assertEqual(remaining["summary"]["record_count"], 0)
        self.assertEqual(remaining["availability"]["excluded_summary"]["record_count"], 63)
        readonly = self.analyze(capture["id"], project["id"], mode="all")
        self.assertEqual(readonly["summary"]["record_count"], 63)
        status, _, _ = self.request("POST", "/api/batches", {
            **body, "analysis_id": readonly["analysis_id"],
            "idempotency_key": "read-only-create-blocked-123",
        })
        self.assertEqual(status, 409)
        revision = self.json(
            "POST", f"/api/batches/{batch['id']}/revisions",
            {
                "base_version": 1, "expected_generation": batch["generation"],
                "idempotency_key": "http-revision-operation-123",
                "claim": {"purpose": "新说明", "amount": "", "currency": "USD", "amount_note": ""},
            },
        )
        self.assertEqual((revision["version"], revision["status"]), (2, "draft"))
        self.assertTrue(revision["is_effective"])
        self.assertEqual(hashlib.sha256(self.request("GET", path)[2]).digest(),
                         hashlib.sha256(original).digest())
        status, _, _ = self.request("POST", f"/api/batches/{batch['id']}/revisions/1/status", {
            "status": "reimbursed", "expected_generation": revision["generation"],
        })
        self.assertEqual(status, 409)
        paid = self.json("POST", f"/api/batches/{batch['id']}/revisions/2/status", {
            "status": "reimbursed", "expected_generation": revision["generation"],
        })
        self.assertEqual(paid["status"], "reimbursed")
        history = self.json("GET", f"/api/batches/{batch['id']}")
        self.assertFalse(history["revisions"][0]["is_effective"])
        self.assertEqual(history["revisions"][0]["status"], "draft")
        self.assertFalse(history["can_edit"])
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

    def test_browser_preview_and_revision_subject_cannot_be_borrowed_by_new_claim(self) -> None:
        capture = self.load_capture(1)
        preview = self.analyze(capture["id"])
        body = {
            "analysis_id": preview["analysis_id"],
            "claim": {"purpose": "浏览器申请", "amount": "", "currency": "CNY", "amount_note": ""},
            "idempotency_key": "browser-new-batch-operation-123",
        }
        for payload in ({**body, "batch_id": None}, body):
            result = self.json("POST", "/api/batches/preview", payload)
            self.assertFalse(result["blocking"])
            self.assertEqual(result["conflicts"], [])
        batch = self.json("POST", "/api/batches", body)
        frozen = {
            "base_version": 1, "expected_generation": batch["generation"],
            "claim": body["claim"], "batch_id": batch["id"],
        }
        self.assertFalse(self.json("POST", "/api/batches/preview", frozen)["blocking"])
        revision_preview = self.json("POST", f"/api/batches/{batch['id']}/analysis", {
            "capture_id": capture["id"], "start_date": "2026-09-01", "end_date": "2026-10-26",
            "project_id": "all", "base_version": 1,
            "expected_generation": batch["generation"],
        })
        self.assertEqual(revision_preview["summary"], preview["summary"])
        self.assertEqual(revision_preview["target_batch_id"], batch["id"])
        self.assertEqual(self.request("POST", "/api/batches", {
            **body, "analysis_id": revision_preview["analysis_id"],
            "idempotency_key": "borrow-other-subject-blocked-123",
        })[0], 409)
        for field in ("batch_id", "exclude_batch_id", "target_batch_id"):
            self.assertEqual(self.request("POST", "/api/analysis", {
                "capture_id": capture["id"], "start_date": "2026-09-01",
                "end_date": "2026-10-26", field: batch["id"],
            })[0], 400)
        self.assertEqual(self.request("POST", "/api/batches/preview", {
            **body, "batch_id": 123,
        })[0], 400)
        self.assertEqual(self.request("POST", f"/api/batches/{batch['id']}/analysis", {
            "capture_id": capture["id"], "start_date": "2026-09-01", "end_date": "2026-10-26",
            "base_version": True, "expected_generation": batch["generation"],
        })[0], 400)
        self.assertEqual(len(self.json("GET", "/api/batches")["batches"]), 1)

    def test_frozen_revision_survives_project_changes_and_preserves_old_material(self) -> None:
        capture = self.load_capture(1)
        project = self.json("POST", "/api/projects", {
            "name": "旧项目名", "directories": ["/work/demo"],
        })["project"]
        preview = self.analyze(capture["id"], project["id"])
        first = self.json("POST", "/api/batches", {
            "analysis_id": preview["analysis_id"],
            "idempotency_key": "frozen-before-project-change",
            "claim": {"purpose": "原说明"},
        })
        original_path = f"/api/batches/{first['id']}/revisions/1/download"
        original = self.request("GET", original_path)[2]
        self.json("POST", f"/api/projects/{project['id']}", {
            "name": "新项目名", "directories": ["/elsewhere"],
        })
        revised = self.json("POST", f"/api/batches/{first['id']}/revisions", {
            "base_version": 1, "expected_generation": first["generation"],
            "idempotency_key": "frozen-after-project-change",
            "claim": {"purpose": "补充说明"},
        })
        self.assertEqual(revised["version"], 2)
        self.assertEqual(revised["project_name"], "旧项目名")
        self.assertEqual(revised["summary"], preview["summary"])
        self.assertEqual(self.request("GET", original_path)[2], original)

    def test_remaining_preview_and_zip_share_only_unclaimed_members(self) -> None:
        capture = self.load_capture(3)
        project = self.json("POST", "/api/projects", {"name": "首笔用量"})["project"]
        original = self.analyze(capture["id"])
        first_row = self.json(
            "GET", f"/api/analysis/{original['analysis_id']}/details?kind=detail"
        )["rows"][0]
        self.json("POST", "/api/assignments", {
            "capture_id": capture["id"], "kind": "detail",
            "keys": [first_row["record_key"]], "project_id": project["id"],
        })
        owned = self.analyze(capture["id"], project["id"])
        first = self.json("POST", "/api/batches", {
            "analysis_id": owned["analysis_id"], "idempotency_key": "first-partial-claim-123",
            "claim": {},
        })
        remaining = self.json("POST", "/api/analysis", {
            "capture_id": capture["id"], "start_date": "2026-10-26",
            "end_date": "2026-10-26", "project_id": "all",
        })
        self.assertEqual(remaining["summary"]["record_count"], 2)
        self.assertEqual(remaining["summary"]["total_cost_usd"], "0.38")
        self.assertEqual(remaining["availability"]["matched_summary"]["record_count"], 3)
        self.assertEqual(remaining["availability"]["excluded_summary"]["record_count"], 1)
        self.assertEqual(remaining["availability"]["excluded_groups"][0]["owners"][0]["batch_id"],
                         first["id"])
        second = self.json("POST", "/api/batches", {
            "analysis_id": remaining["analysis_id"], "idempotency_key": "second-partial-claim-123",
            "claim": {"amount": "100", "currency": "CNY", "amount_note": "人工填写"},
        })
        raw = self.request(
            "GET", f"/api/batches/{second['id']}/revisions/1/download"
        )[2]
        with zipfile.ZipFile(io.BytesIO(raw)) as package:
            details = list(csv.DictReader(io.StringIO(
                package.read("使用明细.csv").decode("utf-8-sig")
            )))
            daily = list(csv.DictReader(io.StringIO(
                package.read("每日汇总.csv").decode("utf-8-sig")
            )))
            manifest = json.loads(package.read("导出信息.json"))
        self.assertEqual(len(details), 2)
        self.assertNotIn(first_row["request_id"], {row["request_id"] for row in details})
        self.assertEqual(daily[0]["record_count"], "2")
        self.assertEqual(daily[0]["total_cost_usd"], "0.38")
        self.assertEqual(manifest["summary"], remaining["summary"])
        self.assertEqual(manifest["claim"]["amount"], "100")
        final = self.json("POST", "/api/analysis", {
            "capture_id": capture["id"], "start_date": "2026-10-26",
            "end_date": "2026-10-26", "project_id": "all",
        })
        self.assertEqual(final["summary"]["record_count"], 0)

    def test_lifecycle_release_and_persistent_request_retry_never_reactivate(self) -> None:
        capture = self.load_capture(1)
        preview = self.analyze(capture["id"])
        body = {
            "analysis_id": preview["analysis_id"], "idempotency_key": "persistent-create-key-123",
            "claim": {
                "purpose": "原申请", "amount": "100", "currency": "CNY", "amount_note": "测试"
            },
        }
        batch = self.json("POST", "/api/batches", body)
        original = self.request("GET", f"/api/batches/{batch['id']}/revisions/1/download")[2]
        # Simulate a source/filter change clearing every in-memory analysis after a lost reply.
        self.server.app.invalidate()
        self.assertEqual(self.json("POST", "/api/batches", body)["id"], batch["id"])
        self.assertEqual(self.request("POST", "/api/batches", {
            **body, "claim": {**body["claim"], "purpose": "different payload"},
        })[0], 409)
        submitted = self.json("POST", f"/api/batches/{batch['id']}/revisions/1/status", {
            "status": "submitted", "expected_generation": batch["generation"],
        })
        self.assertEqual(self.request("POST", f"/api/batches/{batch['id']}/revisions", {
            "base_version": 1, "expected_generation": submitted["generation"],
            "idempotency_key": "submitted-direct-edit-blocked-123", "claim": body["claim"],
        })[0], 409)
        self.assertEqual(self.request("POST", f"/api/batches/{batch['id']}/withdraw", {
            "expected_generation": submitted["generation"], "reason": "",
            "idempotency_key": "withdraw-empty-reason-123",
        })[0], 400)
        withdrawal_body = {
            "expected_generation": submitted["generation"], "reason": "补充用途后重提",
            "idempotency_key": "withdraw-valid-reason-123",
        }
        withdrawn = self.json("POST", f"/api/batches/{batch['id']}/withdraw", withdrawal_body)
        self.assertEqual(withdrawn["status"], "draft")
        self.assertEqual(self.analyze(capture["id"])["summary"]["record_count"], 0)
        paid = self.json("POST", f"/api/batches/{batch['id']}/revisions/1/status", {
            "status": "reimbursed", "expected_generation": withdrawn["generation"],
        })
        self.assertEqual(self.request("POST", f"/api/batches/{batch['id']}/revisions/1/status", {
            "status": "draft", "expected_generation": paid["generation"],
        })[0], 409)
        void_body = {
            "expected_generation": paid["generation"], "reason": "原申请填写错误",
            "idempotency_key": "void-valid-reason-operation-123",
        }
        voided = self.json("POST", f"/api/batches/{batch['id']}/void", void_body)
        self.assertEqual(voided["lifecycle"], "voided")
        available = self.analyze(capture["id"])
        self.assertEqual(available["summary"], preview["summary"])
        second = self.json("POST", "/api/batches", {
            **body, "analysis_id": available["analysis_id"],
            "idempotency_key": "replacement-create-key-123",
        })
        self.assertNotEqual(second["id"], batch["id"])
        self.json("POST", f"/api/batches/{batch['id']}/void", void_body)
        self.assertEqual(self.analyze(capture["id"])["summary"]["record_count"], 0)
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.server.app.close()
        self.server = create_server(self.root / "data")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.authenticate()
        replayed = self.json("POST", "/api/batches", body)
        self.assertEqual(replayed["id"], batch["id"])
        self.assertEqual(replayed["lifecycle"], "voided")
        self.assertEqual(len(self.json("GET", "/api/batches")["batches"]), 2)
        self.assertEqual(self.analyze(capture["id"])["summary"]["record_count"], 0)
        self.assertEqual(self.request("GET", f"/api/batches/{batch['id']}/revisions/1/download")[2],
                         original)

    def test_other_connection_claim_expires_preview_and_cannot_silently_shrink_save(self) -> None:
        capture = self.load_capture(2)
        preview = self.analyze(capture["id"])
        other = Store(self.root / "data")
        try:
            saved = other.get_capture(capture["id"])
            other_result = analyze(
                saved["data"], saved["metadata"], other.config(), "2026-09-01", "2026-10-26",
                claim_snapshot=other.claim_snapshot(), availability_mode="available",
            )
            other_result["capture_id"] = capture["id"]
            other.create_batch(other_result, {}, "other-connection-winner")
        finally:
            other.close()
        self.assertEqual(
            self.request("GET", f"/api/analysis/{preview['analysis_id']}/details")[0], 409
        )
        self.assertEqual(self.request("POST", "/api/batches", {
            "analysis_id": preview["analysis_id"], "idempotency_key": "stale-preview-save-key-123",
            "claim": {
                "purpose": "不能静默扣减", "amount": "100", "currency": "CNY", "amount_note": "测试"
            },
        })[0], 409)
        self.assertEqual(len(self.json("GET", "/api/batches")["batches"]), 1)
        self.assertEqual(self.analyze(capture["id"])["summary"]["record_count"], 0)

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
