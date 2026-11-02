"""Versioned release notes, verified candidates and fail-closed GitHub publication."""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import shutil
import sqlite3
import struct
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

BOOTSTRAP = "f98df67df38a534fb240d20a79dda843297f4437"
# Release Please's configured package-name adds a component to its PR branch.
RELEASE_BRANCH = "release-please--branches--main--components--aha-usage"
VERSION_RE = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\Z")
SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")
CHECKS = frozenset({"directory", "onefile", "browser", "tray", "excel", "print"})
NOTE_START = "<!-- aha-whats-new:start -->"
NOTE_END = "<!-- aha-whats-new:end -->"
RELEASE_MARKER = "<!-- aha-release: "
KINDS = {
    "breaking": "兼容性与升级提醒",
    "feature": "新增功能",
    "improvement": "体验改进",
    "fix": "问题修复",
    "internal": "内部维护",
}
TRAY_FILES = {"__main__.py", "instance.py", "runtime.py", "tray_windows.py", "server.py"}
MATERIAL_FILES = {
    "analysis.py",
    "batches.py",
    "claims.py",
    "decimal_sql.py",
    "domain.py",
    "evidence.py",
    "ledger.py",
    "migrations.py",
    "projects.py",
    "queries.py",
    "session_meta.py",
    "sources.py",
    "sql_dump.py",
    "storage.py",
    "sync.py",
    "time_ranges.py",
}
RECIPE_FILES = {
    "pyproject.toml",
    "scripts/build_windows.py",
    "scripts/build_windows.ps1",
    "scripts/launch.py",
    "scripts/collect_licenses.py",
    "scripts/requirements-build.txt",
    ".github/workflows/windows-build.yml",
    ".release/runtime.json",
}


class ReleaseError(ValueError):
    """A safe, actionable release failure; never print a token-bearing request."""


def canonical(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode())


def git(root: Path, *args: str, optional: bool = False) -> bytes:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=False)
    if result.returncode and not optional:
        raise ReleaseError(f"Git operation failed: {args[0]}")
    return result.stdout if not result.returncode else b""


def resolve(root: Path, ref: str) -> str:
    if ref == "WORKTREE":
        return ref
    value = git(root, "rev-parse", "--verify", f"{ref}^{{commit}}").decode().strip()
    if not SHA_RE.fullmatch(value):
        raise ReleaseError("A complete commit SHA is required.")
    return value


def files_at(root: Path, ref: str) -> list[str]:
    if ref == "WORKTREE":
        raw = git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    else:
        raw = git(root, "ls-tree", "-r", "--name-only", "-z", resolve(root, ref))
    return sorted(
        {
            name
            for name in raw.decode().split("\0")
            if name and (ref != "WORKTREE" or (root / name).is_file())
        }
    )


def read_at(root: Path, ref: str, path: str, *, optional: bool = False) -> bytes:
    if ref == "WORKTREE":
        target = root / path
        if not target.is_file() and optional:
            return b""
        return target.read_bytes()
    return git(root, "show", f"{resolve(root, ref)}:{path}", optional=optional)


def json_at(root: Path, ref: str, path: str) -> Any:
    try:
        return json.loads(read_at(root, ref, path))
    except (json.JSONDecodeError, UnicodeError) as error:
        raise ReleaseError(f"Invalid JSON: {path}") from error


def version_at(root: Path, ref: str) -> str:
    tree = ast.parse(read_at(root, ref, "src/aha/__init__.py"))
    for item in tree.body:
        if isinstance(item, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__version__" for target in item.targets
        ):
            value = ast.literal_eval(item.value)
            if isinstance(value, str) and VERSION_RE.fullmatch(value):
                return value
    raise ReleaseError("aha.__version__ must be a stable X.Y.Z literal.")


def product_file(path: str) -> bool:
    return path.startswith("src/aha/") or path in RECIPE_FILES


def normalized(path: str, content: bytes) -> bytes:
    if Path(path).suffix.lower() in {
        ".py",
        ".toml",
        ".ps1",
        ".txt",
        ".html",
        ".css",
        ".js",
        ".svg",
        ".json",
        ".yml",
        ".yaml",
    }:
        content = content.replace(b"\r\n", b"\n")
    if path == "src/aha/__init__.py":
        return re.sub(rb"(?m)^(__version__\s*=\s*)[\'\"][^\'\"]+[\'\"]", rb'\1"<version>"', content)
    return content


def fingerprints(root: Path, ref: str) -> dict[str, str]:
    groups: dict[str, dict[str, str]] = {
        name: {} for name in ("full", "tray", "materials", "recipe")
    }
    for path in files_at(root, ref):
        if not product_file(path):
            continue
        value = digest(normalized(path, read_at(root, ref, path)))
        groups["full"][path] = value
        if path in RECIPE_FILES:
            groups["recipe"][path] = value
        elif Path(path).name in TRAY_FILES:
            groups["tray"][path] = value
        elif Path(path).name in MATERIAL_FILES:
            groups["materials"][path] = value
    return {name: digest(canonical(values)) for name, values in groups.items()}


def required_checks(root: Path, ref: str, previous: str | None) -> set[str]:
    if not previous:
        return set(CHECKS)
    before, after = fingerprints(root, previous), fingerprints(root, ref)
    if before["recipe"] != after["recipe"]:
        return set(CHECKS)
    old_files, new_files = set(files_at(root, previous)), set(files_at(root, ref))
    known = TRAY_FILES | MATERIAL_FILES | {"__init__.py"}
    for path in old_files ^ new_files:
        if path.startswith("src/aha/") and not path.startswith("src/aha/web/"):
            return set(CHECKS)
    for path in old_files & new_files:
        if (
            path.startswith("src/aha/")
            and not path.startswith("src/aha/web/")
            and Path(path).name not in known
            and read_at(root, previous, path) != read_at(root, ref, path)
        ):
            return set(CHECKS)
    result: set[str] = set()
    if before["tray"] != after["tray"]:
        result |= {"tray", "browser"}
    if before["materials"] != after["materials"]:
        result |= {"excel", "print"}
    return result


