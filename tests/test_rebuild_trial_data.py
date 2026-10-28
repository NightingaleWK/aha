"""One-time cleanup protects CCS inputs and requires complete historical preservation."""

from __future__ import annotations

import copy
import gzip
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from test_sources import detail, price

from aha.domain import build_source_data, content_hash
from scripts import build_windows
from scripts import rebuild_trial_data as rebuild


class RebuildTrialTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.data = self.root / "trial"
        self.data.mkdir()
        with closing(sqlite3.connect(self.data / "aha.sqlite3")) as db:
            db.execute("PRAGMA user_version=2")
            for name in ("settings", "projects", "captures", "batches"):
                db.execute(f"CREATE TABLE {name}(id TEXT)")
            db.commit()
        (self.data / "objects").mkdir()
        data = build_source_data([detail()], [], [price()], {})
        usage = {
            "format_version": 1,
            "adapter_version": 1,
            **{key: data[key] for key in ("schema_version", "details", "rollups", "pricing")},
        }
        self.usage = self.data / "objects" / ("usage-" + content_hash(usage) + ".json.gz")
        self.usage.write_bytes(gzip.compress(rebuild.canonical(usage)))
        (self.data / "cc-switch-history.sql").write_text("protected original")
        self.manifest = rebuild.inspect(self.data, [])
        self.extracted = self.root / "history"
        rebuild.extract(self.data, self.extracted)
        self.index = self.extracted / "history-index.json"
        self.backup = self.root / "backup"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def apply(self, manifest: dict | None = None) -> dict:
        return rebuild.apply_manifest(
            self.data, manifest or self.manifest, self.backup, self.index, []
        )

    def test_default_inspect_does_not_modify_trial_or_source_files(self) -> None:
        before = {
            p.relative_to(self.data): rebuild.fingerprint(p)
            for p in self.data.rglob("*")
            if p.is_file()
        }
        result = subprocess.run(
            [
                sys.executable,
                "scripts/rebuild_trial_data.py",
                "inspect",
                "--data-dir",
                str(self.data),
            ],
            capture_output=True,
            check=True,
        )
        manifest = json.loads(result.stdout)
        self.assertEqual(len(manifest["files"]), 2)
        self.assertIn("cc-switch-history.sql", manifest["untouched"])
        after = {
            p.relative_to(self.data): rebuild.fingerprint(p)
            for p in self.data.rglob("*")
            if p.is_file()
        }
        self.assertEqual(before, after)

    def test_extract_validates_content_and_preserves_only_usage_projection(self) -> None:
        _, entries = rebuild.read_index(self.index)
        self.assertEqual(len(entries), 1)
        entry = next(iter(entries.values()))
        value = rebuild.preserved_usage(self.extracted / entry["output_relative"])
        self.assertEqual(len(value["details"]), 1)
        self.assertEqual(value["source"]["kind"], "historical_projection")
        self.assertNotIn("batches", value)
        self.assertTrue(self.usage.exists())
        changed = self.root / "invalid-history"
        self.usage.write_bytes(gzip.compress(b'{"schema_version":23}'))
        with self.assertRaises(ValueError):
            rebuild.extract(self.data, changed)
        self.assertTrue((self.data / "aha.sqlite3").exists())

    def test_apply_copies_and_checks_every_file_before_cleanup_and_keeps_unknowns(self) -> None:
        hashes = {entry["relative"]: entry["sha256"] for entry in self.manifest["files"]}
        result = self.apply()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["removed_count"], 2)
        self.assertEqual((self.data / "cc-switch-history.sql").read_text(), "protected original")
        for relative, digest in hashes.items():
            self.assertFalse((self.data / relative).exists())
            self.assertEqual(rebuild.fingerprint(self.backup / relative), digest)
        self.assertTrue(self.index.exists())

    def test_stale_manifest_and_unpreserved_history_refuse_before_deletion(self) -> None:
        self.usage.write_bytes(self.usage.read_bytes() + b"changed")
        with self.assertRaises(ValueError):
            self.apply()
        self.assertTrue((self.data / "aha.sqlite3").exists())
        self.assertFalse(self.backup.exists())

    def test_history_output_tampering_refuses_even_with_changed_index_hash(self) -> None:
        index = json.loads(self.index.read_text())
        entry = index["entries"][0]
        target = self.extracted / entry["output_relative"]
        data = rebuild.preserved_usage(target)
        data["details"] = []
        target.write_bytes(gzip.compress(rebuild.canonical(data)))
        entry["output_sha256"] = rebuild.fingerprint(target)
        self.index.write_bytes(rebuild.canonical(index))
        with self.assertRaises(ValueError):
            self.apply()
        self.assertTrue(self.usage.exists())
        self.assertTrue((self.data / "aha.sqlite3").exists())

    def test_missing_history_index_entry_refuses_cleanup(self) -> None:
        self.index.write_bytes(rebuild.canonical({"format_version": 1, "entries": []}))
        with self.assertRaises(ValueError):
            self.apply()
        self.assertTrue((self.data / "aha.sqlite3").exists())

    def test_path_traversal_duplicate_and_source_candidates_are_rejected(self) -> None:
        for relative in (
            "../outside.db",
            "objects/../aha.sqlite3",
            "C:\\outside.db",
            "cc-switch-history.sql",
        ):
            manifest = copy.deepcopy(self.manifest)
            manifest["files"].append({"relative": relative, "sha256": "0" * 64, "bytes": 0})
            with self.subTest(relative=relative), self.assertRaises(ValueError):
                self.apply(manifest)
        manifest = copy.deepcopy(self.manifest)
        manifest["files"].append(manifest["files"][0])
        with self.assertRaises(ValueError):
            self.apply(manifest)
        self.assertTrue(self.usage.exists())

    def test_protected_source_and_nested_backup_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            rebuild.apply_manifest(self.data, self.manifest, self.backup, self.index, [self.data])
        with self.assertRaises(ValueError):
            rebuild.apply_manifest(self.data, self.manifest, self.data / "backup", self.index, [])
        self.assertTrue((self.data / "aha.sqlite3").exists())

    def test_live_process_refuses_cleanup_without_killing_it(self) -> None:
        (self.data / "runtime.json").write_text(json.dumps({"pid": os.getpid()}))
        manifest = rebuild.inspect(self.data, [])
        with self.assertRaises(ValueError):
            self.apply(manifest)
        self.assertTrue((self.data / "runtime.json").exists())
        self.assertTrue((self.data / "aha.sqlite3").exists())

    def test_manifest_protection_cannot_be_ignored_by_direct_apply(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["protected_sources"] = [str(self.data)]
        with self.assertRaises(ValueError):
            self.apply(manifest)
        self.assertFalse(self.backup.exists())
        self.assertTrue(self.usage.exists())

    def test_new_recognized_files_require_a_new_inspection(self) -> None:
        added = self.data / "objects" / ("metadata-" + "b" * 64 + ".json.gz")
        added.write_bytes(b"newly created trial object")
        with self.assertRaises(ValueError):
            self.apply()
        self.assertTrue(added.exists())
        self.assertTrue((self.data / "aha.sqlite3").exists())
        self.assertFalse(self.backup.exists())

    def test_foreign_or_new_business_schema_is_not_trial_data(self) -> None:
        with closing(sqlite3.connect(self.data / "aha.sqlite3")) as db:
            db.execute("PRAGMA user_version=3")
            db.commit()
        with self.assertRaises(ValueError):
            rebuild.inspect(self.data, [])
        with self.assertRaises(ValueError):
            self.apply()

    def test_symlink_candidate_cannot_escape_manifest(self) -> None:
        original = self.root / "outside"
        original.write_text("source original")
        link = self.data / "objects" / ("metadata-" + "a" * 64 + ".json.gz")
        try:
            link.symlink_to(original)
        except OSError:
            self.skipTest("OS does not permit symlink fixtures")
        manifest = copy.deepcopy(self.manifest)
        manifest["files"].append(
            {
                "relative": link.relative_to(self.data).as_posix(),
                "sha256": rebuild.fingerprint(original),
                "bytes": original.stat().st_size,
            }
        )
        with self.assertRaises(ValueError):
            self.apply(manifest)
        self.assertEqual(original.read_text(), "source original")

    def test_delete_failure_restores_removed_files_from_verified_backup(self) -> None:
        unlink = Path.unlink
        usage_name = self.usage.name

        def failing(path: Path, *args: object, **kwargs: object) -> None:
            if path.name == usage_name:
                raise OSError("simulated deletion failure")
            unlink(path, *args, **kwargs)

        with patch.object(Path, "unlink", failing), self.assertRaises(OSError):
            self.apply()
        for entry in self.manifest["files"]:
            path = self.data / entry["relative"]
            self.assertTrue(path.exists())
            self.assertEqual(rebuild.fingerprint(path), entry["sha256"])

    def test_windows_build_gate_uses_actual_sqlite_version(self) -> None:
        runtime = {"windows": True, "bits": 64, "isolated": True, "python": [3, 14]}
        for version, accepted in (
            ([3, 46, 1], False),
            ([3, 51, 2], False),
            ([3, 44, 6], True),
            ([3, 50, 7], True),
            ([3, 53, 1], True),
        ):
            payload = {**runtime, "sqlite": version}
            reply = subprocess.CompletedProcess([], 0, stdout=json.dumps(payload))
            with (
                self.subTest(version=version),
                patch.object(build_windows.subprocess, "run", return_value=reply),
            ):
                if accepted:
                    self.assertEqual(
                        build_windows.inspect_runtime(Path("python.exe"))["sqlite"], version
                    )
                else:
                    with self.assertRaises(ValueError):
                        build_windows.inspect_runtime(Path("python.exe"))


if __name__ == "__main__":
    unittest.main()
