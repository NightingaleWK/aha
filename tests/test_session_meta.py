from __future__ import annotations

import hashlib
import json
import sqlite3
import struct
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from typing import Any
from unittest.mock import patch

import zstandard

from aha.domain import AppError
from aha.session_meta import scan_metadata

SID = "019f0080-1111-7222-8333-000000000001"
SECOND = "019f0080-1111-7222-8333-000000000002"
THIRD = "019f0080-1111-7222-8333-000000000003"


def header(session_id: str, cwd: str, **extra: Any) -> bytes:
    return (
        json.dumps(
            {
                "type": "session_meta",
                "payload": {
                    "id": session_id,
                    "cwd": cwd,
                    "user_instructions": "PRIVATE_INSTRUCTIONS",
                    **extra,
                },
            },
            ensure_ascii=False,
        )
        + "\n"
    ).encode("utf-8")


class SessionMetadataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name, ".codex")
        self.active = self.root / "sessions" / "2026" / "10" / "01"
        self.archive = self.root / "archived_sessions"
        self.active.mkdir(parents=True)
        self.archive.mkdir()

    def put(
        self,
        session_id: str = SID,
        cwd: str = "/work/repo",
        compressed: bool = False,
        archived: bool = False,
        prefix: str = "rollout",
        **extra: Any,
    ) -> Path:
        directory = self.archive if archived else self.active
        suffix = ".jsonl.zst" if compressed else ".jsonl"
        path = directory / f"{prefix}-{session_id}{suffix}"
        data = header(session_id, cwd, **extra) + b"NOT JSON PRIVATE_CONVERSATION\n"
        path.write_bytes(zstandard.ZstdCompressor().compress(data) if compressed else data)
        return path

    def test_plain_compressed_and_archived_headers_without_conversation(self) -> None:
        first = self.put()
        second = self.put(
            SECOND, "/work/中文目录", compressed=True, archived=True, forked_from_id=SID
        )
        before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (first, second)}
        result = scan_metadata({SID, SECOND}, [self.root])
        self.assertEqual(result["matched_sessions"], 2)
        self.assertEqual(result["total_sessions"], 2)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["sessions"][SECOND]["parent_id"], SID)
        self.assertEqual(result["sessions"][SECOND]["cwd"], "/work/中文目录")
        self.assertNotIn("PRIVATE_INSTRUCTIONS", str(result))
        self.assertNotIn("PRIVATE_CONVERSATION", str(result))
        self.assertEqual(
            before,
            {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (first, second)},
        )

    def test_duplicate_headers_same_metadata_merge_and_equivalent_windows_paths_match(self) -> None:
        self.put(cwd=r"C:\Work\Repo")
        self.put(cwd="c:/work/repo/", compressed=True, archived=True)
        result = scan_metadata({SID}, [self.root])
        self.assertEqual(result["matched_sessions"], 1)
        self.assertEqual(result["sessions"][SID]["status"], "matched")
        self.assertEqual(result["errors"], [])

    def test_conflicting_headers_are_unassigned_even_if_later_copy_agrees(self) -> None:
        self.put(cwd="/work/repo")
        self.put(cwd="/work/Other", archived=True)
        self.put(cwd="/work/repo", compressed=True, archived=True)
        result = scan_metadata({SID}, [self.root])
        self.assertEqual(result["matched_sessions"], 0)
        self.assertEqual(
            result["sessions"][SID], {"status": "conflict", "cwd": None, "parent_id": None}
        )

    def test_linux_case_is_preserved_and_parent_conflicts_are_visible(self) -> None:
        self.put(cwd="/work/Repo")
        self.put(cwd="/work/repo", archived=True)
        self.put(SECOND, parent_thread_id="parent-one")
        self.put(SECOND, archived=True, parent_thread_id="parent-two")
        result = scan_metadata({SID, SECOND}, [self.root])
        self.assertEqual(result["sessions"][SID]["status"], "conflict")
        self.assertEqual(result["sessions"][SECOND]["status"], "conflict")

    def test_missing_sessions_and_roots_remain_explicit(self) -> None:
        self.put()
        result = scan_metadata({SID, SECOND}, [self.root, self.root / "missing"])
        self.assertEqual(result["matched_sessions"], 1)
        self.assertEqual(result["sessions"][SECOND]["status"], "missing")
        self.assertIn({"code": "root_unavailable", "count": 1}, result["errors"])
        self.assertNotIn(str(self.root), str(result))

    def test_never_scan_body_for_a_later_session_header(self) -> None:
        path = self.put()
        path.write_bytes(b'{"type":"event_msg","payload":"private"}\n' + header(SID, "/repo"))
        result = scan_metadata({SID}, [self.root])
        self.assertEqual(result["sessions"][SID]["status"], "missing")
        self.assertEqual(result["errors"], [{"code": "metadata_header_missing", "count": 1}])

    def test_header_size_limit_plain_and_compressed(self) -> None:
        self.put(cwd="/" + "a" * 2000)
        self.put(SECOND, cwd="/" + "a" * 2000, compressed=True, archived=True)
        with patch("aha.session_meta.MAX_HEADER_BYTES", 512):
            result = scan_metadata({SID, SECOND}, [self.root])
        self.assertEqual(result["matched_sessions"], 0)
        self.assertEqual(result["errors"], [{"code": "header_limit", "count": 2}])

    def test_compressed_input_and_window_are_bounded(self) -> None:
        path = self.put(compressed=True)
        skippable = struct.pack("<II", 0x184D2A50, 4096) + b"\x00" * 4096
        path.write_bytes(skippable + path.read_bytes())
        with patch("aha.session_meta.MAX_COMPRESSED_BYTES", 1024):
            result = scan_metadata({SID}, [self.root])
        self.assertEqual(result["errors"], [{"code": "compressed_header_limit", "count": 1}])
        data = header(SECOND, "/work/repo") + b"a" * 200000
        path2 = self.archive / f"rollout-{SECOND}.jsonl.zst"
        path2.write_bytes(zstandard.ZstdCompressor().compress(data))
        with patch("aha.session_meta.MAX_WINDOW_BYTES", 1024):
            result = scan_metadata({SECOND}, [self.root])
        self.assertEqual(result["matched_sessions"], 0)
        self.assertEqual(result["errors"], [{"code": "invalid_compressed_header", "count": 1}])

    def test_invalid_headers_and_wrong_id_do_not_expose_content(self) -> None:
        path = self.put()
        variants = (
            (b"\xff PRIVATE", "invalid_header"),
            (header(SECOND, "/repo"), "header_session_mismatch"),
            (header(SID, "relative/private"), "invalid_directory"),
            (header(SID, "/repo", parent_id=42), "invalid_header"),
        )
        for data, code in variants:
            path.write_bytes(data)
            with self.subTest(code=code):
                result = scan_metadata({SID}, [self.root])
                self.assertEqual(result["matched_sessions"], 0)
                self.assertEqual(result["errors"], [{"code": code, "count": 1}])
                self.assertNotIn("PRIVATE", str(result))
                self.assertNotIn("relative/private", str(result))

    def test_only_requested_candidate_headers_are_opened(self) -> None:
        self.put()
        self.put(SECOND).write_bytes(b"invalid unrelated data")
        result = scan_metadata({SID}, [self.root])
        self.assertEqual(result["matched_sessions"], 1)
        self.assertEqual(result["errors"], [])

    def test_index_only_locates_headers_and_stale_path_falls_back_to_scan(self) -> None:
        actual = self.put(cwd="/actual/header")
        legacy = self.active / "legacy.jsonl"
        legacy.write_bytes(header(SECOND, "/from/header"))
        index = self.root / "state_5.sqlite"
        with closing(sqlite3.connect(index)) as connection, connection:
            connection.execute("CREATE TABLE threads(id TEXT,cwd TEXT,rollout_path TEXT)")
            connection.executemany(
                "INSERT INTO threads VALUES (?,?,?)",
                [
                    (SID, "/wrong/index", str(self.root / "not-found.jsonl")),
                    (SECOND, "/wrong/index", str(legacy)),
                ],
            )
        before = hashlib.sha256(index.read_bytes()).hexdigest()
        result = scan_metadata({SID, SECOND}, [self.root])
        self.assertEqual(result["matched_sessions"], 2)
        self.assertEqual(result["sessions"][SID]["cwd"], "/actual/header")
        self.assertEqual(result["sessions"][SECOND]["cwd"], "/from/header")
        self.assertEqual(before, hashlib.sha256(index.read_bytes()).hexdigest())
        self.assertEqual(result["errors"], [])
        actual.unlink()
        legacy.unlink()
        refreshed = scan_metadata({SID, SECOND}, [self.root])
        self.assertEqual(refreshed["matched_sessions"], 0)

    def test_scan_limit_and_input_limits_are_explicit(self) -> None:
        self.put()
        self.put(SECOND)
        self.put(THIRD)
        with patch("aha.session_meta.MAX_SCAN_FILES", 1):
            result = scan_metadata({SID, SECOND, THIRD}, [self.root])
        self.assertEqual(result["matched_sessions"], 1)
        self.assertIn({"code": "scan_limit", "count": 1}, result["errors"])
        with patch("aha.session_meta.MAX_SESSIONS", 1), self.assertRaises(AppError):
            scan_metadata({SID, SECOND}, [self.root])
        with self.assertRaises(AppError):
            scan_metadata({SID}, [self.root] * 17)

    def test_empty_selection_does_not_open_files(self) -> None:
        with patch.object(Path, "open", side_effect=AssertionError("no input needed")):
            result = scan_metadata(set(), [self.root])
        self.assertEqual(
            result, {"sessions": {}, "matched_sessions": 0, "total_sessions": 0, "errors": []}
        )


if __name__ == "__main__":
    unittest.main()