def text_field(value: Any, name: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 8000
        or any(ord(char) < 32 and char not in "\n\t" for char in value)
    ):
        raise ReleaseError(f"Invalid non-empty text field: {name}")
    return value.strip()


def fragments(
    root: Path, ref: str, base: str | None, *, immutable: bool = True
) -> list[dict[str, Any]]:
    old = (
        {
            path: read_at(root, base, path)
            for path in files_at(root, base)
            if path.startswith(".release/changes/") and path.endswith(".json")
        }
        if base
        else {}
    )
    current = {
        path: read_at(root, ref, path)
        for path in files_at(root, ref)
        if path.startswith(".release/changes/") and path.endswith(".json")
    }
    for path, content in old.items():
        if immutable and current.get(path) != content:
            raise ReleaseError(f"Published release fragment is immutable: {path}")
    found: list[dict[str, Any]] = []
    ids: set[str] = set()
    for path, content in current.items():
        try:
            item = json.loads(content)
        except (json.JSONDecodeError, UnicodeError) as error:
            raise ReleaseError(f"Invalid release fragment JSON: {path}") from error
        if not isinstance(item, dict) or set(item) - {
            "id",
            "kind",
            "title",
            "description",
            "highlight",
            "upgrade_notes",
            "reason",
        }:
            raise ReleaseError(f"Unknown release fragment fields: {path}")
        identifier = item.get("id")
        if (
            not isinstance(identifier, str)
            or not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,100}", identifier)
            or identifier in ids
        ):
            raise ReleaseError(f"Invalid or duplicate release fragment id: {path}")
        ids.add(identifier)
        if item.get("kind") not in KINDS:
            raise ReleaseError(f"Invalid release fragment kind: {path}")
        for field in ("title", "description"):
            item[field] = text_field(item.get(field), field)
        notes = item.get("upgrade_notes", [])
        if not isinstance(notes, list) or any(not isinstance(line, str) for line in notes):
            raise ReleaseError(f"upgrade_notes must be a text list: {path}")
        item["upgrade_notes"] = [text_field(line, "upgrade_notes") for line in notes]
        if not isinstance(item.get("highlight", False), bool):
            raise ReleaseError(f"highlight must be boolean: {path}")
        if item["kind"] == "breaking" and not notes:
            raise ReleaseError(f"Breaking change needs upgrade instructions: {path}")
        if item["kind"] == "internal":
            text_field(item.get("reason"), "internal reason")
        if path not in old or not immutable and old[path] != content:
            found.append(item)
    return sorted(found, key=lambda item: item["id"])


def render_notes(
    root: Path, ref: str, base: str | None, version: str, repo: str, previous_tag: str | None = None
) -> tuple[str, list[str]]:
    if not VERSION_RE.fullmatch(version):
        raise ReleaseError("Invalid release version.")
    changes = fragments(root, ref, base)
    visible = [item for item in changes if item["kind"] != "internal"]
    if not visible:
        raise ReleaseError("No user-facing changes; do not create an empty release.")
    lines = [f"# What’s New · v{version}", ""]
    breaking = [item for item in visible if item["kind"] == "breaking"]
    if breaking:
        lines += ["## 兼容性与升级提醒", ""]
        for item in breaking:
            lines += [f"- **{item['title']}**：{item['description']}"]
    if not previous_tag:
        overview = read_at(root, ref, ".release/overview.md", optional=True).decode().strip()
        if overview:
            lines += ["## 首次公开发布", "", overview, ""]
    highlights = [item for item in visible if item.get("highlight")]
    if highlights:
        lines += ["## 本次亮点", ""]
        lines += [f"- **{item['title']}**" for item in highlights]
        lines += [""]
    for kind, title in KINDS.items():
        entries = [item for item in visible if item["kind"] == kind]
        if not entries or kind == "breaking":
            continue
        lines += [f"## {title}", ""]
        lines += [f"- **{item['title']}**：{item['description']}" for item in entries]
        lines += [""]
    upgrades = list(dict.fromkeys(line for item in visible for line in item["upgrade_notes"]))
    if upgrades:
        lines += ["## 升级说明", "", *[f"- {line}" for line in upgrades], ""]
    url = f"https://github.com/{repo}"
    tag = f"v{version}"
    lines += [
        "## 下载与完整变更",
        "",
        f"- [Windows x64 单文件 EXE]({url}/releases/download/{tag}/aha-{version}-windows-x64.exe)",
        f"- [SHA256 校验信息]({url}/releases/download/{tag}/SHA256SUMS.txt)",
    ]
    if previous_tag:
        lines += [f"- [完整变更]({url}/compare/{previous_tag}...{tag})"]
    else:
        lines += [f"- [本版源码]({url}/tree/{tag})（首次发布，没有前版标签）"]
    return "\n".join(lines).strip() + "\n", [item["id"] for item in changes]


def candidate_notes(
    root: Path, ref: str, base: str | None, repo: str, previous_tag: str | None
) -> tuple[str, dict[str, Any]]:
    version = version_at(root, ref)
    manifest = json_at(root, ref, ".release-please-manifest.json")
    if manifest != {".": version}:
        raise ReleaseError("Release Please manifest and authoritative version differ.")
    body, identifiers = render_notes(root, ref, base, version, repo, previous_tag)
    metadata = {
        "schema_version": 1,
        "version": version,
        "base_sha": base,
        "previous_tag": previous_tag,
        "fragment_ids": identifiers,
        "notes_sha256": digest(body.encode()),
    }
    return body, metadata


