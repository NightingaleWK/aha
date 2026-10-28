"""Project rules and manual assignment act on local indexed facts."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from test_storage_helpers import detail, metadata, rollup, source_data

from aha.domain import AppError
from aha.projects import canonical_path, classify
from aha.storage import Store


class ProjectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temporary.name))

    def tearDown(self) -> None:
        self.store.close()
        self.temporary.cleanup()

    def project(self, name: str, directories: list[str]) -> str:
        return self.store.save_project(None, name, "", directories)["project"]["id"]

    def row(self) -> dict:
        analysis = self.store.analyze("2026-10-01", "2026-10-31", availability_mode="all")
        return self.store.analysis_details(analysis)["rows"][0]

    def test_paths_use_their_own_platform_rules(self) -> None:
        self.assertEqual(canonical_path("C:/Users/NAME/Repo/../Repo/"), "c:/users/name/repo")
        self.assertEqual(canonical_path(r"\\?\C:\Users\Name\Repo"), "c:/users/name/repo")
        self.assertEqual(canonical_path(r"\\?\UNC\Server\Share\Repo"), "//server/share/repo")
        self.assertNotEqual(canonical_path("/work/Repo"), canonical_path("/work/repo"))
        for bad in ("relative/path", "C:relative", "", "\x00", r"\\server"):
            with self.assertRaises(AppError):
                canonical_path(bad)

    def test_longest_component_rule_and_atomic_conflict(self) -> None:
        parent = self.project("parent", ["/work/a"])
        child = self.project("child", ["/work/a/sub"])
        self.store.sync_data(source_data(), metadata("/work/a/sub/x"))
        self.assertEqual(self.row()["project_id"], child)
        before = self.store.config()
        with self.assertRaises(AppError):
            self.project("conflict", ["/work/a/"])
        self.assertEqual(self.store.config(), before)
        self.store.save_project(child, "child", "", ["/other"])
        self.assertEqual(self.row()["project_id"], parent)

    def test_manual_assignment_bound_to_content_and_persists_restart(self) -> None:
        auto = self.project("auto", ["/work/a"])
        manual = self.project("manual", [])
        self.store.sync_data(source_data(), metadata(), trust="live")
        self.store.assign([detail()], manual)
        self.assertEqual(self.row()["project_id"], manual)
        self.store.close()
        self.store = Store(Path(self.temporary.name))
        self.assertEqual(self.row()["assignment_origin"], "manual")
        self.store.sync_data(source_data([detail(total_cost_usd="8")]), metadata(), trust="live")
        self.assertEqual(self.row()["project_id"], auto)
        self.assertEqual(self.row()["assignment_origin"], "directory_rule")
        self.assertNotIn("overrides", self.store.config())

    def test_complete_rollup_assignment_is_whole_and_not_inferred(self) -> None:
        project = self.project("project", ["/work/a"])
        self.store.sync_data(source_data([], [rollup()]), metadata())
        analysis = self.store.analyze("2026-10-24", "2026-10-24")
        row = self.store.analysis_details(analysis, kind="rollup")["rows"][0]
        self.assertIsNone(row["project_id"])
        self.store.assign_keys([row["record_key"]], project)
        result = self.store.analyze("2026-10-24", "2026-10-24", project)
        self.assertEqual(result["summary"]["record_count"], 7)

    def test_multiple_session_assignment_is_one_transaction(self) -> None:
        project = self.project("manual", [])
        self.store.sync_data(
            source_data([detail("a", session_id="s1"), detail("b", session_id="s2")])
        )
        self.store.assign_sessions(["s1", "s2"], project)
        result = self.store.analyze("2026-10-26", "2026-10-26", project)
        self.assertEqual(result["summary"]["record_count"], 2)
        with self.assertRaises(AppError):
            self.store.assign_sessions(["s1", "s2"], "missing")
        self.assertEqual(
            self.store.analyze("2026-10-26", "2026-10-26", project)["summary"]["record_count"], 2
        )

    def test_missing_conflicting_metadata_and_component_case_rules(self) -> None:
        self.project("linux", ["/"])
        for status in ("missing", "conflict"):
            meta = metadata()
            meta["sessions"]["s1"]["status"] = status
            self.assertIsNone(classify(detail(), meta, self.store.config())["project_id"])
        self.assertIsNone(
            classify(detail(), metadata(r"\\server\share\a"), self.store.config())["project_id"]
        )
