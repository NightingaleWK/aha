"""Build metadata must have one safe version and preserve the Windows runtime gate."""

from __future__ import annotations

import ast
import contextlib
import importlib.util
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aha import __version__

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_windows.py"
SPEC = importlib.util.spec_from_file_location("aha_build_windows", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
build_windows = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build_windows)


class BuildVersionTests(unittest.TestCase):
    def source(self, root: Path, assignment: str = '__version__ = "0.3.1"') -> None:
        (root / "src/aha/web").mkdir(parents=True)
        (root / "src/aha/__init__.py").write_text(assignment + "\n", encoding="utf-8")
        (root / "pyproject.toml").write_text(
            '[project]\nname="aha-usage"\ndynamic=["version"]\n'
            '[tool.setuptools.dynamic]\nversion={attr="aha.__version__"}\n',
            encoding="utf-8",
        )

    def test_repository_metadata_uses_the_existing_runtime_version(self) -> None:
        root = SCRIPT.parent.parent
        self.assertEqual(build_windows.read_source_version(root), __version__)

    def test_source_version_is_literal_and_cannot_execute_package_code(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.source(root, '__version__ = "0.4.12"\nraise RuntimeError("must not execute")')
            self.assertEqual(build_windows.read_source_version(root), "0.4.12")
            for expression in (
                '"0.3.1" + ""', '"01.3.1"', '"0.3.1-rc.1"',
                '"0.3.65536"', '42', '"0.3.1"\n__version__ = "0.3.2"',
            ):
                (root / "src/aha/__init__.py").write_text(
                    "__version__ = " + expression, encoding="utf-8"
                )
                with self.subTest(expression=expression), self.assertRaises(ValueError):
                    build_windows.read_source_version(root)

    def test_second_static_version_or_wrong_dynamic_source_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.source(root)
            original = (root / "pyproject.toml").read_text("utf-8")
            for content in (
                original.replace('dynamic=["version"]', 'version="0.3.1"'),
                original.replace("aha.__version__", "other.__version__"),
            ):
                (root / "pyproject.toml").write_text(content, "utf-8")
                with self.assertRaises(ValueError):
                    build_windows.read_source_version(root)

    def test_resource_has_fixed_numeric_and_string_versions(self) -> None:
        tree = ast.parse(build_windows.version_resource("12.34.56"), mode="eval")
        calls = [item for item in ast.walk(tree) if isinstance(item, ast.Call)]
        fixed = next(item for item in calls if getattr(item.func, "id", None) == "FixedFileInfo")
        fields = {keyword.arg: ast.literal_eval(keyword.value) for keyword in fixed.keywords}
        self.assertEqual(fields["filevers"], (12, 34, 56, 0))
        self.assertEqual(fields["prodvers"], (12, 34, 56, 0))
        strings = {
            ast.literal_eval(item.args[0]): ast.literal_eval(item.args[1])
            for item in calls if getattr(item.func, "id", None) == "StringStruct"
        }
        self.assertEqual(strings["FileVersion"], "12.34.56")
        self.assertEqual(strings["ProductVersion"], "12.34.56")
        self.assertEqual(strings["OriginalFilename"], "aha.exe")
        for version in ('1.0.0\")', "1.2", "1.2.65536", "1.2.3+local"):
            with self.assertRaises(ValueError):
                build_windows.version_resource(version)

    def test_build_passes_generated_resource_to_the_existing_pyinstaller_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, output = Path(temporary) / "source", Path(temporary) / "build"
            self.source(root)
            (root / "scripts").mkdir()
            for name in ("requirements-build.txt", "collect_licenses.py", "launch.py"):
                (root / "scripts" / name).write_text("", encoding="utf-8")
            runtime = {"windows": True, "bits": 64, "isolated": True}

            def run(command: list[str], **options: object) -> subprocess.CompletedProcess[str]:
                if "PyInstaller" in command:
                    self.assertIn("--onedir", command)
                    resource = Path(command[command.index("--version-file") + 1])
                    self.assertEqual(resource.read_text("utf-8"),
                                     build_windows.version_resource("0.3.1"))
                    executable = output / "release/directory/aha/aha.exe"
                    executable.parent.mkdir(parents=True)
                    executable.write_bytes(b"synthetic executable")
                return subprocess.CompletedProcess(command, 0, "", "")

            with patch.object(build_windows, "inspect_runtime", return_value=runtime), \
                    patch.object(build_windows.subprocess, "run", side_effect=run), \
                    contextlib.redirect_stdout(io.StringIO()):
                executable = build_windows.build(Path("python.exe"), output, root, "Directory")
            self.assertTrue(executable.is_file())
            recorded = json.loads((output / "runtime-versions.json").read_text("utf-8"))
            self.assertEqual(recorded["application_version"], "0.3.1")

    def test_runtime_gate_keeps_platform_isolation_and_sqlite_fixes(self) -> None:
        runtime = {"windows": True, "bits": 64, "isolated": True,
                   "python": [3, 15], "sqlite": [3, 53, 4]}
        cases = (
            ({"windows": False}, False), ({"bits": 32}, False),
            ({"isolated": False}, False), ({"python": [3, 11]}, False),
            ({"sqlite": [3, 51, 2]}, False), ({"sqlite": [3, 50, 6]}, False),
            ({"sqlite": [3, 44, 5]}, False), ({"sqlite": [True, 53, 4]}, False),
            ({"sqlite": [3, 51, 3]}, True), ({"sqlite": [3, 50, 7]}, True),
            ({"sqlite": [3, 44, 6]}, True),
        )
        for change, allowed in cases:
            probe = subprocess.CompletedProcess([], 0, json.dumps({**runtime, **change}), "")
            with self.subTest(change=change), \
                    patch.object(build_windows.subprocess, "run", return_value=probe):
                if allowed:
                    self.assertEqual(build_windows.inspect_runtime(Path("python.exe")),
                                     {**runtime, **change})
                else:
                    with self.assertRaises(ValueError):
                        build_windows.inspect_runtime(Path("python.exe"))

    def test_onefile_cli_still_requires_the_directory_verification_flag(self) -> None:
        with patch("sys.argv", ["build_windows.py", "--build-root", "unused", "--stage",
                                "OneFile"]), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                build_windows.main()
            self.assertEqual(error.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
