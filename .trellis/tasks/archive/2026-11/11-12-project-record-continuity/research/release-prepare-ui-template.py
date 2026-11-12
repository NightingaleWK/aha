"""Recreate the established synthetic schema3 UI template in release QA only."""

from __future__ import annotations

import hashlib
import importlib.metadata
import io
import json
import os
import sqlite3
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from uuid import uuid4


BASELINE = "2216e27"


def git_command(source: Path, *arguments: str) -> list[str]:
    if str(source).lower().startswith(("\\\\wsl.localhost\\", "\\\\wsl$\\")):
        distribution = source.drive.rsplit("\\", 1)[-1]
        linux_source = "/" + "/".join(source.parts[1:])
        return ["wsl.exe", "--distribution", distribution, "--exec", "git", "-C", linux_source, *arguments]
    return ["git", "-C", str(source), *arguments]


def main() -> int:
    source = Path(__file__).resolve().parents[4]
    research = Path(__file__).resolve().parent
    task = Path(os.environ["AHA_RELEASE_QA_ROOT"]).resolve()
    owned = json.loads((task / "task-ownership.json").read_text(encoding="utf-8"))
    assert task.name == "aha-release-v050-20261112"
    assert owned["task"] == "project-record-continuity" and owned["purpose"] == "release-v050"
    assert Path(os.environ["AHA_QA_ROOT"]).resolve() == task
    assert Path(os.environ["USERPROFILE"]).resolve().is_relative_to(task)
    assert sys.platform == "win32" and sys.version_info[:3] == (3, 15, 2)
    assert sys.prefix != sys.base_prefix
    # Do not create stores or install anything until the trusted wheel is ready.
    assert importlib.metadata.version("zstandard") == "0.25.0"
    import zstandard
    import zstandard.backend_c
    assert zstandard.__version__ == "0.25.0"
    assert zstandard.ZstdDecompressor().decompress(zstandard.ZstdCompressor().compress(b"release QA")) == b"release QA"

    baseline = task / "baseline-source"
    assert not baseline.exists(), "Use a new task-owned baseline; never overwrite previous files."
    revision = subprocess.check_output(git_command(source, "rev-parse", BASELINE + "^{commit}"), text=True).strip()
    archive = subprocess.check_output(git_command(source, "archive", "--format=tar", revision, "src/aha"))
    assert len(archive) <= 8 * 1024 * 1024
    staging = task / ("baseline-source-staging-" + uuid4().hex[:8])
    staging.mkdir(exist_ok=False)
    marker = {"task": "project-record-continuity", "purpose": "release-v050-synthetic-ui-baseline",
              "source_commit": revision, "synthetic": True}
    (staging / "task-ownership.json").write_text(json.dumps(marker) + "\n", encoding="utf-8")
    count = 0
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as members:
        for member in members.getmembers():
            relative = PurePosixPath(member.name)
            assert not relative.is_absolute() and ".." not in relative.parts
            if relative.parts == ("src",) and member.isdir():
                continue
            assert relative.parts[:2] == ("src", "aha")
            assert member.isdir() or member.isfile()
            target = staging.joinpath(*relative.parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            stream = members.extractfile(member)
            assert stream is not None
            with stream, target.open("xb") as output:
                output.write(stream.read())
            count += 1
    assert count >= 20
    staging.rename(baseline)

    for name in ("prepare-ui-fixture.py", "prepare-ui-template.py"):
        subprocess.run([sys.executable, "-X", "utf8", "-B", str(research / name)],
                       cwd=source, check=True)
    fixture = json.loads((task / "association-fixture-info.json").read_text(encoding="utf-8"))
    assert fixture["synthetic"] and fixture["schema"] == 3
    assert fixture["detail_count"] == 152 and fixture["record_count"] == 159
    archive_path = Path(fixture["archive"])
    assert archive_path.resolve().is_relative_to(task)
    assert hashlib.sha256(archive_path.read_bytes()).hexdigest() == fixture["archive_sha256"]
    report = {"verified": True, "purpose": "release-v050", "synthetic": True,
              "baseline_source_commit": revision, "baseline_file_count": count,
              "baseline_git_archive_sha256": hashlib.sha256(archive).hexdigest(),
              "schema": fixture["schema"], "detail_count": fixture["detail_count"],
              "rollup_count": fixture["rollup_count"], "record_count": fixture["record_count"],
              "initial_assigned": fixture["initial_assigned"],
              "template_archive_sha256": fixture["archive_sha256"],
              "python": list(sys.version_info[:3]), "sqlite": sqlite3.sqlite_version,
              "zstandard": zstandard.__version__, "real_profile_used": False,
              "candidate_artifact_started": False, "completed_at": datetime.now(timezone.utc).isoformat()}
    (research / "release-ui-template-prepared.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
