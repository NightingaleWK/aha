"""Artifact validation must reject wrong identity, credentials and damaged evidence."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import verify_windows_artifact as artifact  # noqa: E402


def material(*, cost: str = "0.570000003", tamper: bool = False) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=["model", "total_cost_usd", "total_tokens"])
    writer.writeheader()
    writer.writerows([{"model": "合成模型", "total_cost_usd": "0.190000001",
                       "total_tokens": "105"}] * 3)
    files = {"使用明细.csv": output.getvalue().encode("utf-8-sig"),
             "每日汇总.csv": b"synthetic daily", "费用说明.html": b"<p>0.570000003 USD</p>"}
    manifest = {"application": {"name": "aha", "version": "0.3.1"},
                "summary": {"record_count": 3, "total_cost_usd": cost, "total_tokens": 315},
                "members": [{}, {}, {}],
                "files": {name: {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
                          for name, raw in files.items()}}
    if tamper:
        files["使用明细.csv"] += b"tampered"
    files["导出信息.json"] = json.dumps(manifest).encode()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as package:
        for name, raw in files.items():
            package.writestr(name, raw)
    return buffer.getvalue()


class ArtifactBoundaryTests(unittest.TestCase):
    def test_environment_is_synthetic_and_refuses_unknown_existing_data(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            unknown = root / "unknown"
            unknown.mkdir()
            (unknown / "real.sqlite3").write_bytes(b"must remain")
            with self.assertRaises(artifact.VerificationError):
                artifact.isolated_environment(unknown)
            self.assertEqual((unknown / "real.sqlite3").read_bytes(), b"must remain")
            env, profile = artifact.isolated_environment(root / "owned")
            self.assertEqual(env["USERPROFILE"], str(profile))
            self.assertEqual(env["HOME"], str(profile))
            self.assertTrue(Path(env["LOCALAPPDATA"]).is_relative_to(root / "owned"))
            self.assertNotIn("PYTHONPATH", env)
            self.assertNotIn("PYTHONHOME", env)
            self.assertNotEqual(env["USERPROFILE"], os.environ.get("USERPROFILE"))
            with self.assertRaises(artifact.VerificationError):
                artifact.isolated_environment(root / "owned")

    def test_descriptor_cannot_authenticate_to_an_external_or_malformed_address(self) -> None:
        addresses = (
            "https://127.0.0.1:1234/?token=" + "x" * 20,
            "http://example.invalid:1234/?token=" + "x" * 20,
            "http://127.0.0.1:1234/other?token=" + "x" * 20,
            "http://127.0.0.1:1234/?token=short",
            "http://127.0.0.1:1234/?token=" + "x" * 20 + "&token=" + "y" * 20,
            "http://user:secret@127.0.0.1:1234/?token=" + "x" * 20,
            "http://127.0.0.1:1234/?token=" + "x" * 20 + "#fragment",
        )
        with patch.object(artifact.http.client, "HTTPConnection") as connection:
            for address in addresses:
                with self.subTest(address=address), self.assertRaises(artifact.VerificationError):
                    artifact.Client({"bootstrap_url": address})
            connection.assert_not_called()

    def test_material_validation_checks_known_totals_digests_and_zip_members(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = material()
            result = artifact.check_material(raw, "0.3.1", root / "good")
            self.assertEqual(result, hashlib.sha256(raw).hexdigest())
            self.assertEqual((root / "good/evidence.zip").read_bytes(), raw)
            for label, raw, version in (
                ("wrong-cost", material(cost="0.570000002"), "0.3.1"),
                ("damaged-file", material(tamper=True), "0.3.1"),
                ("wrong-version", material(), "0.4.0"),
            ):
                with self.subTest(label=label), self.assertRaises(artifact.VerificationError):
                    artifact.check_material(raw, version, root / label)
            extra = io.BytesIO(material())
            with zipfile.ZipFile(extra, "a") as package:
                package.writestr("../unknown", b"unsafe")
            with self.assertRaises(artifact.VerificationError):
                artifact.check_material(extra.getvalue(), "0.3.1", root / "extra")
            self.assertFalse((root / "unknown").exists())

    def test_failure_report_does_not_copy_private_exception_text(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report = root / "report.json"
            arguments = ["verify_windows_artifact.py", "--exe", str(root), "--source-root",
                         str(root), "--data-root", str(root / "data"), "--report", str(report)]
            with patch("sys.argv", arguments), \
                    patch.object(artifact, "verify", side_effect=OSError("PRIVATE_TOKEN")), \
                    patch("sys.stderr", io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    artifact.main()
            self.assertEqual(error.exception.code, 1)
            result = json.loads(report.read_text("utf-8"))
            self.assertFalse(result["verified"])
            self.assertNotIn("PRIVATE_TOKEN", report.read_text("utf-8"))


if __name__ == "__main__":
    unittest.main()