def validate_candidate(root: Path, ref: str, candidate: dict[str, Any], repo: str) -> str:
    source = resolve(root, ref)
    if source != candidate["source_sha"]:
        raise ReleaseError("Candidate source SHA changed.")
    version = version_at(root, ref)
    if candidate["version"] != version or candidate["tag"] != f"v{version}":
        raise ReleaseError("Candidate tag/version do not identify this source.")
    body, metadata = candidate_notes(
        root, ref, candidate.get("previous_sha"), repo, candidate.get("previous_tag")
    )
    if read_at(root, ref, f"docs/releases/v{version}.md").decode() != body:
        raise ReleaseError("Reviewed What's New differs from current candidate changes.")
    if json_at(root, ref, f".release/candidates/v{version}.json") != metadata:
        raise ReleaseError("Reviewed candidate metadata differs from current source.")
    return body


def acceptance_missing(
    root: Path,
    ref: str,
    receipt_ref: str,
    previous: str | None,
    artifact_sha: str,
    runtime_sha: str,
    previous_runtime_sha: str | None = None,
) -> list[str]:
    required = required_checks(root, ref, previous)
    if previous and runtime_sha != previous_runtime_sha:
        required = set(CHECKS)
    if not required:
        return []
    current = fingerprints(root, ref)
    passed: set[str] = set()
    for path in files_at(root, receipt_ref):
        if not path.startswith(".release/acceptance/") or not path.endswith(".json"):
            continue
        item = json_at(root, receipt_ref, path)
        if not isinstance(item, dict) or item.get("schema_version") != 1:
            raise ReleaseError(f"Invalid acceptance receipt: {path}")
        if not SHA_RE.fullmatch(str(item.get("source_sha", ""))):
            raise ReleaseError(f"Receipt source SHA is invalid: {path}")
        if not DIGEST_RE.fullmatch(str(item.get("runtime_sha256", ""))):
            raise ReleaseError(f"Receipt runtime identity is invalid: {path}")
        try:
            completed = datetime.fromisoformat(item["completed_at"])
            if completed.utcoffset() is None:
                raise ValueError("timezone required")
        except (KeyError, TypeError, ValueError) as error:
            raise ReleaseError(f"Receipt completion time is invalid: {path}") from error
        checks = item.get("checks")
        evidence = item.get("evidence")
        if (
            not isinstance(checks, list)
            or set(checks) - CHECKS
            or len(set(checks)) != len(checks)
            or not isinstance(evidence, list)
        ):
            raise ReleaseError(f"Receipt checks/evidence are invalid: {path}")
        supported = {
            line.get("scope")
            for line in evidence
            if isinstance(line, dict)
            and DIGEST_RE.fullmatch(str(line.get("sha256", "")))
            and isinstance(line.get("description"), str)
            and line["description"].strip()
        }
        if set(checks) - supported:
            raise ReleaseError(f"Receipt lacks evidence for its claimed checks: {path}")
        recorded = item.get("fingerprints", {})
        if (
            not isinstance(recorded, dict)
            or set(recorded) != {"full", "tray", "materials", "recipe"}
            or any(not DIGEST_RE.fullmatch(str(value)) for value in recorded.values())
        ):
            raise ReleaseError(f"Receipt fingerprints are invalid: {path}")
        ensure_commit(root, item["source_sha"])
        if recorded != fingerprints(root, item["source_sha"]):
            raise ReleaseError(f"Receipt fingerprints do not identify its tested source: {path}")
        if item["runtime_sha256"] != runtime_sha:
            continue
        if not previous and (
            item.get("candidate_source_sha") != resolve(root, ref)
            or item.get("artifact_sha256") != artifact_sha
        ):
            continue
        for check in checks:
            scope = (
                "tray"
                if check in {"tray", "browser"}
                else "materials"
                if check in {"excel", "print"}
                else "full"
            )
            if (
                recorded.get(scope) == current[scope]
                and recorded.get("recipe") == current["recipe"]
            ):
                passed.add(check)
    return sorted(required - passed)


def validate_changes(root: Path, ref: str, base: str) -> None:
    current, previous = set(files_at(root, ref)), set(files_at(root, base))
    modified = {
        path
        for path in current | previous
        if normalized(path, read_at(root, ref, path, optional=True))
        != normalized(path, read_at(root, base, path, optional=True))
    }
    changes = fragments(root, ref, base, immutable=False)
    relevant = {path for path in modified if product_file(path)}
    version_only = relevant == {"src/aha/__init__.py"} and (
        normalized("src/aha/__init__.py", read_at(root, ref, "src/aha/__init__.py"))
        == normalized("src/aha/__init__.py", read_at(root, base, "src/aha/__init__.py"))
    )
    if relevant and not version_only and not changes:
        raise ReleaseError(
            "Product/build changes require a reviewed .release/changes JSON fragment."
        )
    version_at(root, ref)


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> Any:
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if (
            redirected
            and urllib.parse.urlsplit(req.full_url).netloc != urllib.parse.urlsplit(newurl).netloc
        ):
            redirected.remove_header("Authorization")
        return redirected


