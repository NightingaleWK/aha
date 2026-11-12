"""A copied ledger retains facts, claims and directory evidence on a new device."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from test_sources import database
from test_storage_helpers import claim, detail, metadata, rollup, source_data

from aha import source_bindings
from aha.domain import ROLLUP_FIELDS, AppError, content_hash, record_key
from aha.storage import Store


class DeviceContinuityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = Store(self.root / "ledger")
        self.source = self.root / "synthetic-ccs.db"
        self.enterContext(patch(
            "aha.source_bindings.installation_id", return_value="new-computer"
        ))

    def tearDown(self) -> None:
        self.store.close()
        self.temporary.cleanup()

    def query(self, project: str = "all") -> dict:
        return self.store.analyze("2026-10-01", "2026-10-31", project)

    def make_source(
        self, rows: list[dict] | None = None, rollups: list[dict] | None = None
    ) -> None:
        if self.source.exists():
            self.source.unlink()
        with closing(database(self.source, rows or [], version=25)) as connection:
            for row in rollups or []:
                connection.execute(
                    "INSERT INTO usage_daily_rollups VALUES ("
                    + ",".join("?" for _ in ROLLUP_FIELDS) + ")",
                    [row[key] for key in ROLLUP_FIELDS],
                )
            connection.commit()

    def old_source(self, rows: list[dict] | None = None) -> None:
        self.make_source([detail()] if rows is None else rows)
        self.store.sync_sqlite(self.source, installation_id="old-computer")

    def test_same_path_new_machine_requires_confirmation_without_quarantining_history(self) -> None:
        self.old_source()
        before = self.store.ledger_status()
        with self.store.read_connection() as connection:
            runs = connection.execute("SELECT COUNT(*) FROM sync_runs").fetchone()[0]
        status = self.store.source_binding_status(self.source)
        self.assertTrue(status["required"])
        self.assertFalse(status["bound"])
        self.assertNotIn("installation_id", status)
        self.assertNotIn(str(self.root), str(status))
        with self.assertRaises(AppError) as error:
            self.store.sync_sqlite(self.source)
        self.assertEqual(error.exception.code, "source_binding_required")
        self.assertEqual(self.store.ledger_status(), before)
        self.assertEqual(self.query()["summary"]["record_count"], 1)
        self.assertEqual(self.store.list_reconciliations(), [])
        with self.store.read_connection() as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM sync_runs").fetchone()[0], runs
            )

    def test_explicit_new_device_keeps_global_keys_claims_and_original_package(self) -> None:
        self.old_source()
        old = self.store.sync_status()["source_id"]
        project = self.store.save_project(None, "原项目", "", [])['project']['id']
        self.store.assign_keys([record_key(detail())], project)
        saved = self.store.create_batch(self.query(), claim(), "old-device-claim")
        package, _ = self.store.download(saved["id"], 1)
        before_sha = hashlib.sha256(package.read_bytes()).hexdigest()
        self.make_source([detail(), detail("new", created_at=detail()["created_at"] + 1)])
        binding = self.store.bind_source(self.source, "新电脑接续，旧电脑已停用")
        self.assertNotEqual(binding["source_id"], old)
        result = self.store.sync_sqlite(self.source)
        self.assertEqual((result["new_count"], result["unchanged_count"]), (1, 1))
        self.assertEqual(result["source_schema_version"], 25)
        self.assertEqual(self.query()["summary"]["record_count"], 1)
        self.assertEqual(self.query(project)["summary"]["record_count"], 0)
        with self.store.read_connection() as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM usage_records").fetchone()[0], 2
            )
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM usage_claims").fetchone()[0], 1
            )
        same = self.store.sync_sqlite(self.source)
        self.assertEqual((same["new_count"], same["revised_count"]), (0, 0))
        restored_package, _ = self.store.download(saved["id"], 1)
        self.assertEqual(hashlib.sha256(restored_package.read_bytes()).hexdigest(), before_sha)

    def test_empty_new_source_preserves_history_and_repeated_binding_is_idempotent(self) -> None:
        self.old_source()
        self.make_source([])
        binding = self.store.bind_source(self.source, "新电脑当前无用量，保留历史")
        again = self.store.bind_source(self.source, "重复提交")
        self.assertEqual(binding["source_id"], again["source_id"])
        for _ in range(2):
            self.assertEqual(self.store.sync_sqlite(self.source)["new_count"], 0)
        self.assertEqual(self.query()["summary"]["record_count"], 1)
        self.assertEqual(self.store.list_reconciliations(), [])

    def test_legacy_path_profile_is_not_adopted_as_current_device_authority(self) -> None:
        self.make_source([detail()])
        legacy = content_hash(["sqlite", str(self.source.resolve())])
        old = source_data()
        old["source"] = {"kind": "sqlite", "name": self.source.name,
                         "location": str(self.source.resolve())}
        self.store.sync_data(old, metadata(), source_id=legacy, trust="live")
        self.assertTrue(self.store.source_binding_status(self.source)["required"])
        new = self.store.bind_source(self.source, "确认独立新电脑来源")
        self.assertNotEqual(new["source_id"], legacy)
        self.make_source([detail(total_cost_usd="0.01")])
        for _ in range(2):
            self.assertEqual(self.store.sync_sqlite(self.source)["revised_count"], 0)
        case = self.store.list_reconciliations()[0]
        self.assertEqual(case["type"], "revision")
        self.store.resolve_reconciliation(case["id"], "current", "保留历史原值")
        self.assertEqual(self.query()["summary"]["total_cost_usd"], "0.1234567")
        self.store.sync_sqlite(self.source)
        self.assertEqual(self.query()["summary"]["total_cost_usd"], "0.1234567")

    def test_restore_marker_requires_rebinding_even_on_same_machine(self) -> None:
        self.make_source([detail()])
        first = self.store.sync_sqlite(self.source)
        marker = self.store.data_dir / "restore-info.json"
        marker.write_text(json.dumps({"format_version": 1, "restore_id": str(uuid4())}))
        self.assertTrue(self.store.source_binding_status(self.source)["required"])
        with self.assertRaises(AppError):
            self.store.sync_sqlite(self.source)
        rebound = self.store.bind_source(self.source, "确认本次独立还原后的来源")
        self.assertNotEqual(rebound["source_id"], first["source_id"])
        self.assertFalse(self.store.source_binding_status(self.source)["required"])
        self.assertEqual(self.store.sync_sqlite(self.source)["unchanged_count"], 1)

    def test_bad_restore_or_binding_metadata_fails_without_changing_history(self) -> None:
        self.old_source()
        before = self.store.revisions()
        marker = self.store.data_dir / "restore-info.json"
        for invalid in ('{"format_version":1}', "[" * 1200 + "0" + "]" * 1200):
            marker.write_text(invalid)
            with self.assertRaises(AppError) as error:
                self.store.source_binding_status(self.source)
            self.assertEqual(error.exception.code, "source_binding_damaged")
        marker.unlink()
        with self.store._transaction():
            self.store._db.execute("UPDATE settings SET value='[]' WHERE key=?",
                                   (source_bindings.SETTINGS_KEY,))
        with self.assertRaises(AppError) as error:
            self.store.sync_sqlite(self.source)
        self.assertEqual(error.exception.code, "source_binding_damaged")
        self.assertEqual(self.store.revisions(), before)
        self.assertEqual(self.query()["summary"]["record_count"], 1)

    def test_equal_rollups_from_another_source_need_origin_review(self) -> None:
        self.make_source([], [rollup()])
        self.store.sync_sqlite(self.source, installation_id="old-computer")
        self.store.bind_source(self.source, "新电脑来源与旧汇总范围待核对")
        result = self.store.sync_sqlite(self.source)
        self.assertEqual(result["new_count"], 0)
        case = self.store.list_reconciliations()[0]
        self.assertEqual(case["type"], "rollup_origin")
        self.assertEqual(case["choices"], ["current"])
        self.store.resolve_reconciliation(case["id"], "current", "确认是复制的同份历史汇总")
        self.assertEqual(self.query()["summary"]["record_count"], 7)
        self.store.sync_sqlite(self.source)
        self.assertEqual(self.store.list_reconciliations(), [])
        self.assertEqual(self.query()["summary"]["record_count"], 7)

    def test_new_machine_smaller_rollup_does_not_replace_old_day_on_repeat(self) -> None:
        self.make_source([], [rollup(request_count=100)])
        self.store.sync_sqlite(self.source, installation_id="old-computer")
        self.make_source([], [rollup(request_count=10)])
        self.store.bind_source(self.source, "新电脑只提供了部分同日用量")
        for _ in range(2):
            result = self.store.sync_sqlite(self.source)
            self.assertEqual(result["revised_count"], 0)
            with self.store.read_connection() as connection:
                self.assertEqual(connection.execute(
                    "SELECT request_count FROM usage_records WHERE kind='rollup'"
                ).fetchone()[0], "100")
        case = self.store.list_reconciliations()[0]
        self.assertEqual(case["type"], "revision")
        self.store.resolve_reconciliation(case["id"], "current", "保留旧设备已保存的完整日")
        self.store.sync_sqlite(self.source)
        self.assertEqual(self.query()["summary"]["record_count"], 100)
        self.assertEqual(self.store.list_reconciliations(), [])

    def test_refresh_on_new_machine_keeps_old_cwd_project_and_metadata_version(self) -> None:
        project = self.store.save_project(None, "原项目", "", ["/old/repo"])["project"]["id"]
        self.store.sync_data(source_data(), metadata("/old/repo"), trust="live")
        with self.store.read_connection() as connection:
            before = tuple(connection.execute(
                "SELECT cwd,status,content_hash FROM sessions"
            ).fetchone())
            count = connection.execute(
                "SELECT COUNT(*) FROM session_metadata_versions"
            ).fetchone()[0]
        self.store.refresh_metadata([self.root / "new-computer-without-old-logs"])
        self.assertEqual(self.query(project)["summary"]["record_count"], 1)
        with self.store.read_connection() as connection:
            current = connection.execute("SELECT cwd,status,content_hash FROM sessions").fetchone()
            self.assertEqual(tuple(current), before)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM session_metadata_versions")
                             .fetchone()[0], count)

    def test_different_directory_is_a_candidate_until_explicitly_accepted(self) -> None:
        old = self.store.save_project(None, "旧目录项目", "", ["/old/repo"])["project"]["id"]
        new = self.store.save_project(None, "新目录项目", "", ["/new/repo"])["project"]["id"]
        self.store.sync_data(source_data(), metadata("/old/repo"), trust="live")
        with patch("aha.session_meta.scan_metadata", return_value=metadata("/new/repo")):
            self.store.refresh_metadata([])
        self.assertEqual(self.query(old)["summary"]["record_count"], 1)
        case = self.store.list_reconciliations()[0]
        self.assertEqual(case["type"], "directory")
        self.assertEqual(case["choices"], ["current", "candidate"])
        self.store.resolve_reconciliation(case["id"], "candidate", "核实新目录同一项目迁移")
        self.assertEqual(self.query(new)["summary"]["record_count"], 1)
        self.assertEqual(self.query(old)["summary"]["record_count"], 0)

    def test_keep_historical_directory_does_not_reopen_the_same_candidate(self) -> None:
        self.store.sync_data(source_data(), metadata("/old/repo"), trust="live")
        with patch("aha.session_meta.scan_metadata", return_value=metadata("/new/repo")):
            self.store.refresh_metadata([])
            case = self.store.list_reconciliations()[0]
            self.store.resolve_reconciliation(case["id"], "current", "保留原电脑已保存的目录")
            revisions = self.store.revisions()
            self.store.refresh_metadata([])
        self.assertEqual(self.store.list_reconciliations(), [])
        self.assertEqual(self.store.revisions(), revisions)
        with self.store.read_connection() as connection:
            self.assertEqual(
                connection.execute("SELECT cwd FROM sessions").fetchone()[0], "/old/repo"
            )

    def test_auxiliary_metadata_change_keeps_directory_candidates_actionable(self) -> None:
        self.store.sync_data(source_data(), metadata("/old/repo"), trust="live")
        self.store.sync_data(source_data(), metadata("/new/repo"), trust="live")
        original = self.store.list_reconciliations()[0]
        same_directory = metadata("/old/repo")
        same_directory["sessions"]["s1"]["parent_id"] = "newly-known-parent"
        self.store.sync_data(source_data(), same_directory, trust="live")
        current = self.store.list_reconciliations()
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0]["candidate_cwd"], "/new/repo")
        with self.assertRaises(AppError) as failure:
            self.store.resolve_reconciliation(
                original["id"], "candidate", "迟到旧依据", original["generation"]
            )
        self.assertEqual(failure.exception.code, "stale_case")
        self.store.resolve_reconciliation(
            current[0]["id"], "candidate", "核对刷新后的目录依据", current[0]["generation"]
        )
        self.assertEqual(self.store.list_reconciliations(), [])
        with self.store.read_connection() as connection:
            self.assertEqual(connection.execute("SELECT cwd FROM sessions").fetchone()[0],
                             "/new/repo")

    def test_ambiguous_current_directory_cannot_replace_a_known_historical_directory(self) -> None:
        self.store.sync_data(source_data(), metadata("/old/repo"), trust="live")
        observed = metadata()
        observed["sessions"]["s1"].update(status="conflict", cwd=None)
        with patch("aha.session_meta.scan_metadata", return_value=observed):
            self.store.refresh_metadata([])
        case = self.store.list_reconciliations()[0]
        self.assertEqual(case["choices"], ["current"])
        with self.assertRaises(AppError) as error:
            self.store.resolve_reconciliation(case["id"], "candidate", "不能采用冲突结果")
        self.assertEqual(error.exception.code, "invalid_candidate")
        self.assertEqual(self.query()["summary"]["record_count"], 1)
        self.store.resolve_reconciliation(case["id"], "current", "保留原机器的确定目录")

    def test_accepting_directory_invalidates_older_candidate_generation(self) -> None:
        self.store.sync_data(source_data(), metadata("/old/repo"), trust="live")
        for cwd in ("/candidate/one", "/candidate/two"):
            with patch("aha.session_meta.scan_metadata", return_value=metadata(cwd)):
                self.store.refresh_metadata([])
        first, second = self.store.list_reconciliations()
        self.store.resolve_reconciliation(
            second["id"], "candidate", "核实第二个目录", second["generation"]
        )
        self.assertEqual(self.store.list_reconciliations(), [])
        with self.assertRaises(AppError) as error:
            self.store.resolve_reconciliation(
                first["id"], "candidate", "迟到的旧目录确认", first["generation"]
            )
        self.assertEqual(error.exception.code, "stale_case")
        with patch("aha.session_meta.scan_metadata", return_value=metadata("/candidate/one")):
            self.store.refresh_metadata([])
        renewed = self.store.list_reconciliations()[0]
        self.assertNotEqual(renewed["id"], first["id"])
        self.assertEqual(renewed["current_cwd"], "/candidate/two")


class InstallationIdentityTests(unittest.TestCase):
    def test_installation_identity_is_stable_outside_the_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            file = Path(root) / "private-device" / "installation.json"
            with patch("aha.source_bindings._state_file", return_value=file):
                first = source_bindings.installation_id()
                self.assertEqual(len(first), 32)
                self.assertEqual(source_bindings.installation_id(), first)
                file.write_text('{"format_version":0,"id":"bad"}')
                with self.assertRaises(AppError) as error:
                    source_bindings.installation_id()
                self.assertEqual(error.exception.code, "device_identity_unavailable")
                self.assertNotIn(str(file), error.exception.message)


if __name__ == "__main__":
    unittest.main()
