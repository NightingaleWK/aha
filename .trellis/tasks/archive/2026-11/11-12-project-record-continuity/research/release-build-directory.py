"""Build and independently verify the frozen 0.5.0 candidate's native Directory artifact."""

from __future__ import annotations

import hashlib
import json
import os
import runpy
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


M = "12d213b5b3c3c505d24f73fc7888966f24435337"
RUNTIME_SHA = "2d64ab084e0aa6c3d8ffab874ef7a08fd35b4fbf452dc1353e89d06dc7ea8642"


def require(condition, code):
    if not condition:
        raise RuntimeError(code)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    source = Path(__file__).resolve().parents[4]
    research = Path(__file__).resolve().parent
    task = Path(os.environ["AHA_RELEASE_QA_ROOT"]).resolve()
    owned = json.loads((task / "task-ownership.json").read_text(encoding="utf-8"))
    require(owned.get("task") == "project-record-continuity" and owned.get("purpose") == "release-v050",
            "task_ownership_mismatch")
    require(Path(os.environ["USERPROFILE"]).resolve().is_relative_to(task)
            and sys.platform == "win32" and sys.prefix != sys.base_prefix
            and tuple(sys.version_info[:3]) == (3, 15, 2) and sqlite3.sqlite_version == "3.53.4",
            "expected_private_native_profile_and_runtime_required")
    candidate = json.loads((research / "release-candidate-source.json").read_text(encoding="utf-8"))
    installed = json.loads((research / "release-installed-runtime.json").read_text(encoding="utf-8"))
    preflight = json.loads((research / "python315-release.json").read_text(encoding="utf-8"))
    require(candidate["source_sha"] == M and candidate["version"] == "0.5.0"
            and installed.get("verified") is True and installed["runtime_sha256"] == RUNTIME_SHA
            and preflight.get("verified") is True and preflight["tests_run"] == 351,
            "candidate_or_runtime_or_preflight_not_verified")
    sys.path.insert(0, str(source / "scripts"))
    import release

    helpers = runpy.run_path(str(research / "release-final-native-checks.py"))
    fingerprints = helpers["source_fingerprints"](source, release)
    require(fingerprints == candidate["source_fingerprints"] == preflight["source_fingerprints"],
            "candidate_product_or_recipe_changed")
    report = {"verified": False, "source_sha": M, "version": "0.5.0",
              "stage": "Directory", "source_fingerprints": fingerprints,
              "runtime_sha256": RUNTIME_SHA, "real_profile_used": False,
              "started_at": datetime.now(timezone.utc).isoformat()}
    report_path = research / "release-directory-build.json"

    def save():
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def checked(name, arguments):
        log = research / ("release-directory-" + name + ".log")
        with log.open("w", encoding="utf-8") as stream:
            result = subprocess.run([sys.executable, "-X", "utf8", "-B", *arguments],
                                    cwd=source, stdout=stream, stderr=subprocess.STDOUT)
        report[name + "_returncode"] = result.returncode
        report[name + "_log_sha256"] = digest(log)
        save()
        require(result.returncode == 0, name + "_process_failed")

    try:
        save()
        checked("metadata", ["-m", "pip", "install", "--disable-pip-version-check", "--no-index",
                             "--no-build-isolation", "-e", str(source)])
        # PEP660 prepares metadata in its temporary build directory; an older
        # source egg-info may still take priority through PYTHONPATH. Regenerate
        # that legitimate source metadata with the fixed setuptools backend.
        checked("egg-info", ["-c", "from setuptools import setup; setup(script_args=['egg_info'])"])
        probe = subprocess.run([sys.executable, "-X", "utf8", "-B", "-c",
            "import aha,importlib.metadata,json; print(json.dumps({'module_version':aha.__version__,"
            "'active_provider_version':importlib.metadata.version('aha-usage'),'source_package':aha.__file__}))"],
            cwd=source, capture_output=True, text=True, encoding="utf-8", check=True)
        provider = json.loads(probe.stdout)
        require(provider["module_version"] == provider["active_provider_version"] == "0.5.0"
                and Path(provider["source_package"]).resolve().is_relative_to(source / "src"),
                "source_and_active_package_metadata_must_be_050")
        report["active_provider"] = provider
        build = task / "build"
        if not build.exists():
            build.mkdir(exist_ok=False)
            (build / "task-ownership.json").write_text(
                json.dumps({"task": owned["task"], "purpose": owned["purpose"], "source_sha": M,
                            "cleanup_after_release": True}) + "\n", encoding="utf-8")
        else:
            build_owned = json.loads((build / "task-ownership.json").read_text(encoding="utf-8"))
            require(build_owned.get("task") == owned["task"] and build_owned.get("purpose") == owned["purpose"],
                    "build_directory_ownership_mismatch")
        checked("build", [str(source / "scripts/build_windows.py"), "--build-root", str(build), "--stage", "Directory"])
        executable = build / "release/directory/aha/aha.exe"
        report["executable"] = str(executable)
        report["executable_sha256"] = digest(executable)
        runtime_probe = json.loads((build / "runtime-versions.json").read_text(encoding="utf-8"))
        require(runtime_probe["application_version"] == "0.5.0" and runtime_probe["python"] == [3, 15]
                and runtime_probe["sqlite"] == [3, 53, 4] and runtime_probe["isolated"] is True,
                "built_runtime_probe_mismatch")
        report["actual_build_runtime"] = runtime_probe
        private = json.loads((research / "release-private-runtime.json").read_text(encoding="utf-8"))
        for name, evidence in private["extracted_files"].items():
            bundled = list(executable.parent.rglob(name))
            require(len(bundled) == 1 and digest(bundled[0]) == evidence["sha256"],
                    "bundled_sqlite_must_match_verified_public_production_bytes")
        report["bundled_sqlite_matches_verified_public_production_bytes"] = True
        artifact_report = research / "release-directory-verification.json"
        fixture = task / ("verify-directory-" + uuid4().hex[:12])
        checked("verification", [str(source / "scripts/verify_windows_artifact.py"), "--exe", str(executable),
                                 "--source-root", str(source), "--data-root", str(fixture),
                                 "--report", str(artifact_report)])
        verified = json.loads(artifact_report.read_text(encoding="utf-8"))
        require(verified.get("verified") is True and verified["executable_sha256"] == report["executable_sha256"]
                and verified["version"] == "0.5.0", "standard_native_directory_gate_failed")
        require(helpers["source_fingerprints"](source, release) == fingerprints, "source_changed_during_build_or_verification")
        verified.update(source_sha=M, source_fingerprints=fingerprints, runtime_sha256=RUNTIME_SHA,
                        actual_build_runtime=runtime_probe)
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
