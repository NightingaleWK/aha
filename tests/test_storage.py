from __future__ import annotations

import copy
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from test_storage_helpers import detail, metadata, rollup, source_data

from aha.domain import AppError
from aha.storage import Store


class StorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = Store(self.root)

    def tearDown(self) -> None:
        self.store.close()
        self.temporary.cleanup()

    def test_repeated_reads_reuse_objects_and_never_add_usage(self) -> None:
        data = source_data(rollups=[rollup()])
        first = self.store.retain(data, metadata())
        again = copy.deepcopy(data)
        again["source"]["observed_at"] = "2026-10-27T02:00:00+00:00"
        second = self.store.retain(again, metadata())
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(self.store.list_captures()), 1)
        self.assertEqual(
            second["counts"],
            {"detail_count": 1, "rollup_count": 1, "rollup_record_count": 7, "record_count": 8},
        )
        self.assertEqual(len(list((self.root / "objects").glob("*.gz"))), 2)
        self.assertEqual(len(self.store.get_capture(first["id"])["data"]["details"]), 1)

    def test_changed_content_and_metadata_create_separate_immutable_versions(self) -> None:
        old = self.store.retain(source_data(), metadata())
        changed = self.store.retain(source_data([detail(total_cost_usd="9.99")]), metadata())
        different_directory = self.store.retain(source_data(), metadata("/other"))
        self.assertNotEqual(old["id"], changed["id"])
        self.assertNotEqual(old["usage_snapshot_id"], changed["usage_snapshot_id"])
        self.assertEqual(old["usage_snapshot_id"], different_directory["usage_snapshot_id"])
        self.assertNotEqual(
            old["metadata_snapshot_id"], different_directory["metadata_snapshot_id"]
        )
        self.assertEqual(
            self.store.get_capture(old["id"])["data"]["details"][0]["total_cost_usd"], "0.1234567"
        )

    def test_restart_and_removed_source_need_only_the_retained_projection(self) -> None:
        original = self.root / "source.sql"
        original.write_text("synthetic original", encoding="utf-8")
        data = source_data()
        data["source"]["name"] = str(original)
        data["credentials"] = "SECRET-CONFIG"
        data["details"][0]["error_message"] = "SECRET-BODY"
        meta = metadata()
        meta["sessions"]["s1"]["body"] = "SECRET-CHAT"
        capture = self.store.retain(data, meta)
        self.store.close()
        original.unlink()
        self.store = Store(self.root)
        loaded = self.store.get_capture(capture["id"])
        self.assertEqual(loaded["source"]["name"], "source.sql")
        self.assertEqual(loaded["metadata"]["sessions"]["s1"]["cwd"], "/work/a")
        self.assertNotIn("SECRET", str(loaded))

    def test_failed_write_and_unindexed_object_are_not_successful_captures(self) -> None:
        original_writer = self.store._write_immutable
        calls = 0

        def fail_second(relative: str, raw: bytes) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise AppError("storage_write_failed", "合成写入失败", 500)
            original_writer(relative, raw)

        with patch.object(self.store, "_write_immutable", side_effect=fail_second):
            with self.assertRaises(AppError):
                self.store.retain(source_data(), metadata())
        self.assertEqual(self.store.list_captures(), [])
        self.assertEqual(len(list((self.root / "objects").glob("*.gz"))), 1)
        successful = self.store.retain(source_data(), metadata())
        self.assertEqual(len(self.store.list_captures()), 1)
        self.assertEqual(successful["counts"]["detail_count"], 1)

    def test_atomic_rename_failure_rolls_back_and_cleans_temporary_files(self) -> None:
        with patch("aha.storage.os.replace", side_effect=OSError("synthetic full disk")):
            with self.assertRaises(AppError) as failure:
                self.store.retain(source_data(), metadata())
        self.assertEqual(failure.exception.code, "storage_write_failed")
        self.assertEqual(self.store.list_captures(), [])
        self.assertEqual(list((self.root / "objects").iterdir()), [])

    def test_corruption_is_reported_and_never_replaced_by_new_source(self) -> None:
        capture = self.store.retain(source_data(), metadata())
        path = self.root / "objects" / f"usage-{capture['usage_snapshot_id']}.json.gz"
        path.write_bytes(b"corrupt")
        with self.assertRaises(AppError):
            self.store.get_capture(capture["id"])
        with self.assertRaises(AppError):
            self.store.retain(source_data(), metadata())
        self.assertEqual(path.read_bytes(), b"corrupt")
        self.assertEqual(len(self.store.list_captures()), 1)

    def test_unknown_archive_and_store_versions_are_rejected(self) -> None:
        capture = self.store.retain(source_data(), metadata())
        with patch("aha.archive.FORMAT_VERSION", 2):
            with self.assertRaises(AppError) as failure:
                self.store.get_capture(capture["id"])
        self.assertEqual(failure.exception.code, "unsupported_archive")
        self.store._db.execute("PRAGMA user_version=999")
        self.store.close()
        with self.assertRaises(AppError) as failure:
            Store(self.root)
        self.assertEqual(failure.exception.code, "unsupported_store")

    def test_concurrent_reads_share_one_capture_without_nested_transactions(self) -> None:
        with ThreadPoolExecutor(max_workers=6) as pool:
            captures = list(
                pool.map(lambda _: self.store.retain(source_data(), metadata()), range(12))
            )
        self.assertEqual(len({capture["id"] for capture in captures}), 1)
        self.assertEqual(len(self.store.list_captures()), 1)

    def test_duplicate_source_identity_cannot_be_retained(self) -> None:
        data = source_data()
        data["details"].append(copy.deepcopy(data["details"][0]))
        with self.assertRaises(AppError):
            self.store.retain(data, metadata())
        self.assertEqual(self.store.list_captures(), [])

    def test_metadata_keeps_safe_error_counts_and_only_required_sessions(self) -> None:
        meta = metadata()
        meta["sessions"]["unrelated"] = {"cwd": "/private/unrelated", "status": "matched"}
        meta["errors"] = [{"code": "root_unavailable", "count": 2, "path": "/private/error"}]
        capture = self.store.retain(source_data(), meta)
        loaded = self.store.get_capture(capture["id"])["metadata"]
        self.assertEqual(set(loaded["sessions"]), {"s1"})
        self.assertEqual(loaded["errors"], [{"code": "root_unavailable", "count": 2}])
        missing = self.store.retain(source_data(), {})
        restored = self.store.get_capture(missing["id"])["metadata"]
        self.assertEqual(restored["total_sessions"], 1)
        self.assertEqual(restored["matched_sessions"], 0)
        self.assertEqual(restored["sessions"]["s1"]["status"], "missing")
