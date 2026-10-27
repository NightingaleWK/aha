from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from test_storage_helpers import detail, metadata, rollup

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

    def test_paths_use_their_own_platform_rules(self) -> None:
        self.assertEqual(canonical_path(r"C:\\Users\\NAME\\Repo\\..\\Repo\\"), "c:/users/name/repo")
        self.assertEqual(canonical_path(r"\\?\C:\Users\Name\Repo"), "c:/users/name/repo")
        self.assertEqual(canonical_path(r"\\?\UNC\Server\Share\Repo"), "//server/share/repo")
        self.assertEqual(canonical_path("/work/A/../Repo/"), "/work/Repo")
        self.assertNotEqual(canonical_path("/work/Repo"), canonical_path("/work/repo"))
        for invalid in ("relative/path", "C:relative", "", "\x00", "\\\\server"):
            with self.subTest(invalid=invalid), self.assertRaises(AppError):
                canonical_path(invalid)

    def test_component_boundary_longest_match_and_multiple_directories(self) -> None:
        parent = self.project("父项目", ["/work/a", r"C:\Work\A"])
        child = self.project("子项目", ["/work/a/child"])
        config = self.store.config()
        self.assertEqual(classify(detail(), metadata("/work/a/sub"), config)["project_id"], parent)
        self.assertEqual(
            classify(detail(), metadata("/work/a/child/sub"), config)["project_id"], child
        )
        self.assertEqual(
            classify(detail(), metadata(r"c:/WORK/a/sub"), config)["project_id"], parent
        )
        self.assertIsNone(classify(detail(), metadata("/work/abc"), config)["project_id"])
        self.assertIsNone(classify(detail(), metadata("/work/A/sub"), config)["project_id"])

    def test_duplicate_directory_binding_rejected_without_partial_change(self) -> None:
        self.project("一", [r"C:\work\a"])
        before = self.store.config()
        with self.assertRaises(AppError) as failure:
            self.project("二", [r"c:/WORK/a/"])
        self.assertEqual(failure.exception.code, "directory_conflict")
        self.assertEqual(self.store.config(), before)

    def test_manual_assignment_survives_rules_but_is_bound_to_original_content(self) -> None:
        first = self.project("自动", ["/work/a"])
        second = self.project("人工", [])
        row = detail()
        self.store.assign([row], second)
        assigned = classify(row, metadata(), self.store.config())
        self.assertEqual(
            (assigned["project_id"], assigned["assignment_origin"]), (second, "manual")
        )
        self.store.save_project(first, "已改名", "", ["/work/a", "/new"])
        self.assertEqual(classify(row, metadata(), self.store.config())["project_id"], second)
        changed_row = detail(total_cost_usd="8")
        self.assertEqual(
            classify(changed_row, metadata(), self.store.config())["project_id"], first
        )
        self.store.assign([row], None)
        restored = classify(row, metadata(), self.store.config())
        self.assertEqual(
            (restored["project_id"], restored["assignment_origin"]), (first, "directory_rule")
        )

    def test_complete_rollup_can_be_manually_assigned_but_no_directory_is_inferred(self) -> None:
        project = self.project("项目", ["/work/a"])
        row = rollup()
        self.assertIsNone(classify(row, metadata(), self.store.config(), "rollup")["project_id"])
        self.store.assign([row], project, "rollup")
        self.assertEqual(
            classify(row, metadata(), self.store.config(), "rollup")["project_id"], project
        )

    def test_conflict_and_missing_metadata_stay_unassigned(self) -> None:
        self.project("项目", ["/work/a"])
        for status in ("missing", "conflict"):
            meta = metadata()
            meta["sessions"]["s1"]["status"] = status
            self.assertIsNone(classify(detail(), meta, self.store.config())["project_id"])

    def test_linux_root_never_claims_windows_network_paths(self) -> None:
        linux = self.project("Linux", ["/"])
        self.assertEqual(
            classify(detail(), metadata("/work/a"), self.store.config())["project_id"], linux
        )
        self.assertIsNone(
            classify(detail(), metadata(r"\\server\share\a"), self.store.config())["project_id"]
        )

    def test_restart_preserves_project_name_multiple_directories_and_overrides(self) -> None:
        project = self.project("持久项目", ["/work/a", "/linux/repo", r"D:\Repo"])
        self.store.assign([detail()], project)
        before = self.store.config()
        self.store.close()
        self.store = Store(Path(self.temporary.name))
        self.assertEqual(self.store.config(), before)
        self.assertEqual(classify(detail(), {}, self.store.config())["assignment_origin"], "manual")
