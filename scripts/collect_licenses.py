"""Collect the actual Windows runtime/dependency licenses into the application bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from importlib.metadata import distribution
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect aha bundle notices")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    sections: list[str] = [
        "aha - Third-party notices\n"
        "This file retains licenses from the runtime and dependencies used for this build.\n"
        "CC Switch data semantics reference: farion1231/cc-switch, MIT, commit "
        "e55d8a21b3897b595b746e9f2139716b2931641d. No CC Switch source code is bundled.\n"
        "https://github.com/farion1231/cc-switch/tree/"
        "e55d8a21b3897b595b746e9f2139716b2931641d\n"
    ]
    manifest: list[dict[str, str]] = []

    def add(component: str, version: str, label: str, path: Path) -> None:
        raw = path.read_bytes()
        sections.append(f"\n{'=' * 72}\n{component} {version} - {label}\n{'=' * 72}\n")
        sections.append(raw.decode("utf-8", errors="strict"))
        manifest.append(
            {
                "component": component,
                "version": version,
                "license_file": label,
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )

    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if not python_license.is_file():
        raise SystemExit("CPython LICENSE.txt is missing from the selected base runtime")
    add("CPython", sys.version.split()[0], "LICENSE.txt", python_license)
    for name in ("zstandard", "pyinstaller"):
        package = distribution(name)
        licenses = [
            file
            for file in package.files or []
            if file.name.lower().startswith(("license", "copying"))
        ]
        if not licenses:
            raise SystemExit(f"License files are missing from installed {name}")
        for license_file in sorted(licenses, key=str):
            add(
                name,
                package.version,
                str(license_file),
                Path(str(package.locate_file(license_file))),
            )
    import zstandard

    if zstandard.ZSTD_VERSION != (1, 5, 7):
        raise SystemExit("The zstd library changed; refresh its retained license before packaging")
    zstd = Path(__file__).with_name("licenses") / "zstd-1.5.7-LICENSE.txt"
    add("zstd", "1.5.7", "https://github.com/facebook/zstd/blob/v1.5.7/LICENSE", zstd)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "THIRD_PARTY_NOTICES.txt").write_text("\n".join(sections), encoding="utf-8")
    (args.output / "LICENSE-SOURCES.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
