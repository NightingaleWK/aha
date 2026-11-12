"""Complete backups, bounded binary uploads and source binding through real HTTP."""

from __future__ import annotations

import hashlib
import threading
import time
import unittest
from contextlib import closing
from pathlib import Path
from typing import Any
from unittest.mock import patch

import test_http
from test_sources import database, detail

from aha.domain import AppError
from aha.server import BACKUP_CHUNK_BYTES
from aha.storage import Store


class BackupHTTPTests(unittest.TestCase):
    request = test_http.HTTPTests.request
    json = test_http.HTTPTests.json
    authenticate = test_http.HTTPTests.authenticate
    wait_sync = test_http.HTTPTests.wait_sync
    load_usage = test_http.HTTPTests.load_usage
    analyze = test_http.HTTPTests.analyze
    claim = staticmethod(test_http.HTTPTests.claim)
    save = test_http.HTTPTests.save
    tearDown = test_http.HTTPTests.tearDown

    def setUp(self) -> None:
        identity = patch("aha.source_bindings.installation_id", return_value="http-test-device")
        identity.start()
        self.addCleanup(identity.stop)
        test_http.HTTPTests.setUp(self)

    def wait_transfer(self, job: dict[str, Any]) -> dict[str, Any]:
        deadline = time.monotonic() + 10
        while job["status"] == "running":
            if time.monotonic() > deadline:
                self.fail("backup or restore worker did not finish")
            time.sleep(0.01)
            job = self.json("GET", "/api/backups/" + job["id"])
        return job

    def upload(self, raw: bytes) -> str:
        upload = self.json("POST", "/api/restore-uploads", {"size": len(raw)})
        for offset in range(0, len(raw), BACKUP_CHUNK_BYTES):
            status, _, data = self.request(
                "POST", "/api/restore-uploads/" + upload["id"] + "/chunks",
                raw[offset:offset + BACKUP_CHUNK_BYTES],
                {"Content-Type": "application/octet-stream", "X-AHA-Upload-Offset": str(offset)},
            )
            self.assertEqual(status, 200, data)
        return str(upload["id"])

    def test_shutdown_closes_allocation_gate_before_cancelling_transfers(self) -> None:
        application = self.server.app
        cancel = application.cancel_transfers

        def allocate_during_close() -> None:
            with self.assertRaises(AppError) as failure:
                application._create_backup()
            self.assertEqual(failure.exception.code, "application_closed")
            self.assertIsNone(application.transfer_directory)
            cancel()

        with patch.object(application, "cancel_transfers", side_effect=allocate_during_close):
            application.close()
        self.assertEqual(application.transfer_jobs, {})

    def test_mark_stopping_closes_allocation_gate_before_cancelling_transfers(self) -> None:
        application = self.server.app
        cancel = application.cancel_transfers
        signal = threading.Event()
        application.transfer_cancels["existing-transfer"] = signal

        def allocate_during_stop() -> None:
            with self.assertRaises(AppError) as failure:
                application._create_upload({"size": 1})
            self.assertEqual(failure.exception.code, "application_closed")
            self.assertIsNone(application.transfer_directory)
            cancel()
            self.assertTrue(signal.is_set())

        with patch.object(application, "cancel_transfers", side_effect=allocate_during_stop):
            self.server.mark_stopping()
        self.assertTrue(self.server.stopping.is_set())
        self.assertEqual(application.restore_uploads, {})

    def complete_backup(self) -> tuple[dict[str, Any], bytes]:
        job = self.wait_transfer(self.json("POST", "/api/backups", {}))
        self.assertEqual(job["status"], "completed", job)
        status, headers, raw = self.request("GET", "/api/backups/" + job["id"] + "/download")
        self.assertEqual(status, 200, raw[:500])
        self.assertIn(".aha-backup", headers["Content-Disposition"])
        self.assertEqual(hashlib.sha256(raw).hexdigest(), job["result"]["sha256"])
        self.assertNotIn("archive_path", job["result"])
        self.assertNotIn("_archive", job)
        return job, raw

    def test_full_http_roundtrip_keeps_current_ledger_and_original_packages(self) -> None:
        self.load_usage(3)
        saved = self.save(self.analyze())
        original, _ = self.server.app.store.download(saved["batch_id"], saved["version"])
        original_hash = hashlib.sha256(original.read_bytes()).hexdigest()
        before = self.json("GET", "/api/ledger")
        job, raw = self.complete_backup()
        upload_id = self.upload(raw)
        target = self.root / "restored"
        restored = self.wait_transfer(self.json(
            "POST", "/api/restore-uploads/" + upload_id + "/restore",
            {"destination": str(target)},
        ))
        self.assertEqual(restored["status"], "completed", restored)
        self.assertEqual(Path(restored["result"]["destination"]), target)
        self.assertEqual(restored["result"]["archive_sha256"], job["result"]["sha256"])
        self.assertTrue((target / "restore-info.json").is_file())
        with closing(Store(target)) as recovered:
            archive, _ = recovered.download(saved["batch_id"], saved["version"])
            self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), original_hash)
            self.assertEqual(recovered.ledger_status()["counts"], before["counts"])
            self.assertTrue(recovered.source_binding_status(self.root / "source.db")["required"])
        self.assertEqual(self.json("GET", "/api/ledger")["counts"], before["counts"])
        with patch("aha.server.subprocess.Popen") as opened:
            self.json("POST", "/api/backups/" + restored["id"] + "/open", {})
        self.assertEqual(opened.call_args.args[0][-2:], ["--data-dir", str(target)])
        self.assertEqual(self.json("GET", "/api/status")["backup"]["id"], restored["id"])

    def test_binary_upload_requires_auth_origin_csrf_type_length_and_exact_offset(self) -> None:
        upload = self.json("POST", "/api/restore-uploads", {"size": 4})
        path = "/api/restore-uploads/" + upload["id"] + "/chunks"
        headers = {"Content-Type": "application/octet-stream", "X-AHA-Upload-Offset": "0"}
        self.assertEqual(self.request("POST", path, b"abcd", headers, authenticated=False)[0], 401)
        for invalid in ({"Origin": "https://invalid.example"}, {"X-AHA-CSRF": "wrong"}):
            self.assertEqual(self.request("POST", path, b"abcd", headers | invalid)[0], 403)
        self.assertEqual(self.request("POST", path, b"abcd", headers | {
            "Content-Type": "application/json"})[0], 415)
        self.assertEqual(self.request("POST", path, b"abcd", headers | {
            "Content-Length": str(BACKUP_CHUNK_BYTES + 1)})[0], 413)
        self.assertEqual(self.request("POST", path, b"abcd", headers | {
            "X-AHA-Upload-Offset": "1"})[0], 409)
        self.assertEqual(self.request("POST", path, b"abcd", headers | {
            "X-AHA-Upload-Offset": "-1"})[0], 400)
        self.assertEqual(self.server.app.restore_uploads[upload["id"]]["received"], 0)
        self.assertEqual(self.request("POST", path, b"ab", headers)[0], 200)
        self.assertEqual(self.request("POST", path, b"ab", headers)[0], 409)
        self.assertEqual(self.request("POST", path, b"cd", headers | {
            "X-AHA-Upload-Offset": "2"})[0], 200)
        self.json("POST", "/api/restore-uploads/" + upload["id"] + "/cancel", {})
        self.assertFalse(self.server.app.restore_uploads)

    def test_invalid_sizes_incomplete_restore_and_existing_or_nested_target_are_safe(self) -> None:
        for size in (0, -1, True, "10", 4 * 1024**3 + 1):
            self.assertEqual(self.request("POST", "/api/restore-uploads", {"size": size})[0], 413)
        upload = self.json("POST", "/api/restore-uploads", {"size": 4})
        path = "/api/restore-uploads/" + upload["id"] + "/restore"
        target = self.root / "new-restored"
        self.assertEqual(self.request("POST", path, {"destination": str(target)})[0], 409)
        self.assertEqual(self.request("POST", path, {"destination": str(self.root)})[0], 409)
        self.assertEqual(self.request("POST", path, {
            "destination": str(self.server.app.store.data_dir / "nested")})[0], 400)
        self.assertEqual(self.request("POST", path, {"destination": "relative-folder"})[0], 400)
        self.assertFalse(target.exists())
        self.json("POST", "/api/restore-uploads/" + upload["id"] + "/cancel", {})

    def test_unfinished_uploads_are_visible_and_cancellable_after_a_page_reload(self) -> None:
        identifiers = [self.json("POST", "/api/restore-uploads", {"size": 4})["id"]
                       for _ in range(4)]
        self.assertEqual(self.request("POST", "/api/restore-uploads", {"size": 4})[0], 409)
        uploads = self.json("GET", "/api/status")["restore_uploads"]
        self.assertEqual({item["id"] for item in uploads}, set(identifiers))
        self.assertTrue(all(set(item) == {"id", "size", "received"} for item in uploads))
        for item in uploads:
            self.json("POST", "/api/restore-uploads/" + item["id"] + "/cancel", {})
        self.assertFalse(self.json("GET", "/api/status")["restore_uploads"])
        self.json("POST", "/api/restore-uploads", {"size": 4})

    def test_corrupt_backup_fails_in_new_directory_without_mutating_current_usage(self) -> None:
        self.load_usage(2)
        before = self.json("GET", "/api/ledger")
        upload = self.upload(b"not a backup")
        target = self.root / "bad-restored"
        job = self.wait_transfer(self.json(
            "POST", "/api/restore-uploads/" + upload + "/restore", {"destination": str(target)}
        ))
        self.assertEqual(job["status"], "failed", job)
        self.assertEqual(job["code"], "invalid_backup")
        self.assertFalse(target.exists())
        self.assertEqual(self.json("GET", "/api/ledger")["counts"], before["counts"])
        self.assertFalse(list(self.server.app._transfer_root().glob("*.upload")))

    def test_backup_worker_is_cancellable_and_keeps_local_queries_available(self) -> None:
        entered = threading.Event()

        def slow(destination: Path, *, cancel: threading.Event) -> dict[str, Any]:
            entered.set()
            self.assertTrue(cancel.wait(5))
            raise AppError("backup_cancelled", "已取消。", 409)

        with patch.object(self.server.app.store, "create_backup", side_effect=slow):
            job = self.json("POST", "/api/backups", {})
            self.assertTrue(entered.wait(2))
            began = time.monotonic()
            self.json("GET", "/api/ledger")
            self.assertLess(time.monotonic() - began, 1)
            self.assertEqual(self.request("POST", "/api/backups", {})[0], 409)
            self.assertEqual(self.request("GET", "/api/backups/" + job["id"] + "/download")[0], 409)
            self.json("POST", "/api/backups/" + job["id"] + "/cancel", {})
            self.assertEqual(self.wait_transfer(job)["status"], "cancelled")

    def test_cancel_by_upload_id_also_cancels_restore_after_response_is_lost(self) -> None:
        entered = threading.Event()

        def slow(archive: Path, destination: Path, *, cancel: threading.Event) -> dict[str, Any]:
            entered.set()
            self.assertTrue(cancel.wait(5))
            raise AppError("backup_cancelled", "已取消。", 409)

        upload = self.upload(b"abcd")
        with patch.object(self.server.app.store, "restore_backup", side_effect=slow):
            job = self.json("POST", "/api/restore-uploads/" + upload + "/restore", {})
            self.assertTrue(entered.wait(2))
            cancelled = self.json("POST", "/api/restore-uploads/" + upload + "/cancel", {})
            self.assertEqual(cancelled["id"], job["id"])
            self.assertEqual(self.wait_transfer(job)["status"], "cancelled")

    def test_new_computer_binding_preserves_old_usage_and_never_quarantines_history(self) -> None:
        source = self.root / "synthetic-source.db"
        database(source, [detail()], version=25).close()
        with patch("aha.source_bindings.installation_id", return_value="old-device"):
            self.server.app.store.sync_sqlite(source)
        before = self.json("GET", "/api/ledger")
        with self.server.app.store.read_connection() as reader:
            before_runs = reader.execute("SELECT count(*) FROM sync_runs").fetchone()[0]
        status = self.json("GET", "/api/status")
        self.assertTrue(status["default_source"]["binding"]["required"])
        self.assertEqual(before["counts"]["pending_count"], 0)
        failed = self.wait_sync(self.json("POST", "/api/sync", {}))
        self.assertEqual(failed["code"], "source_binding_required")
        with self.server.app.store.read_connection() as reader:
            count = reader.execute("SELECT count(*) FROM sync_runs").fetchone()[0]
            self.assertEqual(count, before_runs)
        self.assertEqual(self.request("POST", "/api/source/binding", {"reason": ""})[0], 400)
        binding = self.json("POST", "/api/source/binding", {"reason": "新电脑接续，保留历史"})
        self.assertTrue(binding["bound"])
        self.assertFalse(binding["required"])
        self.assertEqual(self.json("GET", "/api/ledger")["counts"], before["counts"])
        self.assertEqual(self.wait_sync(self.json("POST", "/api/sync", {}))["status"], "completed")
        self.assertEqual(self.json("GET", "/api/ledger")["counts"], before["counts"])

    def test_binding_metadata_error_does_not_prevent_querying_saved_history(self) -> None:
        self.load_usage(2)
        (self.root / "synthetic-source.db").touch()
        with patch.object(self.server.app.store, "source_binding_status", side_effect=AppError(
            "source_binding_damaged", "来源绑定需要检查。", 409
        )):
            status = self.json("GET", "/api/status")
        self.assertTrue(status["default_source"]["binding"]["required"])
        self.assertEqual(status["ledger"]["counts"]["detail_count"], 2)
        self.assertEqual(self.analyze()["summary"]["detail_count"], 2)


if __name__ == "__main__":
    unittest.main()
