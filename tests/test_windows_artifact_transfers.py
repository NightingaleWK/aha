"""Native acceptance must authenticate binary uploads and reject wrong job progress."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import verify_windows_artifact as artifact  # noqa: E402


class ArtifactTransferTests(unittest.TestCase):
    def client(self) -> artifact.Client:
        client = object.__new__(artifact.Client)
        client.port, client.origin = 12345, "http://127.0.0.1:12345"
        client.cookie, client.csrf = "synthetic-cookie", "synthetic-csrf"
        return client

    def test_binary_upload_keeps_bytes_and_all_required_authentication_headers(self) -> None:
        client = self.client()
        connection = Mock()
        response = connection.getresponse.return_value
        response.status = 200
        response.read.return_value = b'{}'
        response.getheaders.return_value = []
        with patch.object(artifact.http.client, "HTTPConnection", return_value=connection):
            client.request("POST", "/api/restore-uploads/test/chunks", b"\x00\xffraw",
                           headers={"X-AHA-Upload-Offset": "4"})
        arguments = connection.request.call_args
        self.assertEqual(arguments.kwargs["body"], b"\x00\xffraw")
        self.assertEqual(arguments.kwargs["headers"], {
            "Cookie": "synthetic-cookie", "Content-Type": "application/octet-stream",
            "Origin": client.origin, "X-AHA-CSRF": "synthetic-csrf", "X-AHA-Upload-Offset": "4",
        })
        connection.close.assert_called_once()

    def test_upload_stops_when_server_progress_or_advertised_chunk_limit_is_wrong(self) -> None:
        client = self.client()
        with patch.object(client, "json", return_value={"id": "own", "chunk_bytes": 4}), \
                patch.object(client, "request", side_effect=[
                    (200, {}, json.dumps({"id": "own", "received": 4, "size": 12}).encode()),
                    (200, {}, json.dumps({"id": "own", "received": 9, "size": 12}).encode()),
                ]) as uploaded:
            with self.assertRaises(artifact.VerificationError):
                client.upload_backup(b"0123456789ab")
            self.assertEqual(uploaded.call_count, 2)
            self.assertEqual(uploaded.call_args_list[1].kwargs["headers"]["X-AHA-Upload-Offset"],
                             "4")
        with patch.object(client, "json", return_value={"id": "own", "chunk_bytes": 8 * 1024**2}), \
                patch.object(client, "request") as uploaded:
            with self.assertRaises(artifact.VerificationError):
                client.upload_backup(b"one")
            uploaded.assert_not_called()

    def test_transfer_polling_rejects_a_different_job_and_a_failed_terminal_result(self) -> None:
        client = self.client()
        with patch.object(client, "json", return_value={"id": "other", "status": "completed"}), \
                patch.object(artifact.time, "sleep"):
            with self.assertRaises(artifact.VerificationError):
                client.transfer({"id": "own", "status": "running"})
        with self.assertRaises(artifact.VerificationError):
            client.transfer({"id": "own", "status": "failed"})

    def test_transfer_timeout_does_not_poll_an_unbounded_job(self) -> None:
        client = self.client()
        with patch.object(artifact.time, "monotonic", side_effect=[0, 31]), \
                patch.object(client, "json") as fetched:
            with self.assertRaises(artifact.VerificationError):
                client.transfer({"id": "own", "status": "running"})
            fetched.assert_not_called()
