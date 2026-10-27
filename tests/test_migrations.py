from __future__ import annotations

import hashlib
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from migration_fixtures import OLD_INSERT, OLD_UPDATE, legacy_analysis, legacy_store, seed_revision
from test_storage_helpers import detail, source_data

from aha.batches import add_members
from aha.claims import evaluate
from aha.domain import AppError
from aha.storage import Store


class MigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.legacy = legacy_store(self.root)
        self.upgraded = None

    def tearDown(self) -> None:
        self.legacy.close()
        if self.upgraded is not None:
            self.upgraded.close()
        self.temporary.cleanup()

    def version(self) -> int:
        with closing(sqlite3.connect(self.root / "aha.sqlite3")) as connection:
            return connection.execute("PRAGMA user_version").fetchone()[0]

    def test_single_draft_upgrade_keeps_project_package_and_valid_backup(self) -> None:
        self.legacy.save_project(None, "项目甲", "原说明", ["/work/a"])
        analysis = legacy_analysis(self.legacy)
        first = seed_revision(self.legacy, "a", 1, 1, analysis)
        self.upgraded = Store(self.root)
        self.assertEqual(self.version(), 2)
        self.assertEqual(self.upgraded.config()["projects"][0]["name"], "项目甲")
        self.assertEqual(self.upgraded.batch_detail("a")["lifecycle"], "active")
        self.assertEqual(len(self.upgraded.claim_snapshot()["claims"]), 1)
        self.assertEqual(self.upgraded.download("a", 1), (first["package"], first["filename"]))
        backup = list((self.root / "backups").glob("*.sqlite3"))
        self.assertEqual(len(backup), 1)
        with closing(sqlite3.connect(backup[0])) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM revisions").fetchone()[0], 1)
            self.assertEqual(connection.execute("PRAGMA quick_check").fetchone()[0], "ok")
        self.upgraded.close()
        self.upgraded = Store(self.root)
        self.assertEqual(len(list((self.root / "backups").glob("*.sqlite3"))), 1)

    def test_old_cached_insert_and_update_cannot_bypass_new_protocol(self) -> None:
        analysis = legacy_analysis(self.legacy)
        first = seed_revision(self.legacy, "a", 1, 1, analysis)
        self.legacy._db.execute(OLD_UPDATE, ("draft", "old", "a", 1))
        self.upgraded = Store(self.root)
        with self.assertRaises(sqlite3.IntegrityError):
            self.legacy._db.execute(OLD_UPDATE, ("submitted", "new", "a", 1))
        values = list(first["values"])
        values[1] = 2
        with self.assertRaises(sqlite3.IntegrityError):
            self.legacy._db.execute(OLD_INSERT, values)
        changed = self.upgraded.set_status("a", 1, "submitted", 1)
        self.assertEqual(changed["status"], "submitted")
        self.assertEqual(len(self.upgraded.batch_detail("a")["revisions"]), 1)

    def test_cross_batch_conflict_and_old_paid_members_are_all_held_until_explicit_resolution(
        self,
    ) -> None:
        one = legacy_analysis(self.legacy)
        two = legacy_analysis(
            self.legacy, source_data([detail("r2", created_at=detail()["created_at"] + 10)])
        )
        first = seed_revision(self.legacy, "a", 1, 1, one, status="reimbursed")
        seed_revision(self.legacy, "a", 1, 2, two)
        seed_revision(self.legacy, "b", 2, 1, one)
        self.upgraded = Store(self.root)
        self.assertEqual(self.upgraded.batch_detail("a")["lifecycle"], "legacy_review")
        self.assertEqual(self.upgraded.batch_detail("b")["lifecycle"], "legacy_review")
        snapshot = self.upgraded.claim_snapshot()
        self.assertEqual(snapshot["claims"], [])
        self.assertEqual(len(snapshot["legacy_holds"]), 3)
        self.assertEqual(evaluate(one["members"] + two["members"], snapshot)["available_keys"], [])
        with self.assertRaises(AppError):
            self.upgraded.resolve_legacy("a", 1, 1, "保留真实已报销版本", "resolve-before")
        self.upgraded.void_batch("b", 1, "重复申请作废", "void-b")
        # Removing one holder must not free any of A's still-undecided members.
        snapshot = self.upgraded.claim_snapshot()
        self.assertEqual(len(snapshot["legacy_holds"]), 2)
        self.assertEqual(evaluate(one["members"] + two["members"], snapshot)["available_keys"], [])
        resolved = self.upgraded.resolve_legacy(
            "a", 1, 1, "核对后保留v1，v2为误建草稿", "resolve-a"
        )
        self.assertEqual((resolved["active_version"], resolved["status"]), (1, "reimbursed"))
        snapshot = self.upgraded.claim_snapshot()
        self.assertEqual(len(snapshot["claims"]), 1)
        self.assertEqual(snapshot["legacy_holds"], [])
        self.assertEqual(
            evaluate(two["members"], snapshot)["available_keys"], [two["members"][0]["key"]]
        )
        self.assertEqual(self.upgraded.download("a", 1)[0], first["package"])
        self.assertFalse(self.upgraded.batch_detail("a")["revisions"][1]["is_effective"])

    def test_multiple_old_drafts_require_explicit_effective_version(self) -> None:
        first = legacy_analysis(self.legacy)
        seed_revision(self.legacy, "a", 1, 1, first)
        seed_revision(self.legacy, "a", 1, 2, first, purpose="另一申请金额说明")
        self.upgraded = Store(self.root)
        self.assertEqual(self.upgraded.batch_detail("a")["lifecycle"], "legacy_review")
        self.assertIsNone(self.upgraded.batch_detail("a")["active_version"])
        chosen = self.upgraded.resolve_legacy("a", 2, 1, "确认最新草稿为准", "resolve")
        self.assertEqual(chosen["active_version"], 2)

    def test_corrupt_members_and_package_cancel_upgrade_instead_of_becoming_empty(self) -> None:
        data = legacy_analysis(self.legacy)
        original = seed_revision(self.legacy, "a", 1, 1, data)
        self.legacy._db.execute("UPDATE revisions SET members_json='[]'")
        with self.assertRaises(AppError):
            Store(self.root)
        self.assertEqual(self.version(), 1)
        self.assertEqual(hashlib.sha256(original["package"]).hexdigest(), original["values"][10])
        self.assertEqual(self.legacy._db.execute("SELECT COUNT(*) FROM revisions").fetchone()[0], 1)
        columns = [row[1] for row in self.legacy._db.execute("PRAGMA table_info(revisions)")]
        self.assertNotIn("claim_protocol", columns)

    def test_backup_and_partial_backfill_failure_leave_schema1_intact(self) -> None:
        data = legacy_analysis(self.legacy)
        first = seed_revision(self.legacy, "a", 1, 1, data)
        with patch.object(Store, "_backup_v1", side_effect=AppError("backup_failed", "测试失败")):
            with self.assertRaises(AppError):
                Store(self.root)
        self.assertEqual(self.version(), 1)

        def inserted_then_fail(*args: object, **kwargs: object) -> None:
            add_members(*args, **kwargs)  # type: ignore[arg-type]
            raise AppError("synthetic", "合成提交前失败")

        with patch("aha.batches.add_members", side_effect=inserted_then_fail):
            with self.assertRaises(AppError):
                Store(self.root)
        self.assertEqual(self.version(), 1)
        self.assertIsNone(
            self.legacy._db.execute(
                "SELECT name FROM sqlite_master WHERE name='usage_claims'"
            ).fetchone()
        )
        self.assertEqual((self.root / first["values"][9]).read_bytes(), first["package"])

    def test_backup_includes_committed_wal_and_never_rewrites_legacy_package(self) -> None:
        self.legacy._db.execute("PRAGMA journal_mode=WAL")
        data = legacy_analysis(self.legacy)
        original = seed_revision(self.legacy, "a", 1, 1, data)
        self.upgraded = Store(self.root)
        self.assertEqual(self.upgraded.download("a", 1)[0], original["package"])
        backup = next((self.root / "backups").glob("*.sqlite3"))
        with closing(sqlite3.connect(backup)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM revisions").fetchone()[0], 1)
            self.assertEqual(
                connection.execute("SELECT status FROM revisions").fetchone()[0], "draft"
            )

    def test_corrupt_package_is_not_rebuilt_during_upgrade(self) -> None:
        data = legacy_analysis(self.legacy)
        original = seed_revision(self.legacy, "a", 1, 1, data)
        package = self.root / original["values"][9]
        package.write_bytes(b"damaged original")
        with self.assertRaises(AppError) as failure:
            Store(self.root)
        self.assertEqual(failure.exception.code, "migration_damaged")
        self.assertEqual(self.version(), 1)
        self.assertEqual(package.read_bytes(), b"damaged original")

    def test_inconsistent_member_fields_do_not_silently_rebuild_an_occupancy(self) -> None:
        import json

        data = legacy_analysis(self.legacy)
        seed_revision(self.legacy, "a", 1, 1, data)
        members = json.loads(
            self.legacy._db.execute("SELECT members_json FROM revisions").fetchone()[0]
        )
        members[0]["date"] = "2026-10-25"
        self.legacy._db.execute("UPDATE revisions SET members_json=?", (json.dumps(members),))
        with self.assertRaises(AppError) as failure:
            Store(self.root)
        self.assertEqual(failure.exception.code, "migration_damaged")
        self.assertEqual(self.version(), 1)
