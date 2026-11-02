"""Exercise release provenance, notes, manual gates and interrupted draft uploads."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "release.py"
SPEC = importlib.util.spec_from_file_location("aha_release", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


class FakeGitHub:
    repo = "example/aha"

    def __init__(self, main: str, prs: list[dict] | None = None) -> None:
        self.main = main
        self.releases: list[dict] = []
        self.prs = prs or []
        self.payloads: dict[int, bytes] = {}
        self.calls: list[tuple[str, str, object]] = []
        self.fail_upload: str | None = None
        self.fail_label_once = False
        self.next_asset = 10

    def pages(self, path: str) -> list[dict]:
        return copy.deepcopy(self.releases if path == "/releases" else self.prs)

    def request(self, method: str, path: str, data: object = None, **kwargs: object) -> object:
        self.calls.append((method, path, data))
        if path == "/git/ref/heads/main":
            return {"object": {"sha": self.main}}
        if path.startswith("/git/ref/tags/"):
            public = [item for item in self.releases if not item["draft"]]
            return (
                {"object": {"type": "commit", "sha": public[0]["target_commitish"]}}
                if public
                else None
            )
        if path == "/releases" and method == "POST":
            item = {**data, "id": 1, "assets": [], "html_url": "https://example.invalid/draft"}
            self.releases.append(item)
            return copy.deepcopy(item)
        if path.startswith("/releases/assets/"):
            return self.payloads[int(path.rsplit("/", 1)[1])]
        if path.startswith("/releases/1/assets?"):
            name = urllib.parse.parse_qs(urllib.parse.urlsplit(path).query)["name"][0]
            if name == self.fail_upload:
                raise release.ReleaseError("synthetic interrupted upload")
            self.next_asset += 1
            self.payloads[self.next_asset] = data
            self.releases[0]["assets"].append({"id": self.next_asset, "name": name})
            return {"id": self.next_asset, "name": name}
        if path == "/releases/1":
            if method == "PATCH":
                self.releases[0].update(data)
            return copy.deepcopy(self.releases[0])
        if path.startswith("/labels/"):
            return {"name": "autorelease: tagged"}
        if path.startswith("/issues/"):
            if method == "POST" and self.fail_label_once:
                self.fail_label_once = False
                raise release.ReleaseError("synthetic label update interrupted after publication")
            for pr in self.prs:
                if method == "POST":
                    labels = {item["name"] for item in pr["labels"]} | set(data["labels"])
                    pr["labels"] = [{"name": name} for name in labels]
                elif method == "DELETE":
                    label = urllib.parse.unquote(path.rsplit("/", 1)[1])
                    pr["labels"] = [item for item in pr["labels"] if item["name"] != label]
            return []
        if path.startswith("/pulls/"):
            if method == "GET":
                return copy.deepcopy(self.prs[0])
            return data
        if path.startswith("/git/commits/"):
            return {"tree": {"sha": "a" * 40}}
        if path == "/git/trees":
            return {"sha": "b" * 40}
        if path == "/git/commits":
            return {"sha": "c" * 40}
        if path.startswith("/git/refs/") or path.endswith("/dispatches"):
            return None
        raise AssertionError((method, path, data, kwargs))


class ReleaseTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="aha-release-test-")
        self.root = Path(self.temp.name)
        self.git("init", "-b", "main")
        self.git("config", "user.email", "release-test@example.invalid")
        self.git("config", "user.name", "Release Test")
        self.put("src/aha/__init__.py", '__version__ = "0.3.1"\n')
        self.put("src/aha/evidence.py", "# synthetic material producer\n")
        self.put("src/aha/tray_windows.py", "# synthetic tray\n")
        self.put("pyproject.toml", '[project]\nname="test"\ndynamic=["version"]\n')
        self.put("scripts/requirements-build.txt", "pyinstaller==6.22.3\nzstandard==0.25.0\n")
        self.put(".release-please-manifest.json", json.dumps({".": "0.3.1"}))
        self.base = self.commit("baseline")
        self.put("src/aha/__init__.py", '__version__ = "0.4.0"\n')
        self.put(".release-please-manifest.json", json.dumps({".": "0.4.0"}))
        self.fragment("new-feature", highlight=True)
        self.put(".release/overview.md", "既有能力概览。\n")
        self.commit("feat: synthetic feature")
        body, meta = release.candidate_notes(self.root, "HEAD", None, FakeGitHub.repo, None)
        self.put("docs/releases/v0.4.0.md", body)
        self.put(".release/candidates/v0.4.0.json", json.dumps(meta))
        self.source = self.commit("chore(release): synthetic candidate")
        self.candidate = {
            "schema_version": 1,
            "version": "0.4.0",
            "tag": "v0.4.0",
            "source_sha": self.source,
            "pr_number": 3,
            "previous_sha": None,
            "previous_tag": None,
        }
        self.api = FakeGitHub(self.source)
        self.asset_root = self.root / "assets"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def git(self, *args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(self.root), *args], check=True, capture_output=True, text=True
        )
        return result.stdout.strip()

    def put(self, path: str, value: str) -> None:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(value.encode())

    def commit(self, title: str) -> str:
        self.git("add", ".")
        self.git("commit", "-m", title)
        return self.git("rev-parse", "HEAD")

    def fragment(self, identifier: str, **extra: object) -> None:
        value = {
            "id": identifier,
            "kind": "feature",
            "title": "功能标题",
            "description": "用户能够完成一项有据可查的操作。",
            "upgrade_notes": [],
            **extra,
        }
        self.put(f".release/changes/{identifier}.json", json.dumps(value, ensure_ascii=False))

    def assets(self) -> Path:
        exe = self.root / "synthetic.exe"
        exe.write_bytes(b"MZ synthetic unit-test artifact; this is not native acceptance")
        report = {
            "verified": True,
            "version": "0.4.0",
            "executable_sha256": release.digest(exe.read_bytes()),
            "pe_version": "0.4.0",
            "scopes": ["synthetic-automatic-report"],
        }
        for name in ("directory.json", "onefile.json"):
            self.put(name, json.dumps(report))
        self.put("runtime.json", json.dumps({"python": [3, 15], "sqlite_version": "3.53.4"}))
        with patch.object(release, "bundle_runtime", return_value=self.synthetic_runtime()):
            release.bundle(
                self.root,
                self.candidate,
                exe,
                self.root / "directory.json",
                self.root / "onefile.json",
                self.root / "runtime.json",
                self.asset_root,
                self.api.repo,
            )
        return self.asset_root

    def synthetic_runtime(self) -> dict:
        return {
            "windows": True,
            "isolated": True,
            "bits": 64,
            "python": [3, 15, 2],
            "machine": "AMD64",
            "sqlite": [3, 53, 4],
            "sqlite_version": "3.53.4",
            "packages": {"pyinstaller": "6.22.3", "zstandard": "0.25.0", "aha-usage": "0.4.0"},
        }

    def receipt(self, *, checks: set[str] | None = None, artifact: str | None = None) -> None:
        checks = checks if checks is not None else set(release.CHECKS)
        value = {
            "schema_version": 1,
            "source_sha": self.source,
            "candidate_source_sha": self.source,
            "completed_at": "2026-11-02T12:00:00+08:00",
            "fingerprints": release.fingerprints(self.root, self.source),
            "runtime_sha256": release.runtime_digest(
                self.root, self.source, self.synthetic_runtime()
            ),
            "checks": sorted(checks),
            "artifact_sha256": artifact,
            "evidence": [
                {"scope": scope, "sha256": "a" * 64, "description": "synthetic unit-test receipt"}
                for scope in checks
            ],
        }
        self.put(".release/acceptance/synthetic.json", json.dumps(value))
        self.api.main = self.commit("chore: synthetic receipt only")

    def test_notes_are_stable_chinese_and_omit_empty_sections(self) -> None:
        body, ids = release.render_notes(self.root, self.source, None, "0.4.0", self.api.repo)
        again, _ = release.render_notes(self.root, self.source, None, "0.4.0", self.api.repo)
        self.assertEqual(body, again)
        self.assertEqual(ids, ["new-feature"])
        self.assertIn("本次亮点", body)
        self.assertIn("首次公开发布", body)
        self.assertNotIn("问题修复", body)
        self.assertNotIn("## 升级说明", body)
        self.assertNotIn("/compare/", body)
        self.assertEqual(body.count("用户能够完成一项有据可查的操作。"), 1)

    def test_manual_main_validation_uses_public_source_or_bootstrap_not_HEAD(self) -> None:
        self.put("release-please-config.json", json.dumps({"bootstrap-sha": self.base}))
        head = self.commit("synthetic config")
        self.assertEqual(release.validation_base(self.root, head, self.api), self.base)
        self.put("release-please-config.json", json.dumps({"bootstrap-sha": "HEAD"}))
        invalid = self.commit("synthetic invalid bootstrap")
        with self.assertRaisesRegex(release.ReleaseError, "Bootstrap equals"):
            release.validation_base(self.root, invalid, self.api)

    def test_duplicate_id_and_breaking_without_upgrade_are_rejected(self) -> None:
        self.fragment("other-file", id="new-feature")
        with self.assertRaisesRegex(release.ReleaseError, "duplicate"):
            release.fragments(self.root, "WORKTREE", None)
        (self.root / ".release/changes/other-file.json").unlink()
        self.fragment("breaking-change", kind="breaking")
        with self.assertRaisesRegex(release.ReleaseError, "upgrade"):
            release.fragments(self.root, "WORKTREE", None)

    def test_published_fragments_immutable_but_unpublished_edits_can_be_validated(self) -> None:
        self.fragment("new-feature", description="已修改且尚未发布的真实说明。")
        with self.assertRaisesRegex(release.ReleaseError, "immutable"):
            release.fragments(self.root, "WORKTREE", self.source)
        release.validate_changes(self.root, "WORKTREE", self.source)

    def test_internal_only_changes_do_not_generate_empty_release(self) -> None:
        self.fragment("new-feature", kind="internal", reason="仅测试夹具，没有用户变化。")
        with self.assertRaisesRegex(release.ReleaseError, "empty"):
            release.render_notes(self.root, "WORKTREE", None, "0.4.0", self.api.repo)

    def test_reverting_unpublished_feature_removes_its_notes_without_empty_release(self) -> None:
        original = (self.root / "src/aha/evidence.py").read_text(encoding="utf-8")
        self.put("src/aha/evidence.py", "# feature awaiting its first public release\n")
        self.fragment("unpublished-feature")
        unmerged = self.commit("feat: synthetic unpublished feature")
        self.put("src/aha/evidence.py", original)
        (self.root / ".release/changes/unpublished-feature.json").unlink()
        self.fragment(
            "restore-unreleased",
            kind="internal",
            reason="撤销尚未公开的功能，使用者没有获得该功能。",
        )
        release.validate_changes(self.root, "WORKTREE", unmerged)
        changes = release.fragments(self.root, "WORKTREE", self.source)
        self.assertEqual([item["id"] for item in changes], ["restore-unreleased"])
        with self.assertRaisesRegex(release.ReleaseError, "empty"):
            release.render_notes(
                self.root, "WORKTREE", self.source, "0.4.1", self.api.repo, "v0.4.0"
            )

    def test_version_only_does_not_invalidate_manual_fingerprints(self) -> None:
        before = release.fingerprints(self.root, self.source)
        self.put("src/aha/__init__.py", '__version__ = "0.4.1"\n')
        self.assertEqual(before, release.fingerprints(self.root, "WORKTREE"))
        self.assertEqual(release.required_checks(self.root, "WORKTREE", self.source), set())

    def test_checkout_line_endings_do_not_invalidate_source_but_binary_bytes_do(self) -> None:
        body = b'__version__ = "0.4.0"\n'
        self.assertEqual(
            release.normalized("src/aha/__init__.py", body),
            release.normalized("src/aha/__init__.py", body.replace(b"\n", b"\r\n")),
        )
        self.assertNotEqual(
            release.normalized("src/aha/web/mark.ico", b"binary\r\n"),
            release.normalized("src/aha/web/mark.ico", b"binary\n"),
        )

    def test_receipt_fingerprints_must_belong_to_its_real_tested_source(self) -> None:
        self.receipt(artifact="b" * 64)
        path = self.root / ".release/acceptance/synthetic.json"
        value = json.loads(path.read_text())
        self.put("src/aha/evidence.py", "# product change after the tested source\n")
        changed = self.commit("fix: synthetic later change")
        value["source_sha"] = changed
        self.put(".release/acceptance/synthetic.json", json.dumps(value))
        with self.assertRaisesRegex(release.ReleaseError, "tested source"):
            release.acceptance_missing(
                self.root,
                self.source,
                "WORKTREE",
                None,
                "b" * 64,
                release.runtime_digest(self.root, self.source, self.synthetic_runtime()),
            )

    def test_runtime_digest_ignores_QA_tools_but_invalidates_actual_SQLite_drift(self) -> None:
        runtime = self.synthetic_runtime()
        current = release.runtime_digest(self.root, self.source, runtime)
        qa = {**runtime, "packages": {**runtime["packages"], "pymupdf": "synthetic-QA-tool"}}
        self.assertEqual(current, release.runtime_digest(self.root, self.source, qa))
        changed = {**runtime, "sqlite": [3, 53, 5], "sqlite_version": "3.53.5"}
        changed_digest = release.runtime_digest(self.root, self.source, changed)
        self.assertNotEqual(current, changed_digest)
        self.receipt(artifact="b" * 64)
        missing = release.acceptance_missing(
            self.root, self.source, "WORKTREE", self.source, "b" * 64, changed_digest, current
        )
        self.assertEqual(set(missing), set(release.CHECKS))

    def test_tested_feature_commit_can_be_fetched_after_squash_merge(self) -> None:
        calls: list[tuple[str, ...]] = []
        known = False

        def git(root: Path, *args: str, **kwargs: object) -> bytes:
            nonlocal known
            calls.append(args)
            if args[0] == "cat-file":
                return b"commit" if known else b""
            if args == ("fetch", "origin", self.source):
                known = True
            if args[0] == "rev-parse":
                return self.source.encode()
            return b""

        with patch.object(release, "git", side_effect=git):
            release.ensure_commit(self.root, self.source)
        self.assertIn(("fetch", "origin", "main"), calls)
        self.assertIn(("fetch", "origin", self.source), calls)

    def test_runtime_inventory_uses_active_provider_when_source_metadata_is_stale(self) -> None:
        self.put(
            "active/aha_usage-0.4.0.dist-info/METADATA",
            "Metadata-Version: 2.1\nName: aha-usage\nVersion: 0.4.0\n",
        )
        self.put(
            "stale/aha_usage.egg-info/PKG-INFO",
            "Metadata-Version: 2.1\nName: aha-usage\nVersion: 0.3.0\n",
        )
        search_path = [str(self.root / "active"), str(self.root / "stale"), *release.sys.path]
        with patch.object(release.sys, "path", search_path):
            versions = {
                item.version
                for item in release.importlib.metadata.distributions(name="aha-usage")
            }
            self.assertTrue({"0.4.0", "0.3.0"}.issubset(versions))
            active = release.importlib.metadata.version("aha-usage")
            self.assertEqual(active, "0.4.0")
            self.assertEqual(release.installed_runtime()["packages"]["aha-usage"], active)

    def test_native_bundle_runtime_records_and_checks_patch_and_actual_dependencies(self) -> None:
        self.put(".release/runtime.json", json.dumps({"python": "3.15.2"}))
        self.put("scripts/requirements-build.txt", "pyinstaller==6.22.3\nzstandard==0.25.0\n")
        self.commit("synthetic native recipe")
        facts = {
            "windows": True,
            "isolated": True,
            "bits": 64,
            "python": [3, 15, 2],
            "machine": "AMD64",
            "sqlite": [3, 53, 4],
            "sqlite_version": "3.53.4",
            "packages": {
                "pyinstaller": "6.22.3",
                "zstandard": "0.25.0",
                "aha-usage": "0.4.0",
                "pyinstaller-hooks-contrib": "synthetic",
            },
        }
        probe = {**facts, "python": [3, 15]}
        with patch.object(release, "installed_runtime", return_value=facts):
            result = release.bundle_runtime(self.root, probe)
            self.assertEqual(result["python"], [3, 15, 2])
            self.assertIn("pyinstaller-hooks-contrib", result["packages"])
            with self.assertRaisesRegex(release.ReleaseError, "build probe"):
                release.bundle_runtime(self.root, {**probe, "sqlite_version": "3.51.3"})
        with patch.object(
            release, "installed_runtime", return_value={**facts, "python": [3, 15, 3]}
        ):
            with self.assertRaisesRegex(release.ReleaseError, "patch"):
                release.bundle_runtime(self.root, probe)
        with patch.object(release, "installed_runtime", return_value={**facts, "isolated": False}):
            with self.assertRaisesRegex(release.ReleaseError, "venv"):
                release.bundle_runtime(self.root, probe)

    def test_material_recipe_and_unknown_source_invalidate_correct_scopes(self) -> None:
        self.put("src/aha/evidence.py", "# changed material producer\n")
        self.assertEqual(
            release.required_checks(self.root, "WORKTREE", self.source), {"excel", "print"}
        )
        self.put("scripts/build_windows.py", "# new build recipe\n")
        self.assertEqual(
            release.required_checks(self.root, "WORKTREE", self.source), set(release.CHECKS)
        )
        (self.root / "scripts/build_windows.py").unlink()
        self.put("src/aha/unknown.py", "# new module cannot bypass manual checks\n")
        self.assertEqual(
            release.required_checks(self.root, "WORKTREE", self.source), set(release.CHECKS)
        )

    def test_product_changes_need_notes_and_unreviewed_candidate_prose_is_rejected(self) -> None:
        self.put("src/aha/tray_windows.py", "# changed tray\n")
        with self.assertRaisesRegex(release.ReleaseError, "require"):
            release.validate_changes(self.root, "WORKTREE", self.source)
        self.put("docs/releases/v0.4.0.md", "unreviewed mutation\n")
        changed = self.commit("unreviewed mutation")
        candidate = {**self.candidate, "source_sha": changed}
        with self.assertRaisesRegex(release.ReleaseError, "What's New"):
            release.validate_candidate(self.root, changed, candidate, self.api.repo)

    def test_first_release_stays_draft_without_real_receipts(self) -> None:
        state = release.stage(self.root, self.api, self.candidate, self.assets())
        self.assertEqual(state["state"], "awaiting_acceptance")
        self.assertEqual(set(state["missing"]), set(release.CHECKS))
        self.assertTrue(self.api.releases[0]["draft"])
        self.assertFalse(
            any(method == "PATCH" and path == "/releases/1" for method, path, _ in self.api.calls)
        )
        sums = (self.asset_root / "SHA256SUMS.txt").read_bytes()
        self.assertNotIn(b"\r", sums)

    def test_first_receipt_must_include_physical_tray_and_exact_asset(self) -> None:
        assets = self.assets()
        sha = json.loads((assets / "build-info.json").read_text())["executable"]["sha256"]
        self.receipt(checks=set(release.CHECKS) - {"tray"}, artifact=sha)
        state = release.stage(self.root, self.api, self.candidate, assets)
        self.assertEqual(state["missing"], ["tray"])
        self.receipt(artifact="b" * 64)
        state = release.stage(self.root, self.api, self.candidate, None)
        self.assertEqual(set(state["missing"]), set(release.CHECKS))

    def test_receipt_after_M_can_publish_same_verified_asset_and_rerun_is_idempotent(self) -> None:
        assets = self.assets()
        first = release.stage(self.root, self.api, self.candidate, assets)
        self.receipt(artifact=first["artifact_sha256"])
        result = release.stage(self.root, self.api, self.candidate, None)
        self.assertEqual(result["state"], "published")
        self.assertNotEqual(self.api.main, self.source)
        self.assertEqual(self.api.releases[0]["target_commitish"], self.source)
        count = len(self.api.payloads)
        again = release.stage(self.root, self.api, self.candidate, None)
        self.assertEqual(again["state"], "already_published")
        self.assertEqual(len(self.api.payloads), count)

    def test_tampered_asset_and_conflicting_release_are_never_overwritten(self) -> None:
        assets = self.assets()
        release.stage(self.root, self.api, self.candidate, assets)
        exe = next(item for item in self.api.releases[0]["assets"] if item["name"].endswith(".exe"))
        self.api.payloads[exe["id"]] = b"changed bytes"
        with self.assertRaisesRegex(release.ReleaseError, "EXE"):
            release.stage(self.root, self.api, self.candidate, None)
        self.api.releases[0]["body"] = "unowned release"
        with self.assertRaisesRegex(release.ReleaseError, "owned"):
            release.stage(self.root, self.api, self.candidate, assets)

    def test_published_asset_identity_does_not_allow_moved_tag(self) -> None:
        assets = self.assets()
        waiting = release.stage(self.root, self.api, self.candidate, assets)
        self.receipt(artifact=waiting["artifact_sha256"])
        release.stage(self.root, self.api, self.candidate, None)
        original = self.api.request

        def request(method: str, path: str, *args: object, **kwargs: object) -> object:
            if path.startswith("/git/ref/tags/"):
                return {"object": {"type": "commit", "sha": "f" * 40}}
            return original(method, path, *args, **kwargs)

        with patch.object(self.api, "request", side_effect=request):
            with self.assertRaisesRegex(release.ReleaseError, "Published tag"):
                release.stage(self.root, self.api, self.candidate, None)

    def test_published_label_failure_recovers_before_next_release_PR_preparation(self) -> None:
        assets = self.assets()
        self.api.prs = [self.trusted_pr()]
        waiting = release.stage(self.root, self.api, self.candidate, assets)
        self.receipt(artifact=waiting["artifact_sha256"])
        self.api.fail_label_once = True
        with self.assertRaisesRegex(release.ReleaseError, "label update"):
            release.stage(self.root, self.api, self.candidate, None)
        self.assertFalse(self.api.releases[0]["draft"])
        self.assertIsNone(release.discover(self.root, self.api))
        release.reconcile_published(self.root, self.api)
        labels = {item["name"] for item in self.api.prs[0]["labels"]}
        self.assertIn("autorelease: tagged", labels)
        self.assertNotIn("autorelease: pending", labels)
        self.assertEqual(
            sum(method == "PATCH" and path == "/releases/1" for method, path, _ in self.api.calls),
            1,
        )

    def test_interrupted_upload_retains_original_recovery_run_and_can_resume(self) -> None:
        with patch.dict(os.environ, {"GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "2"}):
            assets = self.assets()
        self.api.fail_upload = "aha-0.4.0-windows-x64.exe"
        with self.assertRaisesRegex(release.ReleaseError, "interrupted"):
            release.stage(self.root, self.api, self.candidate, assets)
        self.assertEqual(
            {item["name"] for item in self.api.releases[0]["assets"]},
            {"build-info.json", "SHA256SUMS.txt"},
        )
        self.api.prs = [self.trusted_pr()]
        pending = release.discover(self.root, self.api)
        self.assertFalse(pending["needs_build"])
        self.assertEqual(pending["recovery_run_id"], "123")
        self.assertEqual(pending["recovery_artifact"], f"aha-assets-{self.source}-2")
        self.api.fail_upload = None
        state = release.stage(self.root, self.api, pending, assets)
        self.assertEqual(state["state"], "awaiting_acceptance")
        self.assertEqual(len(self.api.payloads), 3)

    def trusted_pr(self) -> dict:
        return {
            "number": 3,
            "state": "closed",
            "merged_at": "2026-11-02T02:00:00Z",
            "merge_commit_sha": self.source,
            "base": {"ref": "main"},
            "head": {
                "sha": self.source,
                "ref": "release-please--branches--main--components--aha-usage",
                "repo": {"full_name": self.api.repo},
            },
            "user": {"login": "github-actions[bot]"},
            "labels": [{"name": "autorelease: pending"}],
        }

    def test_discover_ignores_spoofed_pr_and_rejects_wrong_existing_source(self) -> None:
        fake = self.trusted_pr()
        fake["user"]["login"] = "untrusted-user"
        self.api.prs = [fake]
        self.assertIsNone(release.discover(self.root, self.api))
        self.api.prs = [self.trusted_pr()]
        release.stage(self.root, self.api, self.candidate, self.assets())
        self.api.releases[0]["body"] = (
            release.RELEASE_MARKER
            + json.dumps({"schema_version": 1, "source_sha": "f" * 40})
            + " -->"
        )
        with self.assertRaisesRegex(release.ReleaseError, "different"):
            release.discover(self.root, self.api)

    def test_discover_accepts_configured_component_branch(self) -> None:
        self.api.prs = [self.trusted_pr()]
        candidate = release.discover(self.root, self.api)
        self.assertEqual(candidate["source_sha"], self.source)
        self.assertEqual(candidate["pr_number"], 3)
        self.assertTrue(candidate["needs_build"])

    def test_release_identity_rejects_lookalikes_before_preparation_writes(self) -> None:
        cases = (
            (("head", "ref"), "release-please--branches--main"),
            (("head", "ref"), "release-please--branches--main--components--other"),
            (("head", "ref"), "release-please--branches--main--components--aha-usage-copy"),
            (("head", "ref"), "release-please--branches--other--components--aha-usage"),
            (("head", "repo", "full_name"), "untrusted/aha"),
            (("head", "repo"), None),
            (("base", "ref"), "other"),
            (("user", "login"), "untrusted-user"),
        )
        for path, value in cases:
            with self.subTest(path=path, value=value):
                pr = self.trusted_pr()
                target = pr
                for field in path[:-1]:
                    target = target[field]
                target[path[-1]] = value
                self.assertFalse(release.trusted_pr(pr, self.api.repo))
                self.api = FakeGitHub(self.source, [pr])
                self.assertIsNone(release.discover(self.root, self.api))
                pr.update(state="open", merged_at=None)
                self.api.prs = [pr]
                with self.assertRaisesRegex(release.ReleaseError, "untrusted release PR"):
                    release.prepare_pr(self.root, self.api, [{"number": 3}])
                self.assertFalse(any(method != "GET" for method, _, _ in self.api.calls))

    def test_merged_candidate_still_requires_merge_and_release_labels(self) -> None:
        for changes in ({"merged_at": None}, {"labels": []}):
            with self.subTest(changes=changes):
                pr = {**self.trusted_pr(), **changes}
                self.assertTrue(release.release_pr_identity(pr, self.api.repo))
                self.assertFalse(release.trusted_pr(pr, self.api.repo))
                self.api.prs = [pr]
                self.assertIsNone(release.discover(self.root, self.api))

    def test_prepare_dispatches_final_generated_head_and_preserves_tool_body(self) -> None:
        pr = self.trusted_pr()
        pr.update(state="open", merged_at=None, body="release-please identifying body")
        self.api.prs = [pr]
        original = release.git

        def local_git(root: Path, *args: str, **kwargs: object) -> bytes:
            return b"" if args[0] == "fetch" else original(root, *args, **kwargs)

        output = {
            "headBranchName": "release-please--branches--main--components--aha-usage",
            "baseBranchName": "main",
            "number": 3,
            "title": "chore(main): release 0.4.0",
            "body": pr["body"],
            "files": [],
            "labels": ["autorelease: pending"],
        }
        with patch.object(release, "git", side_effect=local_git):
            release.prepare_pr(self.root, self.api, [output])
        update = next(
            data
            for method, path, data in self.api.calls
            if method == "PATCH" and path == "/pulls/3"
        )
        self.assertIn("release-please identifying body", update["body"])
        self.assertIn("What’s New", update["body"])
        self.assertEqual(update["body"].count(release.NOTE_START), 1)
        branch = "release-please--branches--main--components--aha-usage"
        self.assertIn(
            ("PATCH", f"/git/refs/heads/{branch}", {"sha": "c" * 40, "force": False}),
            self.api.calls,
        )
        dispatch = next(
            data for method, path, data in self.api.calls if path.endswith("/dispatches")
        )
        self.assertEqual(dispatch["ref"], branch)
        self.assertEqual(dispatch["inputs"]["expected_sha"], "c" * 40)

    def test_failed_native_verifier_prevents_bundling(self) -> None:
        self.assets()
        info = json.loads((self.root / "onefile.json").read_text())
        info["verified"] = False
        self.put("onefile.json", json.dumps(info))
        with self.assertRaisesRegex(release.ReleaseError, "reports must pass"):
            release.bundle(
                self.root,
                self.candidate,
                self.root / "synthetic.exe",
                self.root / "directory.json",
                self.root / "onefile.json",
                self.root / "runtime.json",
                self.root / "other-assets",
                self.api.repo,
            )


if __name__ == "__main__":
    unittest.main()
