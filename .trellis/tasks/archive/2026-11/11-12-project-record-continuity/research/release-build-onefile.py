"""Build OneFile only after the reviewed Directory UI and native Office gates."""

from __future__ import annotations

import importlib.metadata
import json
import os
import runpy
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def main():
    source = Path(__file__).resolve().parents[4]
    research = Path(__file__).resolve().parent
    base = runpy.run_path(str(research / "release-build-directory.py"))
    require, digest = base["require"], base["digest"]
    candidate_sha, runtime_sha = base["M"], base["RUNTIME_SHA"]
    task = Path(os.environ["AHA_RELEASE_QA_ROOT"]).resolve()
    marker = json.loads((task / "task-ownership.json").read_text(encoding="utf-8"))
    require(marker.get("task") == "project-record-continuity" and marker.get("purpose") == "release-v050",
            "task_ownership_mismatch")
    require(sys.platform == "win32" and sys.prefix != sys.base_prefix
            and Path(os.environ["USERPROFILE"]).resolve().is_relative_to(task)
            and tuple(sys.version_info[:3]) == (3, 15, 2) and sqlite3.sqlite_version == "3.53.4",
            "expected_private_native_profile_and_runtime_required")
    sys.path.insert(0, str(source / "scripts"))
    import aha
    import release
    from PyInstaller.archive.readers import CArchiveReader

    require(aha.__version__ == importlib.metadata.version("aha-usage") == "0.5.0",
            "source_and_active_package_metadata_must_be_050")
    source_helpers = runpy.run_path(str(research / "release-final-native-checks.py"))
    fingerprints = source_helpers["source_fingerprints"](source, release)
    candidate = json.loads((research / "release-candidate-source.json").read_text(encoding="utf-8"))
    require(candidate["source_sha"] == candidate_sha and candidate["source_fingerprints"] == fingerprints,
            "frozen_candidate_product_or_recipe_changed")
    runtime = release.installed_runtime()
    require(release.runtime_digest(source, "WORKTREE", runtime) == runtime_sha,
            "installed_runtime_differs_from_reviewed_production_recipe")
    directory = json.loads((research / "release-directory-verification.json").read_text(encoding="utf-8"))
    directory_build = json.loads((research / "release-directory-build.json").read_text(encoding="utf-8"))
    ui = json.loads((research / "release-native-ui-directory.json").read_text(encoding="utf-8"))
    materials = json.loads((research / "release-native-materials-directory.json").read_text(encoding="utf-8"))
    directory_exe = task / "build/release/directory/aha/aha.exe"
    directory_sha = digest(directory_exe)
    require(directory_build.get("verified") is True and directory.get("verified") is True
            and directory_build["source_sha"] == directory["source_sha"] == candidate_sha
            and directory["source_fingerprints"] == fingerprints
            and directory_build["executable_sha256"] == directory["executable_sha256"] == directory_sha
            and directory["runtime_sha256"] == runtime_sha, "directory_native_gate_not_current")
    require(ui.get("verified") is True and ui["executable_sha256"] == directory_sha
            and ui["original_facts_unchanged"] is True
            and ui["console_error_count"] == ui["page_error_count"] == 0
            and len(ui["checks"]) == 9 and len(ui["layouts"]) == 5
            and all(item["horizontal_overflow"] is False for item in ui["layouts"]),
            "directory_ui_gate_not_current")
    for name, value in ui["ui_source_sha256"].items():
        require(name in {"app.js", "index.html", "style.css"}
                and digest(source / "src/aha/web" / name) == value, "directory_ui_source_changed")
    require(materials.get("verified") is True and materials["executable_sha256"] == directory_sha
            and materials["ui_report_sha256"] == digest(research / "release-native-ui-directory.json")
            and materials["material_sha256"] == ui["material"]["sha256"]
            and len(materials["excel"]) == 2
            and all(item["all_cells_match"] is True and item["no_formulas"] is True
                    for item in materials["excel"]), "directory_excel_gate_not_current")
    printed = materials["print"]
    pdf = task / printed["pdf_relative_path"]
    require(printed["pages"] == 1 and printed["precise_cost_and_assignment_note_preserved"] is True
            and printed["all_rendered_pages_visually_reviewed"] is True
            and pdf.resolve().is_relative_to(task) and digest(pdf) == printed["pdf_sha256"],
            "directory_a4_gate_or_actual_visual_review_missing")
    report = {"verified": False, "stage": "OneFile", "version": "0.5.0", "source_sha": candidate_sha,
              "source_fingerprints": fingerprints, "runtime_sha256": runtime_sha,
              "actual_build_runtime": runtime, "real_profile_used": False,
              "directory_gates_sha256": {name: digest(research / name) for name in (
                  "release-directory-build.json", "release-directory-verification.json",
                  "release-native-ui-directory.json", "release-native-materials-directory.json")},
              "started_at": datetime.now(timezone.utc).isoformat()}
    report_path = research / "release-onefile-build.json"

    def save():
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def checked(name, arguments):
        log = research / ("release-onefile-" + name + ".log")
        with log.open("w", encoding="utf-8") as stream:
            result = subprocess.run([sys.executable, "-X", "utf8", "-B", *arguments],
                                    cwd=source, stdout=stream, stderr=subprocess.STDOUT)
        report[name + "_returncode"] = result.returncode
        report[name + "_log_sha256"] = digest(log)
        save()
        require(result.returncode == 0, name + "_process_failed")

    try:
        save()
        build = task / "build"
        build_owned = json.loads((build / "task-ownership.json").read_text(encoding="utf-8"))
        require(build_owned.get("task") == marker["task"] and build_owned.get("purpose") == marker["purpose"]
                and build_owned.get("source_sha") == candidate_sha, "build_directory_ownership_mismatch")
        checked("build", [str(source / "scripts/build_windows.py"), "--build-root", str(build),
                          "--stage", "OneFile", "--directory-verified"])
        executable = build / "release/portable/aha.exe"
        report.update(executable=str(executable), executable_sha256=digest(executable))
        archive = CArchiveReader(str(executable))
        private = json.loads((research / "release-private-runtime.json").read_text(encoding="utf-8"))
        for name, evidence in private["extracted_files"].items():
            matches = [member for member in archive.toc if member.replace("\\", "/").split("/")[-1] == name]
            require(len(matches) == 1 and archive.toc[matches[0]][-1] == "b", "bundled_sqlite_entry_ambiguous")
            import hashlib

            require(hashlib.sha256(archive.extract(matches[0])).hexdigest() == evidence["sha256"],
                    "bundled_sqlite_differs_from_reviewed_production_bytes")
        report["bundled_sqlite_matches_verified_public_production_bytes"] = True
        artifact_report = research / "release-onefile-verification.json"
        fixture = task / ("verify-onefile-" + uuid4().hex[:12])
        checked("verification", [str(source / "scripts/verify_windows_artifact.py"), "--exe", str(executable),
                                 "--source-root", str(source), "--data-root", str(fixture), "--report", str(artifact_report)])
        verified = json.loads(artifact_report.read_text(encoding="utf-8"))
        require(verified.get("verified") is True and verified["executable_sha256"] == report["executable_sha256"]
                and verified["version"] == "0.5.0", "standard_native_onefile_gate_failed")
        require(source_helpers["source_fingerprints"](source, release) == fingerprints
                and release.runtime_digest(source, "WORKTREE", release.installed_runtime()) == runtime_sha,
                "source_or_runtime_changed_during_onefile_build")
        verified.update(source_sha=candidate_sha, source_fingerprints=fingerprints, runtime_sha256=runtime_sha,
                        actual_build_runtime=runtime)
        artifact_report.write_text(json.dumps(verified, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        report.update(verified=True, completed_at=datetime.now(timezone.utc).isoformat(),
                      verification_fixture=str(fixture), standard_native_gate_passed=True)
        save()
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except Exception as error:
        report.update(verified=False, failure_type=type(error).__name__,
                      failure_code=str(error) if isinstance(error, RuntimeError) else "native_stage_failed",
                      completed_at=datetime.now(timezone.utc).isoformat())
        save()
        print(json.dumps({"verified": False, "failure_type": type(error).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