class GitHub:
    def __init__(self, repo: str, token: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo) or not token:
            raise ReleaseError("GITHUB_REPOSITORY and GH_TOKEN are required.")
        self.repo, self.token = repo, token
        self.opener = urllib.request.build_opener(SafeRedirect())

    def request(
        self, method: str, path: str, data: Any = None, *, raw: bool = False, upload: bool = False
    ) -> Any:
        host = "https://uploads.github.com" if upload else "https://api.github.com"
        target = f"{host}/repos/{self.repo}{path}"
        body = data if isinstance(data, bytes) else canonical(data) if data is not None else None
        headers = {
            "Authorization": f"Bearer {self.token}",
            "User-Agent": "aha-release",
            "Accept": "application/octet-stream" if raw else "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if body is not None:
            headers["Content-Type"] = "application/octet-stream" if upload else "application/json"
        try:
            with self.opener.open(
                urllib.request.Request(target, body, headers, method=method), timeout=60
            ) as response:
                value = response.read(128 * 1024 * 1024)
                return value if raw else json.loads(value) if value else None
        except urllib.error.HTTPError as error:
            if error.code == 404 and method in {"GET", "DELETE"}:
                return None
            raise ReleaseError(f"GitHub {method} failed with HTTP {error.code}.") from None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            raise ReleaseError(
                "GitHub request failed; no release was declared successful."
            ) from error

    def pages(self, path: str) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        separator = "&" if "?" in path else "?"
        for page in range(1, 101):
            items = self.request("GET", f"{path}{separator}per_page=100&page={page}")
            if not isinstance(items, list):
                raise ReleaseError("GitHub collection is unavailable.")
            result.extend(items)
            if len(items) < 100:
                return result
        raise ReleaseError("GitHub collection exceeds the safe scan limit.")


def release_identity(release: dict[str, Any]) -> dict[str, Any]:
    body = release.get("body") or ""
    match = re.search(re.escape(RELEASE_MARKER) + r"(\{[^\n]+\}) -->", body)
    if not match:
        raise ReleaseError("Existing release is not an owned aha candidate; refusing overwrite.")
    try:
        value = json.loads(match.group(1))
    except json.JSONDecodeError as error:
        raise ReleaseError("Existing candidate identity is invalid.") from error
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ReleaseError("Unsupported candidate identity.")
    return value


def release_pr_identity(pr: dict[str, Any], repo: str) -> bool:
    base, head, user = pr.get("base") or {}, pr.get("head") or {}, pr.get("user") or {}
    head_repo = head.get("repo") or {}
    return bool(
        base.get("ref") == "main"
        and head_repo.get("full_name") == repo
        and head.get("ref") == RELEASE_BRANCH
        and user.get("login") == "github-actions[bot]"
    )


def trusted_pr(pr: dict[str, Any], repo: str) -> bool:
    return bool(
        pr.get("merged_at")
        and release_pr_identity(pr, repo)
        and any(
            label.get("name") in {"autorelease: pending", "autorelease: tagged"}
            for label in pr.get("labels", [])
        )
    )


def ensure_commit(root: Path, sha: str) -> None:
    if not SHA_RE.fullmatch(sha):
        raise ReleaseError("Candidate commit is invalid.")
    if not git(root, "cat-file", "-t", sha, optional=True):
        git(root, "fetch", "origin", "main")
    if not git(root, "cat-file", "-t", sha, optional=True):
        # Squash/rebase merges may leave a tested PR commit outside main history.
        git(root, "fetch", "origin", sha)
    resolve(root, sha)


def discover(root: Path, api: GitHub) -> dict[str, Any] | None:
    releases = api.pages("/releases")
    public = [item for item in releases if not item["draft"] and not item["prerelease"]]
    public.sort(
        key=lambda item: tuple(int(part) for part in item["tag_name"].removeprefix("v").split("."))
    )
    latest = public[-1] if public else None
    previous_sha = release_identity(latest)["source_sha"] if latest else None
    if previous_sha:
        ensure_commit(root, previous_sha)
    prs = api.pages("/pulls?state=closed&sort=updated&direction=desc")
    for pr in sorted(prs, key=lambda item: item.get("merged_at") or ""):
        if not trusted_pr(pr, api.repo):
            continue
        source = pr.get("merge_commit_sha", "")
        ensure_commit(root, source)
        main = api.request("GET", "/git/ref/heads/main")["object"]["sha"]
        ensure_commit(root, main)
        if subprocess.run(
            ["git", "-C", str(root), "merge-base", "--is-ancestor", source, main],
            capture_output=True,
        ).returncode:
            raise ReleaseError("Merged release source is not on trusted main.")
        version = version_at(root, source)
        tag = f"v{version}"
        existing = next((item for item in releases if item["tag_name"] == tag), None)
        if existing:
            identity = release_identity(existing)
            if identity.get("source_sha") != source:
                raise ReleaseError("Existing release tag points at a different candidate.")
            if not existing["draft"]:
                continue
        if latest is not None and tuple(map(int, version.split("."))) <= tuple(
            map(int, latest["tag_name"].removeprefix("v").split("."))
        ):
            raise ReleaseError("An unpublished older release would regress the public version.")
        candidate = {
            "schema_version": 1,
            "version": version,
            "tag": tag,
            "source_sha": source,
            "pr_number": pr["number"],
            "receipt_sha": main,
            "previous_sha": previous_sha,
            "previous_tag": latest["tag_name"] if latest else None,
            "needs_build": not existing or not complete_assets(existing, version),
        }
        if existing and candidate["needs_build"]:
            info_asset = next(
                (item for item in existing.get("assets", []) if item["name"] == "build-info.json"),
                None,
            )
            if info_asset:
                try:
                    info = json.loads(
                        api.request("GET", f"/releases/assets/{info_asset['id']}", raw=True)
                    )
                except (TypeError, json.JSONDecodeError) as error:
                    raise ReleaseError("Partial draft has invalid recovery metadata.") from error
                run_id = info.get("actions_run_id")
                artifact = info.get("actions_artifact")
                if (
                    info.get("source_sha") != source
                    or info.get("version") != version
                    or not isinstance(run_id, str)
                    or not run_id.isdigit()
                    or not isinstance(artifact, str)
                    or not re.fullmatch(rf"aha-assets-{source}-[1-9][0-9]*", artifact)
                ):
                    raise ReleaseError("Partial draft recovery identity is invalid.")
                candidate.update(
                    needs_build=False, recovery_run_id=run_id, recovery_artifact=artifact
                )
        validate_candidate(root, source, candidate, api.repo)
        return candidate
    return None


def complete_assets(release: dict[str, Any], version: str) -> bool:
    names = {item["name"] for item in release.get("assets", [])}
    return names == {f"aha-{version}-windows-x64.exe", "SHA256SUMS.txt", "build-info.json"}


def validation_base(root: Path, ref: str, api: GitHub) -> str:
    public = [
        item for item in api.pages("/releases") if not item["draft"] and not item["prerelease"]
    ]
    public.sort(key=lambda item: tuple(map(int, item["tag_name"].removeprefix("v").split("."))))
    if public:
        base = release_identity(public[-1])["source_sha"]
        if not isinstance(base, str) or not SHA_RE.fullmatch(base):
            raise ReleaseError("Public release source identity is invalid.")
        ensure_commit(root, base)
        return base
    config = json_at(root, ref, "release-please-config.json")
    base = resolve(root, config["bootstrap-sha"])
    if base == resolve(root, ref):
        raise ReleaseError(
            "Bootstrap equals unchecked HEAD; choose a real prior validation boundary."
        )
    return base


def mark_tagged(api: GitHub, number: int) -> None:
    if api.request("GET", "/labels/autorelease%3A%20tagged") is None:
        api.request(
            "POST",
            "/labels",
            {
                "name": "autorelease: tagged",
                "color": "0e8a16",
                "description": "Verified aha version has been published",
            },
        )
    api.request("POST", f"/issues/{number}/labels", {"labels": ["autorelease: tagged"]})
    api.request("DELETE", f"/issues/{number}/labels/autorelease%3A%20pending")


def reconcile_published(root: Path, api: GitHub) -> None:
    public = {
        item["tag_name"]: item
        for item in api.pages("/releases")
        if not item["draft"] and not item["prerelease"]
    }
    for pr in api.pages("/pulls?state=closed&sort=updated&direction=desc"):
        if not trusted_pr(pr, api.repo) or not any(
            item.get("name") == "autorelease: pending" for item in pr.get("labels", [])
        ):
            continue
        source = pr["merge_commit_sha"]
        ensure_commit(root, source)
        version = version_at(root, source)
        existing = public.get(f"v{version}")
        if not existing:
            continue
        metadata = json_at(root, source, f".release/candidates/v{version}.json")
        candidate = {
            "version": version,
            "tag": f"v{version}",
            "source_sha": source,
            "previous_sha": metadata["base_sha"],
            "previous_tag": metadata["previous_tag"],
        }
        body = validate_candidate(root, source, candidate, api.repo)
        if release_identity(existing).get("source_sha") != source:
            raise ReleaseError("Published source differs; refusing label reconciliation.")
        tag = api.request("GET", f"/git/ref/tags/v{version}")
        if not tag or tag["object"]["type"] != "commit" or tag["object"]["sha"] != source:
            raise ReleaseError("Published tag differs; refusing label reconciliation.")
        check_remote_assets(api, existing, candidate, body, root)
        mark_tagged(api, pr["number"])


def prepare_pr(root: Path, api: GitHub, prs: list[dict[str, Any]]) -> None:
    public = [
        item for item in api.pages("/releases") if not item["draft"] and not item["prerelease"]
    ]
    public.sort(key=lambda item: tuple(map(int, item["tag_name"].removeprefix("v").split("."))))
    latest = public[-1] if public else None
    base = release_identity(latest)["source_sha"] if latest else None
    for output in prs:
        number = output.get("number")
        if not isinstance(number, int):
            raise ReleaseError("Release Please output lacks a pull request number.")
        pr = api.request("GET", f"/pulls/{number}")
        if (
            not pr
            or pr["state"] != "open"
            or not release_pr_identity(pr, api.repo)
        ):
            raise ReleaseError("Refusing to update an untrusted release PR.")
        head, branch = pr["head"]["sha"], pr["head"]["ref"]
        git(root, "fetch", "origin", branch)
        ensure_commit(root, head)
        if base:
            ensure_commit(root, base)
        body, metadata = candidate_notes(
            root, head, base, api.repo, latest["tag_name"] if latest else None
        )
        version = version_at(root, head)
        contents = {
            f"docs/releases/v{version}.md": body,
            f".release/candidates/v{version}.json": json.dumps(
                metadata, ensure_ascii=False, indent=2
            )
            + "\n",
        }
        updates = {
            path: value
            for path, value in contents.items()
            if read_at(root, head, path, optional=True).decode() != value
        }
        if updates:
            commit = api.request("GET", f"/git/commits/{head}")
            tree = api.request(
                "POST",
                "/git/trees",
                {
                    "base_tree": commit["tree"]["sha"],
                    "tree": [
                        {"path": path, "mode": "100644", "type": "blob", "content": value}
                        for path, value in updates.items()
                    ],
                },
            )
            new = api.request(
                "POST",
                "/git/commits",
                {
                    "message": "chore(release): 更新中文版 What’s New",
                    "tree": tree["sha"],
                    "parents": [head],
                },
            )
            api.request("PATCH", f"/git/refs/heads/{branch}", {"sha": new["sha"], "force": False})
            head = new["sha"]
        previous_body = pr.get("body") or ""
        clean = re.sub(
            re.escape(NOTE_START) + r".*?" + re.escape(NOTE_END), "", previous_body, flags=re.DOTALL
        ).rstrip()
        api.request(
            "PATCH", f"/pulls/{number}", {"body": f"{clean}\n\n{NOTE_START}\n{body}{NOTE_END}\n"}
        )
        # Dispatch the FINAL generated commit; token-triggered PR events may wait for approval.
        api.request(
            "POST",
            "/actions/workflows/ci.yml/dispatches",
            {"ref": branch, "inputs": {"expected_sha": head}},
        )


def installed_runtime() -> dict[str, Any]:
    package_names = {
        item.metadata["Name"].lower().replace("_", "-")
        for item in importlib.metadata.distributions()
        if item.metadata["Name"]
    }
    return {
        "windows": sys.platform == "win32",
        "isolated": sys.prefix != sys.base_prefix,
        "bits": struct.calcsize("P") * 8,
        "python": list(sys.version_info[:3]),
        "machine": platform.machine(),
        "sqlite": list(sqlite3.sqlite_version_info),
        "sqlite_version": sqlite3.sqlite_version,
        "packages": {
            # Match the interpreter's active metadata provider. A later stale
            # source egg-info must not overwrite the installed distribution.
            name: importlib.metadata.version(name)
            for name in sorted(package_names)
        },
    }


def bundle_runtime(root: Path, probe: dict[str, Any]) -> dict[str, Any]:
    from aha.migrations import sqlite_wal_safe

    actual = installed_runtime()
    config = json_at(root, "HEAD", ".release/runtime.json")
    if (
        actual["windows"] is not True
        or actual["isolated"] is not True
        or actual["bits"] != 64
        or not sqlite_wal_safe(tuple(actual["sqlite"]))
    ):
        raise ReleaseError("Bundle must run in the same safe native Windows x64 build venv.")
    for field in ("windows", "bits", "isolated", "machine", "sqlite", "sqlite_version"):
        if actual[field] != probe.get(field):
            raise ReleaseError(f"Bundle runtime differs from the build probe: {field}")
    if actual["python"][:2] != probe.get("python") or ".".join(
        map(str, actual["python"])
    ) != config.get("python"):
        raise ReleaseError("Bundle Python patch version differs from the reviewed recipe.")
    for line in read_at(root, "HEAD", "scripts/requirements-build.txt").decode().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        name, separator, expected = line.partition("==")
        if not separator or actual["packages"].get(name.lower().replace("_", "-")) != expected:
            raise ReleaseError("Installed build dependencies differ from the fixed recipe.")
    if actual["packages"].get("aha-usage") != version_at(root, "HEAD"):
        raise ReleaseError("Installed package metadata differs from the source version.")
    return actual


def runtime_digest(root: Path, ref: str, actual: dict[str, Any]) -> str:
    pinned = {}
    for line in read_at(root, ref, "scripts/requirements-build.txt").decode().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        name, separator, expected = line.partition("==")
        key = name.lower().replace("_", "-")
        if not separator or actual.get("packages", {}).get(key) != expected:
            raise ReleaseError("Runtime digest does not match fixed builder dependencies.")
        pinned[key] = expected
    fields = ("python", "sqlite", "sqlite_version", "windows", "bits", "machine")
    if any(field not in actual for field in fields):
        raise ReleaseError("Runtime digest needs full native runtime facts.")
    return digest(canonical({**{field: actual[field] for field in fields}, "packages": pinned}))


def bundle(
    root: Path,
    candidate: dict[str, Any],
    exe: Path,
    directory: Path,
    onefile: Path,
    runtime: Path,
    output: Path,
    repo: str,
) -> None:
    body = validate_candidate(root, "HEAD", candidate, repo)
    checks = [json.loads(path.read_text(encoding="utf-8")) for path in (directory, onefile)]
    fingerprint = digest(exe.read_bytes())
    version = candidate["version"]
    for check in checks:
        if check.get("verified") is not True or check.get("version") != version:
            raise ReleaseError(
                "Both native artifact verification reports must pass for this version."
            )
    if checks[1].get("executable_sha256") != fingerprint:
        raise ReleaseError("OneFile report does not identify the selected EXE bytes.")
    if output.exists() and any(output.iterdir()):
        raise ReleaseError("Asset output must be empty; do not silently reuse stale files.")
    output.mkdir(parents=True, exist_ok=True)
    name = f"aha-{version}-windows-x64.exe"
    shutil.copyfile(exe, output / name)
    probe = json.loads(runtime.read_text(encoding="utf-8"))
    actual_runtime = bundle_runtime(root, probe)
    info = {
        "schema_version": 1,
        "version": version,
        "source_sha": candidate["source_sha"],
        "tag": candidate["tag"],
        "notes_sha256": digest(body.encode()),
        "fingerprints": fingerprints(root, "HEAD"),
        "runtime": probe,
        "build_runtime": actual_runtime,
        "runtime_sha256": runtime_digest(root, "HEAD", actual_runtime),
        "executable": {"name": name, "sha256": fingerprint, "size": exe.stat().st_size},
        "automatic_checks": [
            {
                key: value
                for key, value in item.items()
                if key
                in {
                    "verified",
                    "version",
                    "executable_sha256",
                    "pe_version",
                    "scopes",
                    "material_sha256",
                }
            }
            for item in checks
        ],
    }
    run_id = os.environ.get("GITHUB_RUN_ID")
    if run_id:
        info["actions_run_id"] = run_id
        attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
        info["actions_artifact"] = f"aha-assets-{candidate['source_sha']}-{attempt}"
    write_json(output / "build-info.json", info)
    hashes = [
        (name, fingerprint),
        ("build-info.json", digest((output / "build-info.json").read_bytes())),
    ]
    (output / "SHA256SUMS.txt").write_bytes(
        "".join(f"{value}  {name}\n" for name, value in hashes).encode()
    )


def check_remote_assets(
    api: GitHub, release: dict[str, Any], candidate: dict[str, Any], body: str, root: Path
) -> dict[str, Any]:
    if not complete_assets(release, candidate["version"]):
        raise ReleaseError("Candidate asset set is incomplete or contains unexpected files.")
    assets = {
        item["name"]: api.request("GET", f"/releases/assets/{item['id']}", raw=True)
        for item in release["assets"]
    }
    try:
        info = json.loads(assets["build-info.json"])
    except (TypeError, json.JSONDecodeError) as error:
        raise ReleaseError("Candidate build-info is invalid.") from error
    if not isinstance(info, dict):
        raise ReleaseError("Candidate build-info must be an object.")
    expected = {
        "schema_version": 1,
        "version": candidate["version"],
        "source_sha": candidate["source_sha"],
        "tag": candidate["tag"],
        "notes_sha256": digest(body.encode()),
        "fingerprints": fingerprints(root, candidate["source_sha"]),
    }
    if any(info.get(key) != value for key, value in expected.items()):
        raise ReleaseError("Remote asset provenance does not match the candidate source and notes.")
    if info.get("runtime_sha256") != runtime_digest(
        root, candidate["source_sha"], info.get("build_runtime", {})
    ):
        raise ReleaseError("Remote native runtime digest differs from build-info.")
    name = f"aha-{candidate['version']}-windows-x64.exe"
    selected = assets[name]
    if not selected or info.get("executable") != {
        "name": name,
        "sha256": digest(selected),
        "size": len(selected),
    }:
        raise ReleaseError("Remote EXE does not match build-info.")
    sums = f"{digest(selected)}  {name}\n{digest(assets['build-info.json'])}  build-info.json\n"
    if assets["SHA256SUMS.txt"] != sums.encode():
        raise ReleaseError("Remote SHA256SUMS does not match the selected asset bytes.")
    checks = info.get("automatic_checks", [])
    if (
        len(checks) != 2
        or any(
            item.get("verified") is not True or item.get("version") != candidate["version"]
            for item in checks
        )
        or checks[1].get("executable_sha256") != digest(selected)
    ):
        raise ReleaseError("Remote native verification evidence is incomplete.")
    return info


def stage(
    root: Path, api: GitHub, candidate: dict[str, Any], assets: Path | None
) -> dict[str, Any]:
    source = candidate["source_sha"]
    body = validate_candidate(root, source, candidate, api.repo)
    identity = {
        "schema_version": 1,
        "version": candidate["version"],
        "source_sha": source,
        "notes_sha256": digest(body.encode()),
    }
    complete_body = body + "\n" + RELEASE_MARKER + json.dumps(identity, sort_keys=True) + " -->\n"
    existing = next(
        (item for item in api.pages("/releases") if item["tag_name"] == candidate["tag"]), None
    )
    if existing:
        if release_identity(existing) != identity:
            raise ReleaseError("Release identity conflicts with this candidate.")
        release = existing
    else:
        tag = api.request("GET", f"/git/ref/tags/{candidate['tag']}")
        if tag:
            raise ReleaseError(
                "An existing tag without an owned release must be reviewed manually."
            )
        release = api.request(
            "POST",
            "/releases",
            {
                "tag_name": candidate["tag"],
                "target_commitish": source,
                "name": f"aha {candidate['tag']}",
                "body": complete_body,
                "draft": True,
                "prerelease": False,
            },
        )
    if assets and release["draft"]:
        local = sorted(
            assets.iterdir(), key=lambda path: (path.name != "build-info.json", path.name)
        )
        wanted = {
            f"aha-{candidate['version']}-windows-x64.exe",
            "SHA256SUMS.txt",
            "build-info.json",
        }
        if {path.name for path in local} != wanted or any(not path.is_file() for path in local):
            raise ReleaseError("Only the exact verified asset set may be uploaded.")
        remote = {item["name"]: item for item in release.get("assets", [])}
        for path in local:
            payload = path.read_bytes()
            if path.name in remote:
                actual = api.request("GET", f"/releases/assets/{remote[path.name]['id']}", raw=True)
                if actual != payload:
                    raise ReleaseError("Draft asset differs; explicit reviewed reset is required.")
                continue
            api.request(
                "POST",
                f"/releases/{release['id']}/assets?name={urllib.parse.quote(path.name)}",
                payload,
                upload=True,
            )
    release = api.request("GET", f"/releases/{release['id']}")
    info = check_remote_assets(api, release, candidate, body, root)
    if not release["draft"]:
        tag = api.request("GET", f"/git/ref/tags/{candidate['tag']}")
        if not tag or tag["object"]["type"] != "commit" or tag["object"]["sha"] != source:
            raise ReleaseError("Published tag does not identify the verified source.")
        mark_tagged(api, candidate["pr_number"])
        return {"state": "already_published", "url": release["html_url"]}
    # Read receipts from a fixed trusted main commit, independent from the built M.
    receipt_sha = api.request("GET", "/git/ref/heads/main")["object"]["sha"]
    ensure_commit(root, receipt_sha)
    previous_runtime_sha = None
    if candidate.get("previous_sha"):
        previous_release = next(
            (
                item
                for item in api.pages("/releases")
                if item["tag_name"] == candidate["previous_tag"]
            ),
            None,
        )
        if not previous_release or previous_release["draft"]:
            raise ReleaseError("Previous public release is unavailable for runtime comparison.")
        if release_identity(previous_release).get("source_sha") != candidate["previous_sha"]:
            raise ReleaseError("Previous public source changed.")
        previous_info_asset = next(
            (
                item
                for item in previous_release.get("assets", [])
                if item["name"] == "build-info.json"
            ),
            None,
        )
        if previous_info_asset:
            previous_info = json.loads(
                api.request("GET", f"/releases/assets/{previous_info_asset['id']}", raw=True)
            )
            previous_runtime_sha = previous_info.get("runtime_sha256")
    missing = acceptance_missing(
        root,
        source,
        receipt_sha,
        candidate.get("previous_sha"),
        info["executable"]["sha256"],
        info["runtime_sha256"],
        previous_runtime_sha,
    )
    if missing:
        return {
            "state": "awaiting_acceptance",
            "missing": missing,
            "url": release["html_url"],
            "source_sha": source,
            "artifact_sha256": info["executable"]["sha256"],
            "runtime_sha256": info["runtime_sha256"],
            "receipt_sha": receipt_sha,
        }
    # The tag may be created lazily by publishing. Refuse a conflicting tag rather than moving it.
    tag = api.request("GET", f"/git/ref/tags/{candidate['tag']}")
    if tag and (tag["object"]["type"] != "commit" or tag["object"]["sha"] != source):
        raise ReleaseError("Candidate tag does not identify the verified source.")
    published = api.request(
        "PATCH",
        f"/releases/{release['id']}",
        {"draft": False, "make_latest": "true", "target_commitish": source},
    )
    if published.get("draft") is not False:
        raise ReleaseError("GitHub did not confirm the release was published.")
    number = candidate["pr_number"]
    mark_tagged(api, number)
    return {"state": "published", "url": published["html_url"], "receipt_sha": receipt_sha}


def outputs(values: dict[str, Any]) -> None:
    target = os.environ.get("GITHUB_OUTPUT")
    if target:
        with Path(target).open("a", encoding="utf-8") as stream:
            for key, value in values.items():
                if isinstance(value, (str, bool, int)):
                    stream.write(
                        f"{key}={str(value).lower() if isinstance(value, bool) else value}\n"
                    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("--ref", default="HEAD")
    validate.add_argument("--base", required=True)
    render = sub.add_parser("render")
    render.add_argument("--ref", default="HEAD")
    render.add_argument("--base")
    render.add_argument("--version")
    render.add_argument("--previous-tag")
    render.add_argument("--output", type=Path, required=True)
    finger = sub.add_parser("fingerprints")
    finger.add_argument("--ref", default="HEAD")
    finger.add_argument("--output", type=Path, required=True)
    native = sub.add_parser("runtime")
    native.add_argument("--ref", default="HEAD")
    native.add_argument("--output", type=Path, required=True)
    discovery = sub.add_parser("discover")
    discovery.add_argument("--output", type=Path, required=True)
    sub.add_parser("prepare-pr")
    sub.add_parser("reconcile")
    boundary = sub.add_parser("validation-base")
    boundary.add_argument("--ref", default="HEAD")
    package = sub.add_parser("bundle")
    for option in ("exe", "directory-report", "onefile-report", "runtime", "candidate", "output"):
        package.add_argument(f"--{option}", type=Path, required=True)
    staging = sub.add_parser("stage")
    staging.add_argument("--candidate", type=Path, required=True)
    staging.add_argument("--assets", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    repo = os.environ.get("GITHUB_REPOSITORY", "NightingaleWK/aha")
    try:
        if args.command == "validate":
            validate_changes(root, args.ref, args.base)
            print("Release input checks passed.")
        elif args.command == "render":
            body, _ = render_notes(
                root,
                args.ref,
                args.base,
                args.version or version_at(root, args.ref),
                repo,
                args.previous_tag,
            )
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_bytes(body.encode())
        elif args.command == "fingerprints":
            write_json(args.output, fingerprints(root, args.ref))
        elif args.command == "runtime":
            actual = installed_runtime()
            if (
                actual["windows"] is not True
                or actual["isolated"] is not True
                or actual["bits"] != 64
            ):
                raise ReleaseError("Record runtime evidence from the native Windows x64 test venv.")
            write_json(
                args.output,
                {
                    "schema_version": 1,
                    "build_runtime": actual,
                    "runtime_sha256": runtime_digest(root, args.ref, actual),
                },
            )
        elif args.command == "bundle":
            bundle(
                root,
                json.loads(args.candidate.read_text()),
                args.exe,
                args.directory_report,
                args.onefile_report,
                args.runtime,
                args.output,
                repo,
            )
        else:
            api = GitHub(repo, os.environ.get("GH_TOKEN", ""))
            if args.command == "discover":
                candidate = discover(root, api)
                write_json(args.output, candidate)
                outputs({"has_candidate": candidate is not None, **(candidate or {})})
            elif args.command == "prepare-pr":
                prs = json.loads(os.environ.get("RELEASE_PRS", "[]") or "[]")
                if not isinstance(prs, list):
                    raise ReleaseError("RELEASE_PRS must be an array.")
                prepare_pr(root, api, prs)
            elif args.command == "reconcile":
                reconcile_published(root, api)
            elif args.command == "validation-base":
                print(validation_base(root, args.ref, api))
            elif args.command == "stage":
                result = stage(root, api, json.loads(args.candidate.read_text()), args.assets)
                outputs(result)
                print(json.dumps(result, ensure_ascii=False))
                if os.environ.get("GITHUB_STEP_SUMMARY"):
                    with Path(os.environ["GITHUB_STEP_SUMMARY"]).open(
                        "a", encoding="utf-8"
                    ) as stream:
                        stream.write(f"### aha release: {result['state']}\n\n")
                        stream.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    except (ReleaseError, OSError, json.JSONDecodeError) as error:
        parser.exit(1, f"Release stopped: {error}\n")


if __name__ == "__main__":
    main()
