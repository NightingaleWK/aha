"""Complete recovery snapshots use synthetic ledgers and never default data paths."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
import tempfile
import threading
import unittest
import zipfile
from contextlib import closing
from pathlib import Path
from typing import Any
from unittest.mock import patch

from billing_fixtures import frozen_analysis
from test_storage_helpers import claim, detail, metadata, source_data

from aha import backup
from aha.domain import AppError, record_key
from aha.storage import Store


class BackupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.data = self.root / "data"
        self.store = Store(self.data)
        self.store.save_project(None, "恢复项目", "保留用途", ["/work/a"])
        self.store.sync_data(source_data(), metadata(), trust="live")
        self.archive = self.root / "complete.aha-backup"
        self.restored = self.root / "restored"

    def tearDown(self) -> None:
        self.store.close()
        self.temporary.cleanup()

    def assert_code(self, code: str, callback: Any) -> None:
        with self.assertRaises(AppError) as failure:
            callback()
        self.assertEqual(failure.exception.code, code)

    def rows(self, store: Store, table: str) -> list[tuple[Any, ...]]:
        with store.read_connection() as connection:
            return [
                tuple(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY rowid")
            ]

    def repack(self, changes: Any) -> Path:
        with zipfile.ZipFile(self.archive) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
        changes(files)
        target = self.root / "modified.aha-backup"
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, value in files.items():
                archive.writestr(name, value)
        return target

    def mutate_database(self, sql: str) -> Path:
        def change(files: dict[str, bytes]) -> None:
            path = self.root / "editable.sqlite3"
            path.write_bytes(files["aha.sqlite3"])
            with closing(sqlite3.connect(path)) as connection:
                connection.executescript(sql)
                connection.commit()
            files["aha.sqlite3"] = path.read_bytes()
            value = json.loads(files["manifest.json"])
            entry = next(entry for entry in value["files"] if entry["path"] == "aha.sqlite3")
            entry.update(
                size=len(files["aha.sqlite3"]),
                sha256=hashlib.sha256(files["aha.sqlite3"]).hexdigest(),
            )
            files["manifest.json"] = json.dumps(value).encode()

        return self.repack(change)

    def test_complete_restore_keeps_projects_claims_all_revisions_and_original_packages(
        self,
    ) -> None:
        project = self.store.config()["projects"][0]
        self.store.assign_keys([record_key(detail())], project["id"])
        first = self.store.create_batch(
            self.store.analyze("2026-10-26", "2026-10-26"), claim(), "original"
        )
        revised = self.store.create_batch(
            frozen_analysis(self.store, first["id"]),
            claim(purpose="完整保留历史版本"),
            "revision",
            first["id"],
            expected_generation=first["generation"],
            expected_active_version=first["version"],
        )
        self.store.void_batch(revised["id"], revised["generation"], "保留作废原包", "void")
        active = self.store.create_batch(
            self.store.analyze("2026-10-26", "2026-10-26"), claim(), "active"
        )
        packages = {path.name: path.read_bytes() for path in (self.data / "packages").iterdir()}
        self.assertEqual(len(packages), 3)
        object_path = self.data / "objects" / "retained" / "projection.bin"
        object_path.parent.mkdir()
        object_path.write_bytes(b"synthetic persistent object")
        (self.data / "runtime.json").write_text("private-running-token")
        (self.data / ".instance.lock").write_bytes(b"")
        (self.data / "temporary" / "unfinished.tmp").write_bytes(b"not recovery data")
        result = self.store.create_backup(self.archive)
        self.assertEqual(result["counts"]["revisions"], 3)
        with zipfile.ZipFile(self.archive) as archive:
            names = archive.namelist()
            self.assertNotIn("runtime.json", names)
            self.assertNotIn(".instance.lock", names)
            self.assertFalse(any(name.startswith("temporary/") for name in names))
            self.assertEqual(len([name for name in names if name.startswith("packages/")]), 3)
        restored = Store.restore_backup(self.archive, self.restored)
        self.assertEqual(restored["archive_sha256"], result["sha256"])
        self.assertEqual(restored["interrupted_runs"], 0)
        with zipfile.ZipFile(self.archive) as archive:
            manifest = json.loads(archive.read("manifest.json"))
        database_hash = next(
            entry["sha256"] for entry in manifest["files"] if entry["path"] == "aha.sqlite3"
        )
        self.assertEqual(
            hashlib.sha256((self.restored / "aha.sqlite3").read_bytes()).hexdigest(), database_hash
        )
        marker = json.loads((self.restored / "restore-info.json").read_text())
        self.assertEqual(marker["archive_sha256"], result["sha256"])
        self.assertTrue(marker["restore_id"])
        self.assertEqual(
            (self.restored / "objects/retained/projection.bin").read_bytes(),
            object_path.read_bytes(),
        )
        recovered = Store(self.restored)
        try:
            for table in (
                "settings",
                "projects",
                "overrides",
                "sessions",
                "usage_records",
                "usage_versions",
                "record_evidence",
                "reconciliation_events",
                "batches",
                "revisions",
                "revision_members",
                "usage_claims",
                "batch_events",
            ):
                with self.subTest(table=table):
                    self.assertEqual(self.rows(recovered, table), self.rows(self.store, table))
            self.assertEqual(recovered.batch_detail(first["id"])["lifecycle"], "voided")
            self.assertEqual(recovered.batch_detail(active["id"])["lifecycle"], "active")
            self.assertEqual(
                recovered.analyze("2026-10-26", "2026-10-26")["summary"]["record_count"], 0
            )
            for row in self.rows(recovered, "revisions"):
                batch_id, version = row[0], row[1]
                path, _ = recovered.download(batch_id, version)
                self.assertEqual(path.read_bytes(), packages[path.name])
        finally:
            recovered.close()

    def test_committed_wal_is_included_without_checkpointing_the_live_database(self) -> None:
        self.store._db.execute("PRAGMA wal_autocheckpoint=0")
        self.store.sync_data(
            source_data([detail(), detail("new", output_tokens=90)]), metadata(), trust="live"
        )
        wal = self.data / "aha.sqlite3-wal"
        self.assertTrue(wal.is_file())
        before = wal.read_bytes()
        self.store.create_backup(self.archive)
        self.assertEqual(wal.read_bytes(), before)
        backup.restore_backup(self.archive, self.restored)
        recovered = Store(self.restored)
        try:
            self.assertEqual(recovered.ledger_status()["counts"]["detail_count"], 2)
        finally:
            recovered.close()

    def test_file_generation_uses_the_snapshot_and_does_not_hold_the_writer(self) -> None:
        original = backup._add_file
        changed = False
        failures: list[BaseException] = []

        def writer() -> None:
            try:
                with closing(sqlite3.connect(self.data / "aha.sqlite3", timeout=1)) as connection:
                    connection.execute("INSERT INTO settings VALUES('after_snapshot','new')")
                    connection.commit()
            except BaseException as error:
                failures.append(error)

        def add_file(*args: Any, **kwargs: Any) -> dict[str, Any]:
            nonlocal changed
            if not changed:
                changed = True
                thread = threading.Thread(target=writer)
                thread.start()
                thread.join(timeout=3)
                self.assertFalse(thread.is_alive(), "backup file generation blocked the writer")
                self.assertEqual(failures, [])
            return original(*args, **kwargs)

        with patch("aha.backup._add_file", side_effect=add_file):
            self.store.create_backup(self.archive)
        backup.restore_backup(self.archive, self.restored)
        with closing(sqlite3.connect(self.restored / "aha.sqlite3")) as connection:
            self.assertIsNone(
                connection.execute(
                    "SELECT value FROM settings WHERE key='after_snapshot'"
                ).fetchone()
            )
        self.assertEqual(
            self.store._db.execute(
                "SELECT value FROM settings WHERE key='after_snapshot'"
            ).fetchone()[0],
            "new",
        )

    def test_restore_ends_only_volatile_running_sync_and_preserves_published_rows(self) -> None:
        run = self.store._db.execute("SELECT id FROM sync_runs LIMIT 1").fetchone()[0]
        with self.store._transaction():
            self.store._db.execute(
                "UPDATE sync_runs SET state='running',completed_at=NULL WHERE id=?", (run,)
            )
            self.store._db.execute(
                "INSERT INTO sync_stage VALUES(?,?,'detail','staged','{}')", (run, "unpublished")
            )
            self.store._db.execute("INSERT INTO sync_pricing VALUES(?,'staged','{}')", (run,))
        facts, versions = (
            self.rows(self.store, "usage_records"),
            self.rows(self.store, "usage_versions"),
        )
        self.store.create_backup(self.archive)
        digest = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        result = backup.restore_backup(self.archive, self.restored)
        self.assertEqual(result["interrupted_runs"], 1)
        self.assertEqual(hashlib.sha256(self.archive.read_bytes()).hexdigest(), digest)
        self.assertEqual(
            self.store._db.execute("SELECT state FROM sync_runs WHERE id=?", (run,)).fetchone()[0],
            "running",
        )
        recovered = Store(self.restored)
        try:
            self.assertEqual(self.rows(recovered, "usage_records"), facts)
            self.assertEqual(self.rows(recovered, "usage_versions"), versions)
            self.assertEqual(
                recovered._db.execute("SELECT count(*) FROM sync_stage").fetchone()[0], 0
            )
            self.assertEqual(
                recovered._db.execute("SELECT count(*) FROM sync_pricing").fetchone()[0], 0
            )
            self.assertEqual(
                recovered._db.execute(
                    "SELECT state,error_code FROM sync_runs WHERE id=?", (run,)
                ).fetchone()[:],
                ("failed", "sync_interrupted"),
            )
            self.assertEqual(
                recovered.sync_data(source_data(), metadata(), trust="live")["unchanged_count"], 1
            )
        finally:
            recovered.close()

    def test_existing_destinations_and_nested_application_output_are_never_overwritten(
        self,
    ) -> None:
        self.archive.write_bytes(b"keep original")
        self.assert_code("backup_exists", lambda: self.store.create_backup(self.archive))
        self.assertEqual(self.archive.read_bytes(), b"keep original")
        self.assert_code(
            "invalid_backup_destination",
            lambda: self.store.create_backup(self.data / "packages" / "not-a-material.zip"),
        )
        self.archive.unlink()
        self.store.create_backup(self.archive)
        self.restored.mkdir()
        (self.restored / "keep.txt").write_text("user data")
        self.assert_code(
            "restore_destination_exists", lambda: backup.restore_backup(self.archive, self.restored)
        )
        self.assertEqual((self.restored / "keep.txt").read_text(), "user data")

    def test_restore_cannot_be_nested_inside_another_application_profile(self) -> None:
        self.store.create_backup(self.archive)
        target = self.data / "temporary" / "not-a-safe-profile"
        self.assert_code(
            "invalid_restore_destination", lambda: backup.restore_backup(self.archive, target)
        )
        self.assertFalse(target.exists())

    def test_racing_output_creation_never_overwrites_the_new_owner(self) -> None:
        publish_file = backup._publish_file

        def file_race(source: Path, destination: Path) -> None:
            destination.write_bytes(b"another backup")
            publish_file(source, destination)

        with patch("aha.backup._publish_file", side_effect=file_race):
            self.assert_code("backup_exists", lambda: self.store.create_backup(self.archive))
        self.assertEqual(self.archive.read_bytes(), b"another backup")
        self.archive.unlink()
        self.store.create_backup(self.archive)
        publish_directory = backup._publish_directory

        def directory_race(source: Path, destination: Path) -> None:
            destination.mkdir()
            publish_directory(source, destination)

        with patch("aha.backup._publish_directory", side_effect=directory_race):
            self.assert_code(
                "restore_destination_exists",
                lambda: backup.restore_backup(self.archive, self.restored),
            )
        self.assertEqual(list(self.restored.iterdir()), [])
        self.assertEqual(list(self.root.glob(".aha-restore-*")), [])

    def test_cancellation_after_file_work_removes_only_owned_staging(self) -> None:
        cancelled = threading.Event()
        add = backup._add_file

        def cancel_after_add(*args: Any, **kwargs: Any) -> dict[str, Any]:
            result = add(*args, **kwargs)
            cancelled.set()
            return result

        with patch("aha.backup._add_file", side_effect=cancel_after_add):
            self.assert_code(
                "backup_cancelled", lambda: self.store.create_backup(self.archive, cancel=cancelled)
            )
        self.assertFalse(self.archive.exists())
        self.assertEqual(list(self.root.glob(".aha-backup-*")), [])
        cancelled.clear()
        self.store.create_backup(self.archive)
        extract = backup._extract

        def cancel_after_extract(*args: Any, **kwargs: Any) -> None:
            extract(*args, **kwargs)
            cancelled.set()

        with patch("aha.backup._extract", side_effect=cancel_after_extract):
            self.assert_code(
                "backup_cancelled",
                lambda: backup.restore_backup(self.archive, self.restored, cancel=cancelled),
            )
        self.assertFalse(self.restored.exists())
        self.assertEqual(list(self.root.glob(".aha-restore-*")), [])
        self.assertEqual(self.store.ledger_status()["counts"]["detail_count"], 1)

    def test_missing_package_cannot_be_hidden_by_removing_its_manifest_entry(self) -> None:
        self.store.create_batch(self.store.analyze("2026-10-26", "2026-10-26"), claim(), "saved")
        self.store.create_backup(self.archive)

        def remove_package(files: dict[str, bytes]) -> None:
            value = json.loads(files["manifest.json"])
            package = next(
                record["path"]
                for record in value["files"]
                if record["path"].startswith("packages/")
            )
            del files[package]
            value["files"] = [record for record in value["files"] if record["path"] != package]
            files["manifest.json"] = json.dumps(value).encode()

        corrupted = self.repack(remove_package)
        self.assert_code("invalid_backup", lambda: backup.restore_backup(corrupted, self.restored))
        self.assertFalse(self.restored.exists())

    def test_missing_or_changed_original_package_blocks_backup_without_partial_output(self) -> None:
        saved = self.store.create_batch(
            self.store.analyze("2026-10-26", "2026-10-26"), claim(), "one"
        )
        path, _ = self.store.download(saved["id"], 1)
        path.write_bytes(b"damaged")
        self.assert_code("backup_file_changed", lambda: self.store.create_backup(self.archive))
        self.assertFalse(self.archive.exists())
        self.assertEqual(list(self.root.glob(".aha-backup-*")), [])
        self.assertEqual(
            self.store._db.execute("SELECT count(*) FROM usage_claims").fetchone()[0], 1
        )

    def test_bad_manifest_or_unlisted_members_do_not_publish_a_restored_directory(self) -> None:
        self.store.create_backup(self.archive)
        for extra in ("../escape", "packages\\bad.zip", "packages/CON.zip", "unlisted.txt"):
            with self.subTest(member=extra):
                corrupted = self.repack(lambda files: files.update({extra: b"unsafe"}))
                self.assert_code(
                    "invalid_backup", lambda: backup.restore_backup(corrupted, self.restored)
                )
                self.assertFalse(self.restored.exists())
                self.assertFalse((self.root / "escape").exists())
                self.assertEqual(list(self.root.glob(".aha-restore-*")), [])
        corrupted = self.repack(lambda files: files.update({"aha.sqlite3": b"changed"}))
        self.assert_code("invalid_backup", lambda: backup.restore_backup(corrupted, self.restored))

    def test_duplicate_and_symlink_zip_members_are_rejected(self) -> None:
        self.store.create_backup(self.archive)
        with zipfile.ZipFile(self.archive) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
        for mode in ("duplicate", "symlink"):
            corrupted = self.root / (mode + ".aha-backup")
            with zipfile.ZipFile(corrupted, "w") as archive:
                for name, raw in files.items():
                    archive.writestr(name, raw)
                if mode == "duplicate":
                    with self.assertWarns(UserWarning):
                        archive.writestr("aha.sqlite3", files["aha.sqlite3"])
                else:
                    info = zipfile.ZipInfo("objects/link")
                    info.create_system = 3
                    info.external_attr = (stat.S_IFLNK | 0o777) << 16
                    archive.writestr(info, "../../outside")
            self.assert_code(
                "invalid_backup", lambda: backup.restore_backup(corrupted, self.restored)
            )
            self.assertFalse(self.restored.exists())

    def test_manifest_duplicate_fields_and_wrong_hash_are_rejected(self) -> None:
        self.store.create_backup(self.archive)
        corrupted = self.repack(
            lambda files: files.update({"manifest.json": b'{"format":1,"format":2}'})
        )
        self.assert_code("invalid_backup", lambda: backup.restore_backup(corrupted, self.restored))

        def wrong_hash(files: dict[str, bytes]) -> None:
            value = json.loads(files["manifest.json"])
            value["files"][0]["sha256"] = "0" * 64
            files["manifest.json"] = json.dumps(value).encode()

        corrupted = self.repack(wrong_hash)
        self.assert_code("invalid_backup", lambda: backup.restore_backup(corrupted, self.restored))
        self.assertFalse(self.restored.exists())

    def test_valid_file_hash_cannot_hide_wrong_schema_or_broken_foreign_keys(self) -> None:
        project = self.store.config()["projects"][0]
        self.store.assign_keys([record_key(detail())], project["id"])
        self.store.create_backup(self.archive)
        for sql, code in (
            ("PRAGMA user_version=99;", "unsupported_backup_store"),
            ("DELETE FROM projects;", "invalid_backup"),
            (
                "CREATE TRIGGER evil AFTER INSERT ON settings "
                "BEGIN DELETE FROM usage_records; END;",
                "invalid_backup",
            ),
        ):
            with self.subTest(sql=sql):
                corrupted = self.mutate_database(sql)
                self.assert_code(code, lambda: backup.restore_backup(corrupted, self.restored))
                self.assertFalse(self.restored.exists())
        self.assertEqual(self.store._db.execute("SELECT count(*) FROM projects").fetchone()[0], 1)

    def test_bounded_input_expansion_and_file_count(self) -> None:
        self.store.create_backup(self.archive)
        for constant in (
            "MAX_ARCHIVE_BYTES",
            "MAX_EXPANDED_BYTES",
            "MAX_ENTRIES",
            "MAX_CENTRAL_BYTES",
        ):
            with self.subTest(constant=constant), patch("aha.backup." + constant, 1):
                self.assert_code(
                    "backup_too_large", lambda: backup.restore_backup(self.archive, self.restored)
                )
            self.assertFalse(self.restored.exists())
        with patch("aha.backup.MAX_EXPANDED_BYTES", 1):
            self.assert_code(
                "backup_too_large", lambda: self.store.create_backup(self.root / "too-large.zip")
            )

    def test_changed_index_constraints_cannot_make_a_restored_ledger_unusable(self) -> None:
        self.store.create_backup(self.archive)
        for sql in (
            "CREATE UNIQUE INDEX unexpected_source_kind ON source_profiles(kind);",
            "DROP INDEX one_sync_running;",
            "DROP INDEX one_sync_running; "
            "CREATE INDEX one_sync_running ON sync_runs(state) WHERE state='running';",
            "DROP INDEX usage_time; "
            "CREATE INDEX usage_time ON usage_records(record_key,event_time);",
        ):
            with self.subTest(sql=sql):
                corrupted = self.mutate_database(sql)
                self.assert_code(
                    "invalid_backup", lambda: backup.restore_backup(corrupted, self.restored)
                )
                self.assertFalse(self.restored.exists())
                self.assertEqual(list(self.root.glob(".aha-restore-*")), [])
        self.assertEqual(self.store.ledger_status()["counts"]["detail_count"], 1)

    def test_cancel_and_publication_failure_leave_original_data_and_no_staging(self) -> None:
        cancelled = threading.Event()
        cancelled.set()
        self.assert_code(
            "backup_cancelled", lambda: self.store.create_backup(self.archive, cancel=cancelled)
        )
        self.assertFalse(self.archive.exists())
        self.store.create_backup(self.archive)
        self.assert_code(
            "backup_cancelled",
            lambda: backup.restore_backup(self.archive, self.restored, cancel=cancelled),
        )
        with patch("aha.backup._publish_directory", side_effect=OSError("private failure path")):
            self.assert_code(
                "invalid_backup", lambda: backup.restore_backup(self.archive, self.restored)
            )
        self.assertFalse(self.restored.exists())
        self.assertEqual(list(self.root.glob(".aha-restore-*")), [])
        self.assertEqual(self.store.ledger_status()["counts"]["detail_count"], 1)

    def test_unknown_persistent_root_file_and_object_symlink_require_inspection(self) -> None:
        unknown = self.data / "unknown-important.bin"
        unknown.write_bytes(b"do not lose")
        self.assert_code("backup_unknown_files", lambda: self.store.create_backup(self.archive))
        self.assertEqual(unknown.read_bytes(), b"do not lose")
        unknown.unlink()
        outside = self.root / "private.bin"
        outside.write_bytes(b"not an object")
        link = self.data / "objects" / "link"
        try:
            os.symlink(outside, link)
        except OSError:
            self.skipTest("This Windows account cannot create a symlink")
        self.assert_code("invalid_backup", lambda: self.store.create_backup(self.archive))
        self.assertFalse(self.archive.exists())
