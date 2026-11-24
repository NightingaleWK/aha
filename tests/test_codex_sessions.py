from __future__ import annotations

import json
import os
import threading
import unittest
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import patch

import zstandard

from aha.codex_sessions import CodexSource, NativeUsage, probe_source, scan_source
from aha.domain import AppError, fresh_input, normalize_row

THREAD = "019aa0bf-0730-7000-8000-000000000001"
FORK = "019aa0bf-0730-7000-8000-000000000002"
STAMP = "2026-11-24T03:10:00.001Z"
FOLLOWUP = "2026-11-24T03:10:10.005Z"
AFTER = "2026-11-24T03:10:20.010Z"


def _line(kind: str, payload: dict[str, Any], stamp: str = STAMP) -> bytes:
    return (
        json.dumps(
            {"timestamp": stamp, "ordinal": 1, "type": kind, "payload": payload},
            ensure_ascii=False,
        )
        .encode("utf-8") + b"\n"
    )


def _header(thread: str = THREAD, **extra: Any) -> bytes:
    return _line("session_meta", {
        "id": thread, "cwd": "C:/fixture/资料", "timestamp": STAMP, **extra,
    })


def _context(turn: str = "turn-1", model: str = "gpt-6.2-sol", stamp: str = STAMP) -> bytes:
    return _line("turn_context", {"turn_id": turn, "model": model}, stamp)


def _tokens(
    count: int = 1, *, cache_write: int = 0, full_output: bool = True
) -> dict[str, int]:
    return {
        "input_tokens": 20 * count, "cached_input_tokens": 5 * count,
        "cache_write_input_tokens": cache_write * count,
        "output_tokens": (10 if full_output else 7) * count,
        "reasoning_output_tokens": 3 * count, "total_tokens": 30 * count,
    }


def _snapshot(
    total: int, stamp: str = STAMP, *, usage: dict[str, int] | None = None
) -> bytes:
    return _line("event_msg", {
        "type": "token_count",
        "info": {"total_token_usage": _tokens(total), "last_token_usage": usage or _tokens()},
        "rate_limits": {"opaque": "secret-should-not-leave-source"},
    }, stamp)


def _response(
    response: str, total: int, stamp: str = STAMP, *,
    thread: str = THREAD, usage: dict[str, int] | None = None, **extra: Any
) -> bytes:
    return _line("token_usage_record", {
        "thread_id": thread, "turn_id": "turn-1", "response_id": response,
        "usage": usage or _tokens(), "thread_token_usage": _tokens(total), **extra,
    }, stamp)


class CodexSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.directory = self.root / "sessions"
        self.directory.mkdir()
        self.cursors: dict[str, dict[str, Any]] = {}

    def scan(self, *, cancel: threading.Event | None = None) -> tuple[
        list[NativeUsage], dict[str, Any]
    ]:
        events: list[NativeUsage] = []
        receipt = scan_source(
            CodexSource("windows", str(self.root)), self.cursors.get, events.append,
            self.cursors.__setitem__, cancel=cancel,
        )
        return events, receipt

    def test_explicit_receipt_and_cumulative_pair_are_one_request(self) -> None:
        path = self.directory / "rollout.jsonl"
        path.write_bytes(
            _header() + _context() + _response("resp_one", 1) + _snapshot(1, FOLLOWUP)
            + _snapshot(1, AFTER) + _snapshot(2, AFTER) + _response("resp_two", 2, AFTER)
            + _line("response_item", {"body": "secret-should-not-leave-source"}, AFTER)
        )
        events, receipt = self.scan()
        self.assertEqual(receipt["coverage"], "complete")
        self.assertEqual([row.evidence["kind"] for row in events], ["response", "response"])
        self.assertNotEqual(events[0].event_id, events[1].event_id)
        row = normalize_row(events[0].row, "detail")
        self.assertEqual(fresh_input(row), 15)
        self.assertEqual(row["output_tokens"], 10)
        self.assertEqual(row["total_cost_usd"], "0.0001305")
        self.assertEqual(
            events[0].evidence["snapshot_timestamp"], "2026-11-24T03:10:10.005000+00:00"
        )
        self.assertEqual(events[0].session["cwd"], "C:/fixture/资料")
        self.assertIn("2026-11-24", events[0].pricing_basis or "")
        projected = json.dumps([self.cursors, [asdict(event) for event in events]])
        self.assertNotIn("secret-should-not-leave-source", projected)

    def test_append_with_unchanged_mtime_and_incomplete_tail(self) -> None:
        path = self.directory / "rollout.jsonl"
        suffix = _snapshot(2, FOLLOWUP)
        path.write_bytes(_header() + _context() + _snapshot(1) + suffix[:-5])
        original = path.stat()
        first, receipt = self.scan()
        self.assertEqual(len(first), 1)
        self.assertEqual(receipt["issues"], {"incomplete_tail": 1})
        _, unchanged = self.scan()
        self.assertEqual(unchanged["bytes_read"], 0)

        with path.open("ab") as stream:
            stream.write(suffix[-5:])
        os.utime(path, ns=(original.st_atime_ns, original.st_mtime_ns))
        second, receipt = self.scan()
        self.assertEqual(receipt["coverage"], "complete")
        self.assertEqual(len(second), 1)
        self.assertNotEqual(first[0].event_id, second[0].event_id)
        self.assertEqual(receipt["first_at"], first[0].row["created_at"])
        self.assertEqual(receipt["last_at"], second[0].row["created_at"])
        _, same = self.scan()
        self.assertEqual(same["bytes_read"], 0)

    def test_cumulative_unconfirmed_reset_and_later_verified_delta(self) -> None:
        (self.directory / "rollout.jsonl").write_bytes(
            _header() + _context() + _snapshot(3) + _snapshot(4, FOLLOWUP) + _snapshot(1, AFTER)
            + _line("compacted", {}, AFTER) + _snapshot(2, AFTER)
        )
        events, receipt = self.scan()
        self.assertEqual(receipt["coverage"], "partial")
        self.assertEqual(receipt["issues"]["cumulative_baseline_unconfirmed"], 2)
        self.assertEqual(
            [entry.evidence.get("pending_reason") for entry in events],
            ["cumulative_baseline_unconfirmed", None, "cumulative_baseline_unconfirmed", None],
        )
        self.assertEqual(receipt["first_at"], events[1].row["created_at"])

    def test_fork_inherited_parent_prefix_does_not_create_new_usage(self) -> None:
        self.directory.joinpath(f"rollout-2026-11-24-{THREAD}.jsonl").write_bytes(
            _header() + _context() + _snapshot(1)
        )
        self.directory.joinpath(f"rollout-2026-11-24-{FORK}.jsonl").write_bytes(
            _header() + _context() + _snapshot(1)
            + _header(FORK, forked_from_id=THREAD, timestamp=FOLLOWUP)
            + _context("fork-turn", stamp=FOLLOWUP)
            + _response("resp_parent", 1, FOLLOWUP)
            + _snapshot(1, AFTER)
        )
        events, receipt = self.scan()
        self.assertEqual(receipt["coverage"], "complete")
        self.assertEqual(
            sorted(event.row["session_id"] for event in events), sorted([THREAD, FORK])
        )
        fork = next(event for event in events if event.row["session_id"] == FORK)
        self.assertEqual(fork.session["parent_id"], THREAD)

    def test_compression_and_rewrite_preserve_logical_identity(self) -> None:
        data = _header() + _context() + _snapshot(1)
        live = self.directory / "live.jsonl"
        live.write_bytes(data)
        initial, _ = self.scan()
        archive = self.root / "archived_sessions"
        archive.mkdir()
        compressed = zstandard.ZstdCompressor()
        archive.joinpath("renamed.jsonl.zst").write_bytes(
            compressed.compress(data[:37]) + compressed.compress(data[37:])
        )
        broken = archive / "truncated.jsonl.zst"
        broken.write_bytes(compressed.compress(data)[:-1])
        replacement = self.directory / "replacement.tmp"
        replacement.write_bytes(data + _snapshot(2, FOLLOWUP))
        os.replace(replacement, live)

        observed, receipt = self.scan()
        identities = [item.event_id for item in observed]
        self.assertEqual(identities.count(initial[0].event_id), 2)
        self.assertEqual(len(set(identities)), 2)
        self.assertEqual(receipt["issues"], {"invalid_archive": 1})
        self.assertFalse(
            any(item.relative_path.endswith("truncated.jsonl.zst") for item in observed)
        )

    def test_large_archive_segments_resume_from_validated_decoded_cursor(self) -> None:
        self.directory.joinpath("session.jsonl.zst").write_bytes(
            zstandard.ZstdCompressor().compress(
                _header() + _context() + _snapshot(1) + _snapshot(2, FOLLOWUP)
                + _snapshot(3, AFTER)
            )
        )
        with patch("aha.codex_sessions.MAX_FILE_EVENTS", 2):
            first, partial = self.scan()
            rest, complete = self.scan()
        self.assertEqual(len(first), 2)
        self.assertEqual(partial["coverage"], "partial")
        self.assertEqual(len(rest), 1)
        self.assertEqual(complete["coverage"], "complete")
        self.assertEqual(len({event.event_id for event in first + rest}), 3)
        _, stable = self.scan()
        self.assertEqual(stable["bytes_read"], 0)

    def test_ordinary_file_advances_past_long_content_across_budgets(self) -> None:
        unrelated = _line("response_item", {"text": "large-raw-content" * 1600}, FOLLOWUP)
        self.directory.joinpath("rollout.jsonl").write_bytes(
            _header() + _context() + _snapshot(1) + unrelated + _snapshot(2, AFTER)
        )
        confirmed = []
        with (
            patch("aha.codex_sessions.MAX_LINE_BYTES", 1024),
            patch("aha.codex_sessions.MAX_SOURCE_BYTES", 8192),
        ):
            for _ in range(10):
                events, receipt = self.scan()
                confirmed.extend(events)
                if receipt["coverage"] == "complete":
                    break
        self.assertEqual(receipt["coverage"], "complete")
        self.assertEqual(len(confirmed), 2)
        self.assertEqual(len({event.event_id for event in confirmed}), 2)

    def test_projected_tokens_distinguish_reasoning_and_unpriced_cache_write(self) -> None:
        (self.directory / "rollout.jsonl").write_bytes(
            _header() + _context(model="unknown-model")
            + _response("resp_old_tokens", 1, usage=_tokens(full_output=False))
            + _response(
                "resp_cache_write", 2, FOLLOWUP, usage=_tokens(cache_write=4), model="gpt-6.2-sol"
            )
        )
        events, _ = self.scan()
        self.assertEqual([event.row["output_tokens"] for event in events], [10, 10])
        self.assertEqual([event.evidence["reasoning_output_tokens"] for event in events], [3, 3])
        self.assertEqual([event.pricing_basis for event in events], [None, None])
        self.assertEqual(fresh_input(events[1].row), 11)
        self.assertEqual(events[1].evidence["model_basis"], "record")

    def test_bounded_parser_reports_long_lines_without_retaining_content(self) -> None:
        payload = _line("response_item", {"text": "secret-" * 900}, FOLLOWUP)
        unknown = _line("unknown_type", {"text": "secret-" * 900}, FOLLOWUP)
        (self.directory / "rollout.jsonl").write_bytes(
            _header() + _context() + _response("resp_first", 1) + payload
            + _response("resp_second", 2) + unknown + _response("resp_after", 3, AFTER)
        )
        with patch("aha.codex_sessions.MAX_LINE_BYTES", 2048):
            events, receipt = self.scan()
        self.assertEqual(len(events), 3)
        self.assertEqual(receipt["issues"], {"line_limit": 1})
        self.assertNotIn("secret-", json.dumps(self.cursors))

    def test_resumed_receipt_with_thread_total_reset_matches_next_snapshot(self) -> None:
        path = self.directory / "rollout.jsonl"
        path.write_bytes(_header() + _context() + _snapshot(1))
        first, _ = self.scan()
        self.assertEqual([event.evidence["kind"] for event in first], ["snapshot"])
        with path.open("ab") as stream:
            stream.write(_response("resp_resumed", 1, FOLLOWUP) + _snapshot(2, AFTER))
        next_events, receipt = self.scan()
        self.assertEqual(receipt["coverage"], "complete")
        self.assertEqual([event.evidence["kind"] for event in next_events], ["response"])

    def test_project_directory_uses_turn_context_or_marks_missing(self) -> None:
        (self.directory / "rollout.jsonl").write_bytes(
            _header(cwd=None) + _context() + _response("resp_no_dir", 1)
            + _line("turn_context", {
                "turn_id": "turn-1", "model": "gpt-6.2-sol", "cwd": "/mnt/d/fixture",
            }, AFTER)
            + _response("resp_current_dir", 2, AFTER)
        )
        events, receipt = self.scan()
        self.assertEqual(receipt["coverage"], "complete")
        self.assertEqual([event.session["status"] for event in events], ["missing", "matched"])
        self.assertEqual(events[-1].session["cwd"], "/mnt/d/fixture")

    def test_long_context_rates_use_independent_model_price_ids(self) -> None:
        long = {
            "input_tokens": 300_000, "cached_input_tokens": 100_000, "output_tokens": 50,
            "reasoning_output_tokens": 0, "total_tokens": 300_050,
        }
        (self.directory / "rollout.jsonl").write_bytes(
            _header() + _context() + _response("resp_short", 1)
            + _response("resp_long", 2, FOLLOWUP, usage=long)
        )
        events, _ = self.scan()
        self.assertEqual(
            [event.row["pricing_model"] for event in events],
            ["gpt-6.2-sol", "gpt-6.2-sol:long-context"],
        )
        self.assertEqual(events[1].row["total_cost_usd"], "0.82075")
        self.assertIn("长上下文", events[1].pricing_basis or "")

    def test_invalid_source_and_cancellation_do_not_offer_cursors(self) -> None:
        with self.assertRaises(AppError) as invalid:
            probe_source(CodexSource("windows", str(self.root / "absent")))
        self.assertEqual(invalid.exception.code, "source_unavailable")
        with self.assertRaises(AppError) as invalid:
            probe_source(CodexSource("wsl", "", "--exec"))
        self.assertEqual(invalid.exception.code, "invalid_source")
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(AppError) as stopped:
            self.scan(cancel=cancel)
        self.assertEqual(stopped.exception.code, "sync_cancelled")
        self.assertEqual(self.cursors, {})

    def test_descendant_symlinks_do_not_expose_files_outside_rollout_roots(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        log = outside / "private.jsonl"
        log.write_bytes(_header() + _context() + _snapshot(1))
        try:
            (self.directory / "escape.jsonl").symlink_to(log)
            (self.directory / "escape-dir").symlink_to(outside, target_is_directory=True)
        except (NotImplementedError, OSError):
            self.skipTest("symlinks unavailable")
        events, receipt = self.scan()
        self.assertEqual(events, [])
        self.assertEqual(receipt["bytes_read"], 0)
        self.assertEqual(receipt["coverage"], "partial")


if __name__ == "__main__":
    unittest.main()
