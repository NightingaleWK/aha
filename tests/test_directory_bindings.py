"""Directory-wide adoption moves complete evidenced sets without changing usage facts."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from test_storage_helpers import claim, detail, metadata, rollup, source_data

from aha.domain import AppError, content_hash, record_key
from aha.projects import classify
from aha.storage import Store


class DirectoryBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temporary.name) / "data")

    def tearDown(self) -> None:
        self.store.close()
        self.temporary.cleanup()

    def preview(
        self,
        name: str = "目录项目",
        directories: list[str] | None = None,
        project_id: str | None = None,
    ) -> dict:
        draft = {"name": name, "directories": ["/work/a"] if directories is None else directories}
        if project_id:
            draft["project_id"] = project_id
        return self.store.preview_project_binding(draft)

    def apply(self, preview: dict, key: str | None = None) -> dict:
        return self.store.apply_project_binding(preview["preview_id"], key or uuid4().hex)

    def summary(self, project: str = "all") -> dict:
        return self.store.analyze("2026-10-01", "2026-10-31", project, availability_mode="all")[
            "summary"
        ]

    def test_preview_cancel_and_zero_history_then_later_records(self) -> None:
        preview = self.preview()
        self.assertEqual(preview["summary"]["detail_count"], 0)
        self.assertEqual(self.store.config()["projects"], [])
        result = self.apply(preview)
        project = result["project"]["id"]
        self.assertTrue(result["project"]["directory_managed"])
        self.store.sync_data(source_data(), metadata(), trust="live")
        self.assertEqual(self.summary(project)["record_count"], 1)
        self.assertEqual(
            self.store._db.execute("SELECT assignment_origin FROM usage_records").fetchone()[0],
            "directory_binding",
        )
        self.assertEqual(
            self.store._db.execute("SELECT COUNT(*) FROM session_project_bindings").fetchone()[0], 0
        )

    def test_complete_history_transfer_includes_manual_and_defaults_and_preserves_frozen(
        self,
    ) -> None:
        original = self.store.save_project(None, "原目录项目", "", ["/work/a"])["project"]["id"]
        other = self.store.save_project(None, "旧人工项目", "", [])["project"]["id"]
        rows = [detail(f"row-{i}") for i in range(80)]
        self.store.sync_data(source_data(rows), metadata(), trust="live")
        analysis = self.store.analyze("2026-10-01", "2026-10-31", original)
        batch = self.store.create_batch(analysis, claim(), "directory-frozen-batch-key")
        package, _ = self.store.download(batch["id"], 1)
        before_package = package.read_bytes()
        self.store.assign_keys([record_key(rows[0])], other)
        self.store.assign_sessions(["s1"], other)
        before = self.summary()
        facts = list(
            self.store._db.execute(
                "SELECT record_key,content_hash,total_cost_usd "
                "FROM usage_records ORDER BY record_key"
            )
        )
        claims = list(self.store._db.execute("SELECT * FROM usage_claims"))
        preview = self.preview()
        self.assertEqual(preview["summary"]["detail_count"], 80)
        self.assertEqual(preview["summary"]["changed_count"], 80)
        self.assertEqual(preview["summary"]["claimed_count"], 80)
        self.assertEqual(preview["transfers"][0]["from_project_id"], original)
        self.assertEqual(self.summary(other)["record_count"], 80)
        result = self.apply(preview)
        project = result["project"]["id"]
        self.assertEqual(self.summary(project)["record_count"], 80)
        self.assertEqual(self.summary(other)["record_count"], 0)
        self.assertEqual(self.summary(), before)
        self.assertEqual(
            list(
                self.store._db.execute(
                    "SELECT record_key,content_hash,total_cost_usd "
                    "FROM usage_records ORDER BY record_key"
                )
            ),
            facts,
        )
        self.assertEqual(list(self.store._db.execute("SELECT * FROM usage_claims")), claims)
        self.assertEqual(package.read_bytes(), before_package)
        self.assertEqual(self.store._db.execute("SELECT COUNT(*) FROM overrides").fetchone()[0], 0)
        self.assertEqual(
            self.store._db.execute("SELECT COUNT(*) FROM session_project_bindings").fetchone()[0], 0
        )
        self.assertEqual(
            next(p for p in result["projects"] if p["id"] == original)["directories"], []
        )
        self.store.sync_data(
            source_data([*rows, detail("future", created_at=rows[0]["created_at"] + 1)]),
            metadata(),
            trust="live",
        )
        self.assertEqual(self.summary(project)["record_count"], 81)

    def test_late_directory_replaces_null_baseline_and_old_mode_is_not_changed(self) -> None:
        project = self.apply(self.preview())["project"]["id"]
        missing = {"sessions": {"s1": {"cwd": None, "status": "missing", "parent_id": None}}}
        self.store.sync_data(source_data(), missing, trust="live")
        self.assertEqual(self.summary(project)["record_count"], 0)
        with patch("aha.session_meta.scan_metadata", return_value=metadata()):
            self.store.refresh_metadata([])
        self.assertEqual(self.summary(project)["record_count"], 1)
        self.store.refresh_metadata([Path(self.temporary.name) / "absent"])
        self.assertEqual(self.summary(project)["record_count"], 1)
        self.store.close()
        self.store = Store(Path(self.temporary.name) / "data")
        self.assertEqual(self.summary(project)["record_count"], 1)

    def test_legacy_saved_directory_remains_unconfirmed_until_explicit_adoption(self) -> None:
        self.store.sync_data(source_data(), metadata(), trust="live")
        legacy = self.store.save_project(None, "旧项目", "", ["/work/a"])["project"]
        self.assertFalse(legacy.get("directory_managed", False))
        self.assertEqual(self.summary(legacy["id"])["record_count"], 0)
        self.store.sync_data(source_data([detail(), detail("next")]), metadata(), trust="live")
        self.assertEqual(self.summary(legacy["id"])["record_count"], 1)
        self.apply(self.preview(project_id=legacy["id"]))
        self.assertEqual(self.summary(legacy["id"])["record_count"], 2)

    def test_repeat_configuration_does_not_repeat_assignment_events(self) -> None:
        self.store.sync_data(source_data(), metadata(), trust="live")
        project = self.apply(self.preview())["project"]["id"]
        before = self.store._db.execute(
            "SELECT COUNT(*) FROM project_assignment_events"
        ).fetchone()[0]
        repeat = self.preview(project_id=project)
        self.assertEqual(repeat["summary"]["changed_count"], 0)
        self.apply(repeat)
        self.assertEqual(
            self.store._db.execute("SELECT COUNT(*) FROM project_assignment_events").fetchone()[0],
            before,
        )

    def test_atomic_rollback_stale_digest_and_persistent_idempotency(self) -> None:
        self.store.sync_data(source_data(), metadata(), trust="live")
        preview = self.preview()
        with patch(
            "aha.ledger.refresh_availability", side_effect=RuntimeError("injected rollback")
        ):
            with self.assertRaises(RuntimeError):
                self.apply(preview)
        self.assertEqual(self.store.config()["projects"], [])
        self.assertEqual(self.summary("unassigned")["record_count"], 1)
        result = self.apply(preview, "project-binding-replay-operation")
        self.store.close()
        self.store = Store(Path(self.temporary.name) / "data")
        self.assertEqual(self.apply(preview, "project-binding-replay-operation"), result)
        stale = self.preview(project_id=result["project"]["id"])
        self.store.save_project(None, "other", "", [])
        with self.assertRaises(AppError) as caught:
            self.apply(stale)
        self.assertEqual(caught.exception.code, "project_binding_preview_expired")

    def test_manual_override_mutation_without_revision_invalidates_preview(self) -> None:
        self.store.sync_data(source_data(), metadata(), trust="live")
        other = self.store.save_project(None, "旧人工项目", "", [])["project"]["id"]
        preview = self.preview()
        self.store._db.execute(
            "INSERT INTO overrides VALUES(?,?,?)",
            (
                record_key(detail()),
                self.store._db.execute("SELECT content_hash FROM usage_records").fetchone()[0],
                other,
            ),
        )
        with self.assertRaises(AppError) as caught:
            self.apply(preview)
        self.assertEqual(caught.exception.code, "project_binding_preview_expired")

    def test_directory_overlap_boundaries_and_no_double_count_for_same_project_roots(self) -> None:
        self.store.save_project(None, "child", "", ["/work/a/child"])
        with self.assertRaises(AppError) as caught:
            self.preview()
        self.assertEqual(caught.exception.code, "directory_overlap_conflict")
        self.apply(self.preview(directories=["/work/another"]))
        project = self.apply(self.preview(directories=["/same", "/same/child"]))["project"]["id"]
        self.store.sync_data(source_data(), metadata("/same/child"), trust="live")
        repeat = self.preview(directories=["/same", "/same/child"], project_id=project)
        self.assertEqual(sum(d["detail_count"] for d in repeat["directories"]), 1)

    def test_retiring_directory_preserves_old_records_but_stops_future_and_legacy_guards(
        self,
    ) -> None:
        self.store.sync_data(source_data(), metadata(), trust="live")
        project = self.apply(self.preview())["project"]["id"]
        other = self.store.save_project(None, "other", "", [])["project"]["id"]
        with self.assertRaises(AppError) as caught:
            self.store.assign_keys([record_key(detail())], other)
        self.assertEqual(caught.exception.code, "directory_assignment_required")
        with self.assertRaises(AppError):
            self.store.assign_sessions(["s1"], other)
        with self.assertRaises(AppError):
            self.store.preview_associations(
                {"action": "assign", "project_id": other, "filters": {"project_id": project}}
            )
        with self.assertRaises(AppError):
            self.store.save_project(project, "目录项目", "", [])
        self.apply(self.preview(directories=[], project_id=project))
        self.store.sync_data(source_data([detail(), detail("future")]), metadata(), trust="live")
        self.assertEqual(self.summary(project)["record_count"], 1)
        self.assertEqual(self.summary("unassigned")["record_count"], 1)

    def test_pure_classification_matches_managed_directory_authority(self) -> None:
        target = "directory-owner"
        other = "old-manual"
        row = detail()
        config = {
            "projects": [
                {
                    "id": target,
                    "name": "目录",
                    "directories": ["/work/a"],
                    "directory_managed": True,
                },
                {"id": other, "name": "手工", "directories": []},
            ],
            "record_links": {record_key(row): {"project_id": other}},
        }
        self.assertEqual(classify(row, metadata(), config)["project_id"], target)

    def test_rollups_are_not_guessed_and_corrupt_policy_rejects(self) -> None:
        self.store.sync_data(source_data([detail()], [rollup()]), metadata(), trust="live")
        preview = self.preview()
        self.assertEqual(preview["summary"]["detail_count"], 1)
        self.apply(preview)
        self.assertEqual(
            self.store._db.execute(
                "SELECT project_id FROM usage_records WHERE kind='rollup'"
            ).fetchone()[0],
            "",
        )
        self.store._db.execute(
            "UPDATE settings SET value=? WHERE key='directory_assignment_policy'",
            (json.dumps({"version": 99, "projects": []}),),
        )
        with self.assertRaises(AppError) as caught:
            self.store.config()
        self.assertEqual(caught.exception.code, "invalid_directory_policy")

    def test_same_project_override_cleanup_is_audited_and_does_not_repeat(self) -> None:
        self.store.sync_data(source_data(), metadata(), trust="live")
        project = self.apply(self.preview())["project"]["id"]
        self.store._db.execute(
            "INSERT INTO overrides VALUES(?,?,?)",
            (
                record_key(detail()),
                self.store._db.execute("SELECT content_hash FROM usage_records").fetchone()[0],
                project,
            ),
        )
        before = self.store._db.execute(
            "SELECT COUNT(*) FROM project_assignment_events"
        ).fetchone()[0]
        preview = self.preview(project_id=project)
        self.assertEqual(preview["summary"]["changed_count"], 1)
        self.apply(preview)
        self.assertEqual(self.store._db.execute("SELECT COUNT(*) FROM overrides").fetchone()[0], 0)
        self.assertEqual(
            self.store._db.execute("SELECT COUNT(*) FROM project_assignment_events").fetchone()[0],
            before + 1,
        )
        self.assertEqual(self.preview(project_id=project)["summary"]["changed_count"], 0)

    def test_limits_fail_whole_directory_without_configuration_changes(self) -> None:
        data = source_data([detail("a", session_id="s1"), detail("b", session_id="s2")])
        metas = metadata()
        metas["sessions"]["s2"] = {"cwd": "/work/a/sub", "status": "matched", "parent_id": None}
        self.store.sync_data(data, metas, trust="live")
        for setting in ("MAX_RECORDS", "MAX_SESSIONS", "MAX_METADATA"):
            with self.subTest(setting=setting), patch("aha.associations." + setting, 1):
                with self.assertRaises(AppError) as caught:
                    self.preview()
                self.assertIn(
                    caught.exception.code, {"assignment_too_large", "assignment_metadata_limit"}
                )
                self.assertEqual(self.store.config()["projects"], [])

    def test_unique_historical_directory_recovers_without_files_then_device_directory_adds(
        self,
    ) -> None:
        self.store.sync_data(source_data(), metadata("/old/repo"), trust="live")
        missing = {"cwd": None, "status": "missing", "parent_id": None}
        self.store._db.execute(
            "UPDATE sessions SET cwd=NULL,status='missing',content_hash=?", (content_hash(missing),)
        )
        preview = self.preview(directories=["/old/repo"])
        self.assertEqual(preview["summary"]["recovered_sessions"], 1)
        project = self.apply(preview)["project"]["id"]
        self.assertEqual(
            self.store._db.execute("SELECT cwd FROM sessions").fetchone()[0], "/old/repo"
        )
        self.apply(self.preview(directories=["/old/repo", "/new/repo"], project_id=project))
        new = detail("new-machine", session_id="s2", created_at=detail()["created_at"] + 1)
        metas = metadata("/old/repo")
        metas["sessions"]["s2"] = {"cwd": "/new/repo", "status": "matched", "parent_id": None}
        self.store.sync_data(source_data([detail(), new]), metas, trust="live")
        self.assertEqual(self.summary(project)["record_count"], 2)

    def test_backup_restore_preserves_managed_mode_and_future_matching(self) -> None:
        project = self.apply(self.preview())["project"]["id"]
        self.store.sync_data(source_data(), metadata(), trust="live")
        archive = Path(self.temporary.name) / "complete.aha-backup"
        destination = Path(self.temporary.name) / "restored"
        self.store.create_backup(archive)
        Store.restore_backup(archive, destination)
        restored = Store(destination)
        try:
            self.assertTrue(restored.config()["projects"][0]["directory_managed"])
            restored.sync_data(source_data([detail(), detail("future")]), metadata(), trust="live")
            result = restored.analyze("2026-10-01", "2026-10-31", project, availability_mode="all")
            self.assertEqual(result["summary"]["record_count"], 2)
        finally:
            restored.close()

    def test_windows_normalization_transfer_and_linux_prefix_boundary(self) -> None:
        project = self.apply(self.preview(directories=["C:/Work/Repo"]))["project"]["id"]
        self.store.sync_data(source_data(), metadata(r"c:\work\REPO\child"), trust="live")
        self.assertEqual(self.summary(project)["record_count"], 1)
        other = self.apply(self.preview(name="转移", directories=[r"c:\work\repo"]))
        self.assertEqual(other["summary"]["detail_count"], 1)
        self.assertEqual(self.summary(other["project"]["id"])["record_count"], 1)
        self.apply(self.preview(directories=["/work/ab"]))
        self.apply(self.preview(directories=["/work/a"]))

    def test_cost_revision_and_new_alias_keep_directory_owner(self) -> None:
        project = self.apply(self.preview())["project"]["id"]
        self.store.sync_data(source_data(), metadata(), trust="live")
        self.store.sync_data(
            source_data([detail(total_cost_usd="9.123456789")]), metadata(), trust="live"
        )
        self.assertEqual(self.summary(project)["total_cost_usd"], "9.123456789")
        self.store.sync_data(
            source_data([detail("renamed-key", total_cost_usd="9.123456789")]),
            metadata(),
            trust="live",
        )
        case = self.store._db.execute(
            "SELECT id,generation FROM reconciliation_cases WHERE type='identity' AND state='open'"
        ).fetchone()
        self.assertIsNotNone(case)
        self.store.resolve_reconciliation(
            case["id"], "same", "核实相同消费", expected_generation=case["generation"]
        )
        self.assertEqual(self.summary(project)["record_count"], 1)
        self.assertEqual(self.summary(project)["total_cost_usd"], "9.123456789")
