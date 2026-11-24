"""A copied ledger retains facts, claims and directory evidence on a new device."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from native_usage_fixtures import CACHED, INPUT, MODEL, OUTPUT, SESSION, START, write_rollout
from test_storage_helpers import claim, detail, metadata, rollup, source_data

from aha import source_bindings
from aha.codex_sessions import CodexSource, probe_source
from aha.domain import AppError, content_hash
from aha.storage import Store


class DeviceContinuityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = Store(self.root / "ledger")
        self.source = self.root / "synthetic-codex"
        self.source.mkdir()
        self.enterContext(patch(
            "aha.source_bindings.installation_id", return_value="new-computer"
        ))

    def tearDown(self) -> None:
        self.store.close()
        self.temporary.cleanup()

    def query(self, project: str = "all") -> dict:
        return self.store.analyze("2026-10-01", "2026-10-31", project)

    def bind_source(self, root: Path | None = None) -> source_bindings.CodexBinding:
        previous = source_bindings.configured_codex_sources(self.store).get("windows")
        source = probe_source(CodexSource("windows", str(root or self.source)))
        source_bindings.bind_codex_source(
            self.store, source, previous.source_id if previous else None
        )
        return source_bindings.configured_codex_sources(self.store)["windows"]

    def sync_source(self) -> dict:
        binding = source_bindings.configured_codex_sources(self.store)["windows"]
        return self.store.sync_codex(binding.source, binding.source_id, since=binding.since)

    def old_source(self) -> source_bindings.CodexBinding:
        write_rollout(self.source, 1)
        with patch("aha.source_bindings.installation_id", return_value="old-computer"):
            binding = self.bind_source()
            self.sync_source()
        return binding

    def test_same_path_new_machine_requires_confirmation_without_quarantining_history(self) -> None:
        self.old_source()
        before = self.store.ledger_status()
        with self.store.read_connection() as connection:
            runs = connection.execute("SELECT COUNT(*) FROM sync_runs").fetchone()[0]
        self.assertEqual(source_bindings.configured_codex_sources(self.store), {})
        self.assertEqual(self.store.ledger_status(), before)
        self.assertEqual(self.query()["summary"]["record_count"], 1)
        self.assertEqual(self.store.list_reconciliations(), [])
        with self.store.read_connection() as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM sync_runs").fetchone()[0], runs
            )

    def test_explicit_new_device_keeps_global_keys_claims_and_original_package(self) -> None:
        old = self.old_source()
        with self.store.read_connection() as connection:
            first_key = connection.execute("SELECT record_key FROM usage_records").fetchone()[0]
        project = self.store.save_project(None, "原项目", "", [])['project']['id']
        self.store.assign_keys([first_key], project)
        saved = self.store.create_batch(self.query(), claim(), "old-device-claim")
        package, _ = self.store.download(saved["id"], 1)
        before_sha = hashlib.sha256(package.read_bytes()).hexdigest()
        write_rollout(self.source, 2, first_index=1)
        binding = self.bind_source()
        self.assertNotEqual(binding.source_id, old.source_id)
        result = self.sync_source()
        self.assertEqual((result["new_count"], result["unchanged_count"]), (1, 1))
        self.assertEqual(self.query()["summary"]["record_count"], 1)
        self.assertEqual(self.query(project)["summary"]["record_count"], 0)
        with self.store.read_connection() as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM usage_records").fetchone()[0], 2
            )
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM usage_claims").fetchone()[0], 1
            )
        same = self.sync_source()
        self.assertEqual((same["new_count"], same["revised_count"]), (0, 0))
        restored_package, _ = self.store.download(saved["id"], 1)
        self.assertEqual(hashlib.sha256(restored_package.read_bytes()).hexdigest(), before_sha)

    def test_empty_new_source_preserves_history_and_repeated_binding_is_idempotent(self) -> None:
        self.old_source()
        empty = self.root / "empty-codex"
        (empty / "sessions").mkdir(parents=True)
        binding = self.bind_source(empty)
        again = self.bind_source(empty)
        self.assertEqual(binding, again)
        for _ in range(2):
            self.assertEqual(self.sync_source()["new_count"], 0)
        self.assertEqual(self.query()["summary"]["record_count"], 1)
        self.assertEqual(self.store.list_reconciliations(), [])

    def test_legacy_path_profile_is_not_adopted_as_current_device_authority(self) -> None:
        unavailable = self.root / "retired-source.sqlite"
        legacy = content_hash(["sqlite", str(unavailable)])
        old_row = detail(
            session_id=SESSION, model=MODEL, pricing_model=MODEL, request_model=MODEL,
            input_tokens=INPUT, output_tokens=OUTPUT, cache_read_tokens=CACHED,
            cache_creation_tokens=0, created_at=int(START.timestamp()),
        )
        old = source_data([old_row])
        old["source"] = {"kind": "sqlite", "name": unavailable.name, "location": str(unavailable)}
        self.store.sync_data(old, source_id=legacy, trust="live")
        self.assertEqual(source_bindings.configured_codex_sources(self.store), {})
        self.assertEqual(source_bindings.history_default_since(self.store), "2026-10-26")
        write_rollout(self.source, 1)
        new = self.bind_source()
        self.assertNotEqual(new.source_id, legacy)
        for _ in range(2):
            self.assertEqual(self.sync_source()["revised_count"], 0)
        case = self.store.list_reconciliations()[0]
        self.assertEqual(case["type"], "identity")
        self.store.resolve_reconciliation(case["id"], "same", "已核对同笔历史，保留原值")
        self.assertEqual(self.query()["summary"]["total_cost_usd"], "0.1234567")
        self.sync_source()
        self.assertEqual(self.query()["summary"]["total_cost_usd"], "0.1234567")
        self.assertEqual(self.store.list_reconciliations(), [])
        self.assertFalse(unavailable.exists())

    def test_restore_marker_requires_rebinding_even_on_same_machine(self) -> None:
        write_rollout(self.source, 1)
        first = self.bind_source()
        self.sync_source()
        marker = self.store.data_dir / "restore-info.json"
        marker.write_text(json.dumps({"format_version": 1, "restore_id": str(uuid4())}))
        self.assertEqual(source_bindings.configured_codex_sources(self.store), {})
        rebound = self.bind_source()
        self.assertNotEqual(rebound.source_id, first.source_id)
        self.assertEqual(self.sync_source()["unchanged_count"], 1)

    def test_bad_restore_or_binding_metadata_fails_without_changing_history(self) -> None:
        write_rollout(self.source, 1)
        self.bind_source()
        self.sync_source()
        before = self.store.revisions()
        marker = self.store.data_dir / "restore-info.json"
        for invalid in ('{"format_version":1}', "[" * 1200 + "0" + "]" * 1200):
            marker.write_text(invalid)
            with self.assertRaises(AppError) as error:
                source_bindings.configured_codex_sources(self.store)
            self.assertEqual(error.exception.code, "source_binding_damaged")
        marker.unlink()
        with self.store._transaction():
            self.store._db.execute("UPDATE settings SET value='[]' WHERE key=?",
                                   (source_bindings.CODEX_BINDINGS_KEY + "windows",))
        with self.assertRaises(AppError) as error:
            source_bindings.configured_codex_sources(self.store)
        self.assertEqual(error.exception.code, "source_binding_damaged")
        self.assertEqual(self.store.revisions(), before)
        self.assertEqual(self.query()["summary"]["record_count"], 1)

    def test_equal_historical_rollups_need_origin_review(self) -> None:
        history = source_data([], [rollup()])
        self.store.sync_data(history, source_id="old-rollup", trust="live")
        result = self.store.sync_data(history, source_id="copied-rollup", trust="live")
        self.assertEqual(result["new_count"], 0)
        case = self.store.list_reconciliations()[0]
        self.assertEqual(case["type"], "rollup_origin")
        self.assertEqual(case["choices"], ["current"])
        self.store.resolve_reconciliation(case["id"], "current", "确认是复制的同份历史汇总")
        self.assertEqual(self.query()["summary"]["record_count"], 7)
        self.store.sync_data(history, source_id="copied-rollup", trust="live")
        self.assertEqual(self.store.list_reconciliations(), [])
        self.assertEqual(self.query()["summary"]["record_count"], 7)

    def test_smaller_historical_rollup_does_not_replace_old_day_on_repeat(self) -> None:
        self.store.sync_data(
            source_data([], [rollup(request_count=100)]), source_id="full-history", trust="live"
        )
        partial = source_data([], [rollup(request_count=10)])
        for _ in range(2):
            result = self.store.sync_data(partial, source_id="partial-history", trust="live")
            self.assertEqual(result["revised_count"], 0)
            with self.store.read_connection() as connection:
                self.assertEqual(connection.execute(
                    "SELECT request_count FROM usage_records WHERE kind='rollup'"
                ).fetchone()[0], "100")
        case = self.store.list_reconciliations()[0]
        self.assertEqual(case["type"], "revision")
        self.store.resolve_reconciliation(case["id"], "current", "保留旧设备已保存的完整日")
        self.store.sync_data(partial, source_id="partial-history", trust="live")
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
