"""Verify the public tag, notes, three published assets and delivered bytes."""

import hashlib
import json
import subprocess
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path


def fetch(url, cap=64 * 1024 * 1024):
    request = urllib.request.Request(url, headers={"User-Agent": "aha-release-verification",
                                                "Cache-Control": "no-cache"})
    with urllib.request.urlopen(request, timeout=60) as response:
        content = response.read(cap + 1)
    assert len(content) <= cap
    return content


def main():
    research = Path(__file__).resolve().parent
    root = research.parents[3]
    expected = json.loads((research / "release-cloud-assets.json").read_text())
    delivery_file = research / "release-desktop-delivery.json"
    delivery = json.loads(delivery_file.read_text())
    assert expected["verified"] and delivery["verified"]
    api = "https://api.github.com/repos/NightingaleWK/aha"
    release = json.loads(fetch(api + "/releases/tags/v0.5.0", 1024 * 1024))
    latest = json.loads(fetch(api + "/releases/latest", 1024 * 1024))
    tag = json.loads(fetch(api + "/git/ref/tags/v0.5.0", 1024 * 1024))
    assert release["draft"] is False and release["prerelease"] is False
    assert latest["id"] == release["id"] and release["tag_name"] == "v0.5.0"
    assert release["target_commitish"] == tag["object"]["sha"] == expected["source_sha"]
    assert tag["object"]["type"] == "commit"
    assert set(a["name"] for a in release["assets"]) == set(expected["file_sha256"])
    public_hashes, sizes = {}, {}
    for asset in release["assets"]:
        content = fetch(asset["browser_download_url"])
        value = hashlib.sha256(content).hexdigest()
        assert value == expected["file_sha256"][asset["name"]]
        assert len(content) == asset["size"]
        if asset.get("digest"):
            assert asset["digest"] == "sha256:" + value
        public_hashes[asset["name"]] = value
        sizes[asset["name"]] = len(content)
    notes = (root / "docs/releases/v0.5.0.md").read_bytes()
    assert hashlib.sha256(notes).hexdigest() == expected["build_info_notes_sha256"]
    assert notes.decode().strip() in release["body"]
    assert expected["source_sha"] in release["body"]
    for target in delivery["delivery"]:
        native_path = subprocess.check_output(["wslpath", "-u", target["path"]], text=True).strip()
        assert hashlib.sha256(Path(native_path).read_bytes()).hexdigest() == expected["executable_sha256"]
    tray = json.loads((research / "release-user-tray-v050.json").read_text())
    assert tray["desktop_delivery_report_sha256"] == hashlib.sha256(delivery_file.read_bytes()).hexdigest()
    receipt = root / ".release/acceptance/v0.5.0-project-continuity.json"
    report = {"verified": True, "published": True, "version": "0.5.0",
              "source_sha": expected["source_sha"], "runtime_sha256": expected["runtime_sha256"],
              "executable_sha256": expected["executable_sha256"],
              "public_asset_sha256": public_hashes, "public_asset_sizes": sizes,
              "public_url": release["html_url"], "release_id": release["id"],
              "published_at": release["published_at"], "tag_sha": tag["object"]["sha"],
              "latest_public_release_matches": True,
              "notes_sha256": hashlib.sha256(notes).hexdigest(),
              "desktop_and_existing_program_match_public_asset": True,
              "original_delivery_report_byte_unchanged": True,
              "receipt_sha256": hashlib.sha256(receipt.read_bytes()).hexdigest(),
              "verified_at": datetime.now(timezone(timedelta(hours=8))).isoformat()}
    (research / "release-publication.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"verified": True, "published": True, "public_url": release["html_url"],
                      "source_sha": expected["source_sha"], "executable_sha256": expected["executable_sha256"]}))


if __name__ == "__main__":
    main()
