"""Project association decisions survive source absence and operate on exact full selections."""

from __future__ import annotations

import base64
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_storage_helpers import claim, detail, metadata, rollup, source_data

from aha.domain import AppError, content_hash, record_key
from aha.storage import Store


class AssociationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temporary.name))

    def tearDown(self) -> None:
        self.store.close()
        self.temporary.cleanup()

    def project(self, name: str, directories: list[str] | None = None) -> str:
        return self.store.save_project(None, name, "", directories or [])["project"]["id"]

    def query(self, project: str = "all") -> dict:
        return self.store.analyze("2026-10-01", "2026-10-31", project, availability_mode="all")

    def apply(self, preview: dict, key: str = "association-test-operation") -> dict:
        return self.store.apply_associations(preview["preview_id"], "核实消费所属项目", key)

    def lose_directory_as_legacy_refresh_did(self) -> None:
        missing = {"cwd": None, "status": "missing", "parent_id": None}
        with self.store._transaction():
            self.store._db.execute(
                "UPDATE sessions SET status='missing',cwd=NULL,content_hash=?",
                (content_hash(missing),),
            )
            self.store._db.execute(
                "UPDATE record_project_links SET project_id=NULL,basis='unassigned'"
            )
            self.store._db.execute(
                "UPDATE usage_records SET project_id='',assignment_origin='unassigned',cwd=NULL"
            )
            self.store._db.execute(
                "INSERT INTO session_metadata_versions("
                "session_id,content_hash,payload_json,created_at) "
                "VALUES('s1',?,?,?)",
                (content_hash(missing), self.store._encode(missing), self.store._now()),
            )
            from aha.ledger import refresh_availability

            refresh_availability(self.store._db)
            self.store._advance_revision()

    def test_unique_retained_directory_recovers_without_any_codex_file_and_replays(self) -> None:
        project = self.project("历史项目", ["/old/repo"])
        self.store.sync_data(source_data(), metadata("/old/repo"), trust="live")
        self.lose_directory_as_legacy_refresh_did()
        before = self.query()["summary"]
        status = self.store.association_status()
        self.assertEqual(status["summary"]["recoverable_sessions"], 1)
        self.assertEqual(status["summary"]["unassigned_detail_count"], 1)
        records = self.store.association_records({"reason": "recoverable"})["rows"]
        self.assertEqual(records[0]["cwd"], "/old/repo")
        preview = self.store.preview_associations({"action": "recover"})
        self.assertEqual(self.query(project)["summary"]["record_count"], 0)
        self.assertEqual(preview["summary"]["recovered_sessions"], 1)
        result = self.apply(preview)
        self.assertEqual(result["recovered_sessions"], 1)
        self.assertEqual(self.query(project)["summary"]["record_count"], 1)
        self.assertEqual(self.query()["summary"], before)
        self.assertEqual(self.apply(preview), result)
        self.store.refresh_metadata([Path(self.temporary.name) / "absent-old-logs"])
        self.assertEqual(self.query(project)["summary"]["record_count"], 1)
        self.assertEqual(
            self.store._db.execute("SELECT COUNT(*) FROM reconciliation_events").fetchone()[0], 1
        )

    def test_unique_directory_without_project_is_retained_as_an_actionable_unassigned_group(
        self,
    ) -> None:
        self.store.sync_data(source_data(), metadata("/old/unbound"), trust="live")
        self.lose_directory_as_legacy_refresh_did()
        preview = self.store.preview_associations({"action": "recover"})
        self.assertEqual(preview["summary"]["directory_only_sessions"], 1)
        self.apply(preview)
        status = self.store.association_status()
        self.assertEqual(status["summary"]["unassigned_detail_count"], 1)
        self.assertEqual(status["groups"][0]["reason"], "directory_unbound")
        self.assertEqual(
            self.store._db.execute("SELECT cwd FROM sessions").fetchone()[0], "/old/unbound"
        )

    def test_recovery_excludes_matched_new_machine_records_without_project_rules(self) -> None:
        self.project("旧项目", ["/old/repo"])
        self.store.sync_data(source_data(), metadata("/old/repo"), trust="live")
        self.lose_directory_as_legacy_refresh_did()
        new = detail("new-machine", session_id="s2")
        observed = {
            "sessions": {"s2": {"cwd": "/new/unbound", "status": "matched", "parent_id": None}}
        }
        self.store.sync_data(source_data([detail(), new]), observed, trust="live")
        status = self.store.association_status()
        self.assertEqual(status["summary"]["recoverable_sessions"], 1)
        self.assertEqual(status["summary"]["directory_only_sessions"], 0)
        preview = self.store.preview_associations({"action": "recover"})
        self.assertEqual(preview["summary"]["selected_detail_count"], 1)
        self.assertEqual(preview["summary"]["session_count"], 1)
        self.assertEqual(preview["summary"]["directory_only_sessions"], 0)
        self.apply(preview)
        remaining = self.store.association_records({})["rows"]
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["session_id"], "s2")
        self.assertEqual(remaining[0]["reason"], "directory_unbound")

    def test_explicit_session_focus_can_recover_beyond_global_metadata_scan_limit(self) -> None:
        self.project("旧项目", ["/old/repo"])
        rows = [detail("first", session_id="s1"), detail("second", session_id="s2")]
        observed = {
            "sessions": {
                sid: {"cwd": "/old/repo", "status": "matched", "parent_id": None}
                for sid in ("s1", "s2")
            }
        }
        self.store.sync_data(source_data(rows), observed, trust="live")
        self.lose_directory_as_legacy_refresh_did()
        with patch("aha.associations.MAX_METADATA", 1):
            self.assertTrue(self.store.association_status()["metadata_scan_truncated"])
            preview = self.store.preview_associations({"action": "recover", "session_ids": ["s2"]})
            self.assertEqual(preview["summary"]["recovered_sessions"], 1)
            self.apply(preview)
        statuses = dict(self.store._db.execute("SELECT id,status FROM sessions"))
        self.assertEqual(statuses, {"s1": "missing", "s2": "matched"})

    def test_conflicting_historical_directories_are_never_selected_by_recency(self) -> None:
        self.project("历史项目", ["/old/repo"])
        self.store.sync_data(source_data(), metadata("/old/repo"), trust="live")
        self.lose_directory_as_legacy_refresh_did()
        other = {"cwd": "/another/repo", "status": "matched", "parent_id": None}
        self.store._db.execute(
            "INSERT INTO session_metadata_versions("
            "session_id,content_hash,payload_json,created_at) "
            "VALUES('s1',?,?,?)",
            (content_hash(other), self.store._encode(other), self.store._now()),
        )
        self.assertEqual(self.store.association_status()["summary"]["ambiguous_sessions"], 1)
        with self.assertRaises(AppError) as failure:
            self.store.preview_associations({"action": "recover"})
        self.assertEqual(failure.exception.code, "empty_assignment")
        self.assertEqual(
            self.store._db.execute("SELECT status FROM sessions").fetchone()[0], "missing"
        )

    def test_metadata_limit_never_treats_unchecked_sessions_as_missing_filter_members(self) -> None:
        project = self.project("目标项目")
        self.store.sync_data(
            source_data([detail("first", session_id="s1"), detail("second", session_id="s2")]),
            {"sessions": {
                sid: {"status": "matched", "cwd": "/known/repo", "parent_id": None}
                for sid in ("s1", "s2")
            }}, trust="live",
        )
        revisions = self.store.revisions()
        with patch("aha.associations.MAX_METADATA", 1):
            status = self.store.association_status()
            self.assertTrue(status["metadata_scan_truncated"])
            self.assertTrue(status["groups_truncated"])
            self.assertEqual(status["summary"]["unassigned_detail_count"], 2)
            self.assertEqual(sum(group["detail_count"] for group in status["groups"]), 1)
            self.assertTrue(all(group["reason"] == "directory_unbound"
                                for group in status["groups"]))
            for filters in ({"reason": "missing"}, {"reason": "directory_unbound"},
                            {"directory": "/known/repo"}):
                with self.subTest(filters=filters):
                    with self.assertRaises(AppError) as reading:
                        self.store.association_records(filters)
                    self.assertEqual(reading.exception.code, "assignment_metadata_limit")
                    with self.assertRaises(AppError) as previewing:
                        self.store.preview_associations({
                            "action": "assign", "project_id": project, "filters": filters,
                        })
                    self.assertEqual(previewing.exception.code, "assignment_metadata_limit")
            self.assertEqual(self.store.revisions(), revisions)
            focused = self.store.association_records({"session_id": "s2"})["rows"]
            self.assertEqual(focused[0]["reason"], "directory_unbound")
            first = self.store.association_records({}, size=1)
            second = self.store.association_records({}, cursor=first["next_cursor"], size=1)
            self.assertEqual(second["rows"][0]["reason"], "directory_unbound")
            self.assertEqual(second["rows"][0]["cwd"], "/known/repo")
            explicit = self.store.preview_associations({"action": "assign", "project_id": project})
            self.assertEqual(explicit["summary"]["selected_detail_count"], 2)
            self.apply(explicit)
        self.assertEqual(self.query(project)["summary"]["record_count"], 2)

    def test_whole_filtered_selection_includes_rows_beyond_the_visible_page(self) -> None:
        project = self.project("项目")
        self.store.sync_data(
            source_data([detail(f"r{i}") for i in range(80)]), metadata(), trust="live"
        )
        page = self.store.association_records({}, size=50)
        self.assertEqual(len(page["rows"]), 50)
        self.assertTrue(page["has_more"])
        preview = self.store.preview_associations(
            {"action": "assign", "project_id": project, "filters": {"project_id": "unassigned"}}
        )
        self.assertEqual(preview["summary"]["selected_detail_count"], 80)
        self.apply(preview)
        self.assertEqual(self.query(project)["summary"]["record_count"], 80)
        self.assertEqual(self.store.association_status()["summary"]["unassigned_detail_count"], 0)

    def test_explicit_rejection_in_legacy_event_prevents_automatic_recovery(self) -> None:
        from aha import ledger

        self.project("历史项目", ["/old/repo"])
        self.store.sync_data(source_data(), metadata("/old/repo"), trust="live")
        self.lose_directory_as_legacy_refresh_did()
        version = self.store._db.execute(
            "SELECT id FROM session_metadata_versions "
            "WHERE json_extract(payload_json,'$.status')='matched'"
        ).fetchone()[0]
        with self.store._transaction():
            case = ledger.create_case(
                self.store._db,
                "directory",
                "合成已拒绝目录",
                {
                    "session_id": "s1",
                    "candidate_metadata_version_id": version,
                    "candidate_hash": "synthetic-rejected-candidate",
                },
                key="session:s1",
            )
            self.store._db.execute(
                "UPDATE reconciliation_cases SET state='resolved' WHERE id=?", (case,)
            )
            self.store._db.execute(
                "INSERT INTO reconciliation_events(case_id,choice,reason,created_at) "
                "VALUES(?,'current','已核实不采用这个候选',?)",
                (case, self.store._now()),
            )
        self.assertEqual(self.store.association_status()["summary"]["ambiguous_sessions"], 1)
        with self.assertRaises(AppError):
            self.store.preview_associations({"action": "recover"})

    def test_record_cursor_is_revision_bound_and_filter_bound(self) -> None:
        self.store.sync_data(
            source_data([detail(f"r{i}") for i in range(3)]), metadata(), trust="live"
        )
        cursor = self.store.association_records({}, size=1)["next_cursor"]
        self.assertIsNotNone(cursor)
        with self.assertRaises(AppError) as changed_filter:
            self.store.association_records({"reason": "missing"}, cursor=cursor, size=1)
        self.assertEqual(changed_filter.exception.code, "invalid_cursor")
        self.project("新项目")
        with self.assertRaises(AppError) as changed_revision:
            self.store.association_records({}, cursor=cursor, size=1)
        self.assertEqual(changed_revision.exception.code, "invalid_cursor")

    def test_malformed_cursor_structures_are_safe_client_errors(self) -> None:
        self.store.sync_data(source_data(), metadata(), trust="live")
        for value in ({}, {"x": 1}, [], [1, 2], None, "not-a-cursor"):
            with self.subTest(value=value), self.assertRaises(AppError) as failure:
                cursor = base64.urlsafe_b64encode(json.dumps(value).encode()).decode()
                self.store.association_records({}, cursor=cursor)
            self.assertEqual(failure.exception.code, "invalid_cursor")

    def test_non_assignment_cannot_enable_a_session_default(self) -> None:
        self.store.sync_data(source_data(), metadata(), trust="live")
        for action in ("recover", "reclassify"):
            with self.subTest(action=action), self.assertRaises(AppError) as failure:
                self.store.preview_associations({"action": action, "bind_sessions": True})
            self.assertEqual(failure.exception.code, "invalid_assignment")
        self.assertEqual(
            self.store._db.execute("SELECT COUNT(*) FROM session_project_bindings").fetchone()[0], 0
        )

    def test_truncated_metadata_cannot_clear_projects_in_a_full_reclassification(self) -> None:
        project = self.project("两个已归属会话", ["/work/a"])
        rows = [detail("first", session_id="s1"), detail("second", session_id="s2")]
        observed = {
            "sessions": {
                sid: {"cwd": "/work/a", "status": "matched", "parent_id": None}
                for sid in ("s1", "s2")
            }
        }
        self.store.sync_data(source_data(rows), observed, trust="live")
        before = self.query(project)
        with patch("aha.associations.MAX_METADATA", 1):
            with self.assertRaises(AppError) as failure:
                self.store.preview_associations(
                    {"action": "reclassify", "filters": {"project_id": "all"}}
                )
            self.assertEqual(failure.exception.code, "assignment_metadata_limit")
        after = self.query(project)
        self.assertEqual(after["summary"], before["summary"])
        self.assertEqual(after["classification_revision"], before["classification_revision"])
        self.assertEqual(after["summary"]["record_count"], 2)

    def test_alias_confirmation_transfers_the_unique_known_project_without_copying_override(
        self,
    ) -> None:
        project = self.project("唯一已知项目")
        original, candidate = detail("original"), detail("rebuilt")
        self.store.sync_data(source_data([original]), metadata(), trust="live")
        self.store.sync_data(source_data([candidate]), metadata(), trust="live")
        self.store.assign_keys([record_key(candidate)], project)
        identity = next(c for c in self.store.list_reconciliations() if c["type"] == "identity")
        self.store.resolve_reconciliation(identity["id"], "same", "已核实是同一消费且候选项目正确")
        self.assertEqual(self.query(project)["summary"]["record_count"], 1)
        self.assertEqual(self.query()["summary"]["record_count"], 1)
        link = self.store._db.execute(
            "SELECT project_id,basis,basis_json FROM record_project_links WHERE record_key=?",
            (record_key(original),),
        ).fetchone()
        self.assertEqual(link["project_id"], project)
        self.assertEqual(link["basis"], "identity_confirmation")
        self.assertEqual(json.loads(link["basis_json"])["case_id"], identity["id"])
        self.assertEqual(
            self.store._db.execute(
                "SELECT COUNT(*) FROM overrides WHERE record_key=?", (record_key(original),)
            ).fetchone()[0],
            0,
        )
        self.assertEqual(
            self.store._db.execute(
                "SELECT COUNT(*) FROM project_assignment_events WHERE basis='identity_confirmation'"
            ).fetchone()[0],
            1,
        )

    def test_alias_project_transfer_preserves_claim_package_and_financial_revision_review(
        self,
    ) -> None:
        project = self.project("唯一已知项目")
        original, candidate = detail("original"), detail("rebuilt", total_cost_usd="0.99")
        self.store.sync_data(source_data([original]), metadata(), trust="live")
        selected = self.store.analyze("2026-10-01", "2026-10-31")
        batch = self.store.create_batch(selected, claim(), "before-identity-project-transfer")
        package, _ = self.store.download(batch["id"], batch["version"])
        digest = hashlib.sha256(package.read_bytes()).hexdigest()
        self.store.sync_data(source_data([candidate]), metadata(), trust="live")
        self.store.assign_keys([record_key(candidate)], project)
        identity = next(c for c in self.store.list_reconciliations() if c["type"] == "identity")
        self.store.resolve_reconciliation(identity["id"], "same", "确认同消费与唯一已知项目")
        revision = next(c for c in self.store.list_reconciliations() if c["type"] == "revision")
        self.assertEqual(
            self.store._db.execute(
                "SELECT total_cost_usd FROM usage_records WHERE record_key=?",
                (record_key(original),),
            ).fetchone()[0],
            "0.1234567",
        )
        self.store.resolve_reconciliation(revision["id"], "current", "保留已确认原费用")
        self.assertEqual(self.query(project)["summary"]["record_count"], 1)
        self.assertEqual(
            self.store._db.execute(
                "SELECT COUNT(*) FROM usage_claims WHERE batch_id=?", (batch["id"],)
            ).fetchone()[0],
            1,
        )
        self.assertEqual(hashlib.sha256(package.read_bytes()).hexdigest(), digest)

    def test_whole_session_preview_expands_existing_members_preserves_exception_and_future_default(
        self,
    ) -> None:
        project, exception = self.project("整个会话"), self.project("逐条例外")
        rows = [detail(f"r{i}") for i in range(3)]
        self.store.sync_data(source_data(rows), metadata(), trust="live")
        self.store.assign_keys([record_key(rows[1])], exception)
        preview = self.store.preview_associations(
            {
                "action": "assign",
                "project_id": project,
                "keys": [record_key(rows[0])],
                "bind_sessions": True,
            }
        )
        self.assertEqual(preview["summary"]["selected_detail_count"], 3)
        self.assertEqual(preview["summary"]["manual_exceptions"], 1)
        self.apply(preview)
        self.assertEqual(self.query(project)["summary"]["record_count"], 2)
        self.assertEqual(self.query(exception)["summary"]["record_count"], 1)
        self.store.sync_data(source_data([*rows, detail("future")]), metadata(), trust="live")
        self.assertEqual(self.query(project)["summary"]["record_count"], 3)
        self.assertEqual(self.query(exception)["summary"]["record_count"], 1)

    def test_rule_edits_preserve_history_until_explicit_reclassification(self) -> None:
        parent = self.project("父项目", ["/work"])
        child = self.project("子项目", ["/work/a"])
        self.store.sync_data(source_data(), metadata(), trust="live")
        self.store.save_project(child, "子项目", "", ["/elsewhere"])
        self.assertEqual(self.query(child)["summary"]["record_count"], 1)
        preview = self.store.preview_associations(
            {"action": "reclassify", "filters": {"project_id": child}}
        )
        self.assertEqual(preview["projects"][0]["id"], parent)
        self.apply(preview)
        self.assertEqual(self.query(parent)["summary"]["record_count"], 1)

    def test_saving_a_new_rule_does_not_silently_assign_existing_unassigned_records(self) -> None:
        self.store.sync_data(source_data(), metadata(), trust="live")
        self.project("后来新建", ["/work/a"])
        self.store.sync_data(source_data([detail(), detail("new")]), metadata(), trust="live")
        first = self.store._db.execute(
            "SELECT project_id FROM usage_records WHERE record_key=?", (record_key(detail()),)
        ).fetchone()[0]
        self.assertEqual(first, "")
        status = self.store.association_status()
        self.assertEqual(status["summary"]["unassigned_detail_count"], 1)
        self.assertEqual(status["groups"][0]["reason"], "directory_unbound")
        self.assertEqual(status["summary"]["recoverable_sessions"], 0)

    def test_stale_previews_reject_all_changes_and_response_loss_replay_survives_restart(
        self,
    ) -> None:
        project = self.project("项目")
        self.store.sync_data(source_data(), metadata(), trust="live")
        stale = self.store.preview_associations({"action": "assign", "project_id": project})
        self.store.save_project(project, "更名项目", "", [])
        with self.assertRaises(AppError) as failure:
            self.apply(stale)
        self.assertEqual(failure.exception.code, "association_preview_expired")
        self.assertEqual(self.query(project)["summary"]["record_count"], 0)
        preview = self.store.preview_associations({"action": "assign", "project_id": project})
        result = self.apply(preview)
        self.store.close()
        self.store = Store(Path(self.temporary.name))
        self.assertEqual(self.apply(preview), result)

    def test_failure_mid_batch_rolls_back_relations_overrides_stats_and_events(self) -> None:
        project = self.project("项目")
        self.store.sync_data(source_data([detail("a"), detail("b")]), metadata(), trust="live")
        preview = self.store.preview_associations(
            {"action": "assign", "project_id": project, "bind_sessions": True}
        )
        before = self.store.association_status()
        from aha.project_links import link_record

        calls = 0

        def fail_second(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("synthetic interrupted batch")
            return link_record(*args, **kwargs)

        with patch("aha.project_links.link_record", side_effect=fail_second):
            with self.assertRaises(RuntimeError):
                self.apply(preview)
        self.assertEqual(self.store.association_status(), before)
        self.assertEqual(
            self.store._db.execute("SELECT COUNT(*) FROM session_project_bindings").fetchone()[0], 0
        )

    def test_rollups_remain_whole_and_project_totals_plus_unassigned_conserve_cost(self) -> None:
        project = self.project("项目")
        self.store.sync_data(source_data([detail()], [rollup()]), metadata(), trust="live")
        missing = self.store.association_records({"reason": "missing"})["rows"]
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0]["kind"], "rollup")
        self.assertEqual(missing[0]["record_count"], 7)
        preview = self.store.preview_associations(
            {
                "action": "assign",
                "project_id": project,
                "filters": {"start_date": "2026-10-24", "end_date": "2026-10-24"},
            }
        )
        self.assertEqual(preview["summary"]["selected_rollup_count"], 1)
        self.assertEqual(preview["summary"]["selected_record_count"], 7)
        self.apply(preview)
        status = self.store.association_status()
        self.assertEqual(status["projects"][0]["record_count"], 7)
        self.assertEqual(status["projects"][0]["total_cost_usd"], "1.00000001")
        self.assertEqual(status["summary"]["unassigned_cost_usd"], "0.1234567")
        self.assertEqual(self.query()["summary"]["total_cost_usd"], "1.12345671")


if __name__ == "__main__":
    unittest.main()
