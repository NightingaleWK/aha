"""Offline backup and restore must not create a service or touch default data."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_storage_helpers import metadata, source_data

from aha.storage import Store


class BackupCLITests(unittest.TestCase):
    def test_explicit_backup_and_restore_exit_without_starting_a_server(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data, archive, restored = root / "data", root / "full.aha-backup", root / "recovered"
            store = Store(data)
            try:
                store.sync_data(source_data(), metadata(), trust="live")
            finally:
                store.close()
            env = dict(
                os.environ,
                PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"),
                PYTHONUTF8="1",
            )
            command = [sys.executable, "-m", "aha"]
            for arguments, expected in (
                (["--data-dir", str(data), "--backup", str(archive)], "archive_path"),
                (["--restore-backup", str(archive), "--restore-dir", str(restored)], "destination"),
            ):
                result = subprocess.run(
                    command + arguments,
                    env=env,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=30,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(expected, json.loads(result.stdout))
                self.assertNotIn("AHA_URL", result.stdout)
            self.assertFalse((data / "runtime.json").exists())
            self.assertFalse((restored / "runtime.json").exists())
            self.assertFalse((data / ".instance.lock").exists())
            recovered = Store(restored)
            try:
                self.assertEqual(recovered.ledger_status()["counts"]["detail_count"], 1)
            finally:
                recovered.close()
            failure = subprocess.run(
                command + ["--restore-backup", str(archive), "--restore-dir", str(restored)],
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=30,
                check=False,
            )
            self.assertNotEqual(failure.returncode, 0)
            self.assertIn("还原目录已存在", failure.stderr)

    def test_invalid_offline_arguments_fail_before_creating_a_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "not-created"
            for arguments in (
                ["--restore-dir", str(missing)],
                ["--restore-backup", "missing.aha-backup"],
                [
                    "--restore-backup",
                    "missing.aha-backup",
                    "--restore-dir",
                    str(missing),
                    "--data-dir",
                    str(missing),
                ],
            ):
                result = subprocess.run(
                    [sys.executable, "-m", "aha", *arguments],
                    capture_output=True,
                    timeout=10,
                    check=False,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(missing.exists())
