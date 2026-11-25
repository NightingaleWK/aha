"""Project native Codex rollouts into durable usage and resumable read positions."""

from __future__ import annotations

import hashlib
import json
import re
import threading
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from time import monotonic
from typing import Any, Literal

import zstandard

from .codex_source_io import (
    READ_BYTES,
    FileStamp,
    SourceFile,
    source_files,
)
from .codex_source_io import (
    CodexSource as CodexSource,
)
from .codex_source_io import (
    default_local_root as default_local_root,
)
from .codex_source_io import (
    list_distributions as list_distributions,
)
from .domain import AppError, Row, content_hash, decimal_text
from .projects import canonical_path
from .session_meta import MAX_WINDOW_BYTES, _header_identity, _HeaderError

CURSOR_VERSION = 2
SCAN_SECONDS = 45.0
MAX_SOURCE_BYTES = 256 * 1024 * 1024
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_EXPANDED_BYTES = 256 * 1024 * 1024
MAX_LINE_BYTES = 1024 * 1024
MAX_COMPACTED_LINE_BYTES = 4 * 1024 * 1024
MAX_FILE_EVENTS = 15_000
MAX_SOURCE_EVENTS = 100_000
ANCHOR_BYTES = 2048
_ROLLOUT_PREFIX_BYTES = 512
_UTC_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MAX_TIMESTAMP = 253402271999 - 8 * 3600
_IDENTIFIER = re.compile(r"[a-zA-Z0-9_.:/-]{1,256}\Z")
_ROLLOUT_THREAD = re.compile(
    r"rollout-.*-([0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})\.jsonl(?:\.zst)?\Z"
)
_ROLLOUT_PREFIX = re.compile(
    rb'^\s*\{\s*"timestamp"\s*:\s*"[^"\\\r\n]{1,64}"\s*,\s*'
    rb'(?:"ordinal"\s*:\s*[0-9]{1,20}\s*,\s*)?'
    rb'"type"\s*:\s*"([a-z_]+)"\s*,\s*"payload"\s*:\s*\{\s*'
    rb'(?:"type"\s*:\s*"([a-z_]+)")?'
)
_UNRELATED_EVENTS = frozenset({
    b"agent_message", b"agent_reasoning", b"item_completed", b"item_started", b"user_message",
})
_COUNTERS = (
    "input_tokens", "cached_input_tokens", "cache_write_input_tokens", "output_tokens",
    "reasoning_output_tokens", "total_tokens",
)

# Prices are USD per million tokens for the published Standard API schedule.
# Only exact published model IDs are priced. A cache-write TTL is required to
# choose a cache-write rate and is absent from verified rollout usage records.
PRICE_SOURCE = "https://developers.openai.com/api/docs/pricing"
PRICE_BASIS = "OpenAI API Standard · 2026-11-24 · " + PRICE_SOURCE
_PRICES = {
    "gpt-6.2-astra": ("8", "0.40", "40"),
    "gpt-6.2-sol": ("2", "0.10", "10"),
    "gpt-6-astra": ("10", "1", "50"),
    "gpt-6.1-sol": ("2", "0.10", "10"),
    "gpt-6.1-terra": ("1", "0.05", "5"),
    "gpt-6-luna": ("0.10", "0.01", "0.50"),
    "gpt-5.3-codex": ("1.75", "0.175", "14"),
}
_LONG_PROMPT_THRESHOLD = 272_000
_UNKNOWN_MODEL = "未知模型"

Tokens = tuple[int, int, int, int, int, int]
type _DiscardedLine = Literal["unknown", "unrelated"]
type _OversizedLine = _DiscardedLine | Literal["compacted"]


@dataclass(frozen=True)
class NativeUsage:
    event_id: str
    row: Row
    session: dict[str, Any]
    pricing_basis: str | None
    price: dict[str, Any] | None
    evidence: dict[str, Any] = field(default_factory=dict)
    relative_path: str = ""


class _ScanLimit(Exception):
    pass


class _BadArchive(Exception):
    pass


class _CompareFailed(Exception):
    pass


def _cancelled(cancel: threading.Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise AppError("sync_cancelled", "同步已取消。", 409)


def probe_source(source: CodexSource) -> CodexSource:
    deadline = monotonic() + 8

    def check() -> None:
        if monotonic() >= deadline:
            raise AppError("wsl_unavailable", "等待 WSL Codex 目录超时，请检查发行版。", 409)

    with source_files(source, check) as files:
        return CodexSource(source.kind, files.root, source.distribution)


def _identifier(value: object) -> str | None:
    return value if isinstance(value, str) and _IDENTIFIER.fullmatch(value) else None


def _timestamp(value: object) -> tuple[int, str] | None:
    if not isinstance(value, str) or len(value) > 64:
        return None
    try:
        event = datetime.fromisoformat(value)
        if event.tzinfo is None:
            return None
        utc = event.astimezone(UTC)
        delta = utc - _UTC_EPOCH
        second = delta.days * 86400 + delta.seconds
    except (ValueError, OverflowError):
        return None
    if 0 <= second <= _MAX_TIMESTAMP:
        return second, utc.isoformat(timespec="microseconds")
    return None


def _tokens(value: object) -> Tokens | None:
    if not isinstance(value, dict):
        return None
    raw = [
        value.get(key, 0) if key not in ("input_tokens", "output_tokens", "total_tokens")
        else value.get(key)
        for key in _COUNTERS
    ]
    return _checked_tokens(raw)


def _context_estimate(value: object) -> bool:
    # Codex also emits local context estimates in last_token_usage. These have
    # only total_tokens set, unlike server token usage.
    return (
        isinstance(value, dict)
        and all(value.get(key, 0) == 0 for key in _COUNTERS[:-1])
        and type(value.get("total_tokens")) is int
        and value["total_tokens"] > 0
    )


def _checked_tokens(value: Any) -> Tokens | None:
    if not isinstance(value, (list, tuple)) or len(value) != len(_COUNTERS):
        return None
    if any(type(number) is not int or not 0 <= number < 2**63 for number in value):
        return None
    prompt, cached, written, output, reasoning, total = value
    if cached + written > prompt or (
        total != prompt + output + reasoning
        and (total != prompt + output or reasoning > output)
    ):
        return None
    return prompt, cached, written, output, reasoning, total


def _source_cwd(value: object) -> str | None:
    if (
        not isinstance(value, str) or len(value) > 8192
        or any(ord(character) < 32 for character in value)
    ):
        return None
    try:
        canonical_path(value)
    except AppError:
        return None
    return value


def _rate_rows(model: str, usage: Tokens) -> tuple[str | None, Row | None, Row]:
    prompt, cached, written, _, _, total = usage
    rates = _PRICES.get(model)
    costs: Row = {
        "input_cost_usd": "0", "output_cost_usd": "0", "cache_read_cost_usd": "0",
        "cache_creation_cost_usd": "0", "total_cost_usd": "0", "cost_multiplier": "1",
    }
    if rates is None or written:
        return None, None, costs
    input_rate, cached_rate, output_rate = map(Decimal, rates)
    long_context = model.startswith("gpt-6") and prompt > _LONG_PROMPT_THRESHOLD
    if long_context:
        input_rate *= 2
        cached_rate *= 2
        output_rate *= Decimal("1.5")
    micro = Decimal("0.000001")
    input_cost = (prompt - cached) * input_rate * micro
    read_cost = cached * cached_rate * micro
    output_cost = (total - prompt) * output_rate * micro
    costs.update(
        input_cost_usd=decimal_text(input_cost.normalize()),
        output_cost_usd=decimal_text(output_cost.normalize()),
        cache_read_cost_usd=decimal_text(read_cost.normalize()),
        total_cost_usd=decimal_text((input_cost + read_cost + output_cost).normalize()),
    )
    price = {
        "model_id": model + ":long-context" if long_context else model, "display_name": model,
        "input_cost_per_million": decimal_text(input_rate),
        "cache_read_cost_per_million": decimal_text(cached_rate),
        "cache_creation_cost_per_million": "0",
        "output_cost_per_million": decimal_text(output_rate),
    }
    basis = PRICE_BASIS
    if long_context:
        basis += f" · 长上下文 · https://developers.openai.com/api/docs/models/{model}"
    return basis, price, costs


def _snapshot_id(thread: str, turn: str | None, total: Tokens, usage: Tokens) -> str:
    return content_hash(["codex-snapshot-pair-v1", thread, turn, total, usage])


@dataclass
class _Parser:
    relative_path: str
    expected_thread: str | None
    thread: str | None = None
    cwd: str | None = None
    parent: str | None = None
    born: str | None = None
    turn: str | None = None
    turn_cwd: str | None = None
    model: str | None = None
    total: Tokens | None = None
    response_pair: str | None = None
    modern_turn: str | None = None
    receipt_usage: Tokens | None = None
    receipt_at: str | None = None
    paired_snapshot: tuple[str, str] | None = None
    forked: bool = False
    observed_usage: bool = False
    reset_allowed: bool = False
    replaying: bool = False
    issues: Counter[str] = field(default_factory=Counter)

    @classmethod
    def create(cls, relative_path: str, raw: Any = None) -> _Parser:
        match = _ROLLOUT_THREAD.fullmatch(relative_path.rsplit("/", 1)[-1])
        value = cls(relative_path, match[1] if match else None)
        if isinstance(raw, dict):
            saved = _timestamp(raw.get("born"))
            value.thread = _identifier(raw.get("thread"))
            value.cwd = _source_cwd(raw.get("cwd"))
            value.parent = _identifier(raw.get("parent"))
            value.born = saved[1] if saved is not None else None
            value.turn = _identifier(raw.get("turn"))
            value.turn_cwd = _source_cwd(raw.get("turn_cwd"))
            value.model = _identifier(raw.get("model"))
            value.response_pair = _identifier(raw.get("response_pair"))
            value.modern_turn = _identifier(raw.get("modern_turn"))
            value.receipt_usage = _checked_tokens(raw.get("receipt_usage"))
            receipt_time = _timestamp(raw.get("receipt_at"))
            value.receipt_at = receipt_time[1] if receipt_time else None
            value.total = _checked_tokens(raw.get("total"))
            value.forked = raw.get("forked") is True
            value.observed_usage = raw.get("observed_usage") is True
            value.reset_allowed = raw.get("reset_allowed") is True
            value.replaying = raw.get("replaying") is True
        return value

    def saved(self) -> dict[str, Any]:
        return {
            "thread": self.thread, "cwd": self.cwd, "parent": self.parent, "born": self.born,
            "turn": self.turn, "turn_cwd": self.turn_cwd, "model": self.model, "total": self.total,
            "response_pair": self.response_pair, "modern_turn": self.modern_turn,
            "receipt_usage": self.receipt_usage, "receipt_at": self.receipt_at,
            "forked": self.forked, "observed_usage": self.observed_usage,
            "reset_allowed": self.reset_allowed, "replaying": self.replaying,
        }

    def _header(self, payload: dict[str, Any], timestamp: object) -> None:
        try:
            thread, parent = _header_identity(payload)
        except _HeaderError:
            self.issues["invalid_header"] += 1
            return
        if not _identifier(thread):
            self.issues["invalid_header"] += 1
            return
        primary = self.expected_thread or self.thread
        if primary and primary.lower() != thread.lower():
            # A paginated rollout may keep a foreign header from inherited history.
            # Its current turn attribution remains the primary thread's.
            self.replaying = self.thread is None
            return
        if self.thread is None:
            self.thread = thread
            event = _timestamp(payload.get("timestamp")) or _timestamp(timestamp)
            self.born = event[1] if event is not None else None
        self.cwd = _source_cwd(payload.get("cwd")) or self.cwd
        self.parent = _identifier(parent) or self.parent
        self.forked = self.forked or bool(self.parent or payload.get("history_base"))
        self.replaying = False

    def _event(
        self,
        event_id: str,
        stamp: tuple[int, str],
        usage: Tokens,
        turn: str | None,
        pair: str | None,
        response: str | None,
        model: str | None,
        pending_reason: str | None = None,
    ) -> NativeUsage:
        assert self.thread is not None
        current_model = self.model if self.turn == turn else None
        selected = model or current_model or _UNKNOWN_MODEL
        basis, price, costs = _rate_rows(selected, usage)
        prompt, cached, written, _, reasoning, total = usage
        row = {
            "app_type": "codex", "provider_id": "_codex_session", "request_id": event_id,
            "model": selected, "request_model": current_model, "session_id": self.thread,
            "input_tokens": prompt, "cache_read_tokens": cached, "cache_creation_tokens": written,
            "output_tokens": total - prompt, "input_token_semantics": 1,
            "created_at": stamp[0], "data_source": "codex_native",
            "pricing_model": price["model_id"] if price else None,
            **costs,
        }
        evidence = {
            "kind": "response" if response else "snapshot", "timestamp": stamp[1],
            "thread_id": self.thread, "turn_id": turn, "snapshot_id": pair,
            "model_basis": "record" if model else "turn_context" if current_model else "unknown",
            "reasoning_output_tokens": reasoning,
        }
        if response:
            evidence["response_id"] = response
        if pending_reason:
            evidence["pending_reason"] = pending_reason
        cwd = (self.turn_cwd if self.turn == turn else None) or self.cwd
        session = {
            "session_id": self.thread, "cwd": cwd, "parent_id": self.parent,
            "status": "matched" if cwd else "missing",
        }
        return NativeUsage(event_id, row, session, basis, price, evidence, self.relative_path)

    def _response(self, source: dict[str, Any], stamp: tuple[int, str]) -> NativeUsage | None:
        if self.thread is None:
            self.issues["metadata_header_missing"] += 1
            return None
        thread = _identifier(source.get("thread_id"))
        if thread and thread != self.thread:
            if not self.forked:
                self.issues["thread_identity_conflict"] += 1
            return None
        response = _identifier(source.get("response_id"))
        usage = _tokens(source.get("usage"))
        if not thread or not response or usage is None:
            self.issues["invalid_response_usage"] += 1
            return None
        turn = _identifier(source.get("turn_id")) or self.turn
        reported = _tokens(source.get("thread_token_usage"))
        pair = _snapshot_id(thread, turn, reported, usage) if reported is not None else None
        self.response_pair = pair
        self.modern_turn = turn
        self.receipt_usage = usage
        self.receipt_at = stamp[1]
        if not usage[-1]:
            return None
        event_id = content_hash(["codex-response-v1", thread, response])
        return self._event(
            event_id, stamp, usage, turn, pair, response, _identifier(source.get("model"))
        )

    def _snapshot(self, info: dict[str, Any], stamp: tuple[int, str]) -> NativeUsage | None:
        if self.thread is None:
            self.issues["metadata_header_missing"] += 1
            return None
        total = _tokens(info.get("total_token_usage"))
        raw_usage = info.get("last_token_usage")
        usage = _tokens(raw_usage)
        previous = self.total
        if (
            total is not None and _context_estimate(raw_usage)
            and (total == previous or not total[-1])
        ):
            return None
        if total is None or usage is None:
            self.issues["invalid_cumulative_usage"] += 1
            self.total = None
            self.observed_usage = True
            return None
        self.total = total
        pair = _snapshot_id(self.thread, self.turn, total, usage)
        first = not self.observed_usage
        self.observed_usage = True
        if not usage[-1]:
            return None
        if pair == self.response_pair:
            if self.receipt_usage is not None:
                self.paired_snapshot = pair, stamp[1]
            self.receipt_usage = None
            return None
        if total == previous:
            return None
        delta = (
            tuple(now - old for now, old in zip(total, previous, strict=True))
            if previous is not None else None
        )
        if (
            self.receipt_usage == usage and self.turn == self.modern_turn
            and self.receipt_at is not None and stamp[1] >= self.receipt_at
            and (delta == usage or previous is None)
        ):
            # After resume, the receipt's thread counter may start a new epoch
            # while token_count retains previous usage. A matching next debit
            # for the same turn still belongs to the receipt just observed.
            self.paired_snapshot = pair, stamp[1]
            self.receipt_usage = None
            return None
        self.receipt_usage = None
        event_id = content_hash(
            ["codex-token-snapshot-v1", self.thread, self.turn, stamp[1], total, usage]
        )
        pending: str | None
        if self.modern_turn is not None and self.turn == self.modern_turn:
            # In a turn with response receipts, a nonmatching snapshot cannot establish
            # an additional charge. Keep its cumulative position for the next sample.
            # A context estimate changes only last. A budget update can include no usage.
            pending = "snapshot_receipt_mismatch"
        else:
            new_thread = first and (
                not self.forked or (self.born is not None and self.turn is not None)
            )
            restart = total == usage and (self.reset_allowed or new_thread)
            pending = "cumulative_baseline_unconfirmed" if delta != usage and not restart else None
        self.reset_allowed = False
        if pending:
            self.issues[pending] += 1
        return self._event(event_id, stamp, usage, self.turn, pair, None, None, pending)

    def _compact(self) -> None:
        if not self.replaying:
            self.reset_allowed = True

    def read_oversized(self, kind: _OversizedLine, raw: bytes) -> None:
        self.paired_snapshot = None
        if kind == "compacted" and raw and _valid_compaction(raw):
            self._compact()
        elif kind != "unrelated":
            self.issues["line_limit"] += 1
            self.total = None
            self.observed_usage = True
            self.reset_allowed = False

    def read_line(self, raw: bytes) -> NativeUsage | None:
        self.paired_snapshot = None
        try:
            value = json.loads(raw)
        except (ValueError, RecursionError):
            self.issues["invalid_line"] += 1
            self.total = None
            self.observed_usage = True
            return None
        if not isinstance(value, dict) or not isinstance(value.get("payload"), dict):
            self.issues["invalid_line"] += 1
            return None
        payload = value["payload"]
        kind = value.get("type")
        if kind == "session_meta":
            self._header(payload, value.get("timestamp"))
            return None
        if self.replaying:
            return None
        if kind == "turn_context":
            self.turn = _identifier(payload.get("turn_id")) or self.turn
            self.turn_cwd = _source_cwd(payload.get("cwd"))
            self.model = _identifier(payload.get("model"))
            return None
        if kind == "compacted" or (
            kind == "event_msg"
            and payload.get("type") in ("context_compacted", "thread_rolled_back")
        ):
            self._compact()
            return None
        if kind == "event_msg" and payload.get("type") in ("task_started", "turn_started"):
            turn = _identifier(payload.get("turn_id"))
            if turn is not None and turn != self.turn:
                self.turn, self.model, self.turn_cwd = turn, None, None
            return None
        snapshot = (
            payload.get("info") if kind == "event_msg" and payload.get("type") == "token_count"
            else None
        )
        if kind != "token_usage_record" and not isinstance(snapshot, dict):
            return None
        stamp = _timestamp(value.get("timestamp"))
        if stamp is None:
            self.issues["invalid_usage_time"] += 1
            return None
        if self.forked and self.born is not None and stamp[1] < self.born:
            return None
        if kind == "token_usage_record":
            return self._response(payload, stamp)
        assert isinstance(snapshot, dict)
        return self._snapshot(snapshot, stamp)


@dataclass
class _Budget:
    cancel: threading.Event | None
    deadline: float
    bytes_read: int = 0
    events: int = 0

    def check(self) -> None:
        _cancelled(self.cancel)
        if monotonic() >= self.deadline:
            raise _ScanLimit

    def read(self, file: SourceFile, offset: int, limit: int) -> bytes:
        self.check()
        data = file.read(offset, limit)
        if len(data) != limit:
            raise _CompareFailed
        self.bytes_read += len(data)
        return data


def _chunks(
    file: SourceFile, start: int, end: int, budget: _Budget
) -> Iterator[bytes]:
    for offset in range(start, end, READ_BYTES):
        yield budget.read(file, offset, min(READ_BYTES, end - offset))


def _expanded(chunks: Iterator[bytes]) -> Iterator[bytes]:
    total = 0
    try:
        inflater = zstandard.ZstdDecompressor(max_window_size=MAX_WINDOW_BYTES).decompressobj()
        for block in chunks:
            # Limit input per call so even a run-length-compressed frame cannot
            # allocate the entire allowed output in one decompressor call.
            for index in range(0, len(block), 512):
                data = block[index:index + 512]
                while data:
                    if inflater.eof:
                        inflater = zstandard.ZstdDecompressor(
                            max_window_size=MAX_WINDOW_BYTES
                        ).decompressobj()
                    plain = inflater.decompress(data)
                    total += len(plain)
                    if total > MAX_EXPANDED_BYTES:
                        raise _BadArchive("archive_expansion_limit")
                    if plain:
                        yield plain
                    data = inflater.unused_data if inflater.eof else b""
        if not inflater.eof:
            raise _BadArchive("invalid_archive")
    except zstandard.ZstdError as exc:
        raise _BadArchive("invalid_archive") from exc


def _skip_prefix(chunks: Iterator[bytes], width: int) -> Iterator[bytes]:
    for chunk in chunks:
        consumed = min(width, len(chunk))
        width -= consumed
        if consumed < len(chunk):
            yield chunk[consumed:]
    if width:
        raise _CompareFailed


@dataclass
class _Lines:
    discarding: _DiscardedLine | None = None
    buffer: bytearray = field(default_factory=bytearray)
    size: int = 0
    oversized: _OversizedLine | None = None

    def _retain(self, block: bytes, start: int, end: int) -> None:
        if self.discarding is not None:
            return
        if self.oversized is None:
            general_end = min(end, start + MAX_LINE_BYTES - len(self.buffer))
            self.buffer.extend(block[start:general_end])
            if self.size <= MAX_LINE_BYTES:
                return
            self.oversized = _oversized_kind(bytes(self.buffer[:_ROLLOUT_PREFIX_BYTES]))
            start = general_end
        if self.oversized == "compacted":
            compaction_end = min(end, start + MAX_COMPACTED_LINE_BYTES - len(self.buffer))
            self.buffer.extend(block[start:compaction_end])

    def unfinished_discard(self) -> _DiscardedLine | None:
        if self.oversized == "compacted":
            # Reread a bounded candidate from the start of its line. The
            # cursor never carries raw content or an unverified reset.
            return "unknown" if self.size > MAX_COMPACTED_LINE_BYTES else None
        return self.discarding or self.oversized

    def read(self, chunks: Iterator[bytes]) -> Iterator[tuple[bytes, int, _OversizedLine | None]]:
        for block in chunks:
            start = 0
            while start < len(block):
                newline = block.find(b"\n", start)
                end = len(block) if newline < 0 else newline + 1
                self.size += end - start
                self._retain(block, start, end)
                if newline >= 0:
                    kind = self.discarding or self.oversized
                    complete = kind is None or (
                        kind == "compacted" and self.size <= MAX_COMPACTED_LINE_BYTES
                    )
                    yield bytes(self.buffer) if complete else b"", self.size, kind
                    self.buffer.clear()
                    self.size = 0
                    self.discarding = None
                    self.oversized = None
                start = end


def _anchor(file: SourceFile, offset: int, budget: _Budget) -> str:
    width = min(ANCHOR_BYTES, offset)
    head = budget.read(file, 0, width) if width else b""
    tail = budget.read(file, offset - width, width) if offset > width else head
    return hashlib.sha256(head + tail).hexdigest()


def _oversized_kind(prefix: bytes) -> _OversizedLine:
    match = _ROLLOUT_PREFIX.match(prefix)
    if match is None:
        return "unknown"
    if match[1] == b"compacted":
        # The envelope only qualifies this line for bounded JSON validation.
        return "compacted"
    if (
        match[1] in {b"response_item", b"world_state"}
        or (match[1] == b"event_msg" and match[2] in _UNRELATED_EVENTS)
    ):
        return "unrelated"
    return "unknown"


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Invalid JSON constant: {value}")


def _valid_compaction(raw: bytes) -> bool:
    try:
        value = json.loads(raw, parse_constant=_reject_json_constant)
    except (ValueError, RecursionError):
        return False
    return (
        isinstance(value, dict)
        and value.get("type") == "compacted"
        and isinstance(value.get("payload"), dict)
    )


def _compatible_cursor(saved: dict[str, Any]) -> bool:
    version = saved.get("version")
    if version == CURSOR_VERSION:
        # Earlier cursors could already be inside an unvalidated compaction.
        return saved.get("discarding") != "compacted"
    issues = saved.get("durable_issues")
    # Legacy scanners discarded long compactions as unknown. Replay only files
    # that skipped a long line or are still inside an unclassified one.
    return version == 1 and saved.get("discarding") != "unknown" and not (
        isinstance(issues, dict) and issues.get("line_limit")
    )


def _merge_time(first: int | None, latest: int | None, instant: int) -> tuple[int, int]:
    return (
        instant if first is None else min(first, instant),
        instant if latest is None else max(latest, instant),
    )


def _saved_offset(saved: dict[str, Any], file: SourceFile, fact: FileStamp, budget: _Budget) -> int:
    size = saved.get("offset")
    signature = saved.get("signature")
    if (
        type(size) is int and 0 < size <= fact.size
        and isinstance(signature, list) and len(signature) == 5
        and all(type(item) is int for item in signature)
        and signature[:2] == list(fact.identity)
        and (fact.size > signature[2] or fact.signature == signature)
        and saved.get("anchor") == _anchor(file, size, budget)
    ):
        return size
    return 0


def _scan_file(
    file: SourceFile, listed: FileStamp, saved: dict[str, Any], budget: _Budget
) -> tuple[list[NativeUsage], dict[str, Any]]:
    fact = file.stamp()
    if fact.identity != listed.identity:
        raise _CompareFailed
    compressed = fact.path.endswith(".zst")
    if compressed:
        candidate = saved.get("offset")
        offset = candidate if (
            type(candidate) is int and 0 <= candidate <= MAX_EXPANDED_BYTES
            and saved.get("signature") == fact.signature
            and saved.get("anchor") == _anchor(file, fact.size, budget)
        ) else 0
    else:
        offset = _saved_offset(saved, file, fact, budget)
    parser = _Parser.create(fact.path, saved.get("state") if offset else None)
    previous_issues = saved.get("durable_issues", {}) if offset else {}
    first = saved.get("first_at") if offset else None
    latest = saved.get("last_at") if offset else None
    remaining_bytes = max(0, MAX_SOURCE_BYTES - budget.bytes_read)
    if compressed and fact.size > MAX_ARCHIVE_BYTES:
        raise _BadArchive("archive_input_limit")
    if not remaining_bytes or (compressed and fact.size > remaining_bytes):
        raise _ScanLimit
    end = fact.size if compressed else min(fact.size, offset + remaining_bytes)
    discarding = saved.get("discarding") if offset else None
    lines = _Lines(discarding if discarding in ("unknown", "unrelated") else None)
    events: list[NativeUsage] = []
    finished = end == fact.size
    cap_reached = False
    initial_anchor = _anchor(file, min(end, ANCHOR_BYTES), budget)
    if compressed:
        pieces = _skip_prefix(_expanded(_chunks(file, 0, end, budget)), offset)
    else:
        pieces = _chunks(file, offset, end, budget)
    limit = min(MAX_FILE_EVENTS, MAX_SOURCE_EVENTS - budget.events)
    for line, size, oversized in lines.read(pieces):
        budget.check()
        offset += size
        if oversized is not None:
            parser.read_oversized(oversized, line)
            continue
        event = parser.read_line(line)
        if (
            parser.paired_snapshot and events and events[-1].evidence["kind"] == "response"
            and events[-1].evidence["turn_id"] == parser.modern_turn
        ):
            pair, timestamp = parser.paired_snapshot
            events[-1].evidence.update(snapshot_id=pair, snapshot_timestamp=timestamp)
        if event is not None:
            evidence = event.evidence
            if (
                evidence["kind"] == "response" and evidence["snapshot_id"] and events
                and events[-1].evidence["kind"] == "snapshot"
                and evidence["snapshot_id"] == events[-1].evidence["snapshot_id"]
            ):
                prior = events.pop()
                evidence["snapshot_timestamp"] = prior.evidence["timestamp"]
                if reason := prior.evidence.get("pending_reason"):
                    parser.issues[reason] -= 1
            events.append(event)
        if len(events) >= limit:
            cap_reached = True
            if compressed:
                # Finish validating all compression frames before offering a
                # cursor into decoded data. The rest needs no JSON parsing yet.
                for _ in pieces:
                    budget.check()
            finished = False
            break
    next_discarding = None
    if not compressed and not cap_reached:
        next_discarding = lines.unfinished_discard()
        if next_discarding is not None:
            offset += lines.size
    if not isinstance(previous_issues, dict):
        previous_issues = {}
    issues = Counter({
        key: value for key, value in previous_issues.items() if type(value) is int and value > 0
    })
    issues.update(parser.issues)
    for event in events:
        if "pending_reason" not in event.evidence:
            first, latest = _merge_time(first, latest, event.row["created_at"])
    transient: Counter[str] = Counter()
    if lines.size and finished:
        transient["incomplete_tail"] += 1
    if finished and parser.thread is None and (compressed or offset):
        transient["metadata_header_missing"] += 1
    if not finished:
        transient["scan_limit"] += 1
    now = file.stamp()
    if (
        now.identity != fact.identity or now.size < fact.size
        or (now.size == fact.size and now.signature != fact.signature)
        or _anchor(file, min(end, ANCHOR_BYTES), budget) != initial_anchor
    ):
        raise _CompareFailed
    return events, {
        "version": CURSOR_VERSION,
        "signature": fact.signature,
        "offset": offset,
        "discarding": next_discarding,
        "anchor": _anchor(file, fact.size if compressed else offset, budget),
        "state": parser.saved(),
        "finished": finished, "first_at": first, "last_at": latest,
        "durable_issues": dict(issues), "issues": dict(issues + transient),
    }


def scan_source(
    source: CodexSource,
    load_cursor: Callable[[str], dict[str, Any] | None],
    on_event: Callable[[NativeUsage], None],
    on_cursor: Callable[[str, dict[str, Any]], None],
    *,
    cancel: threading.Event | None = None,
) -> dict[str, Any]:
    """Offer validated segments and resume state for a single source transaction."""
    budget = _Budget(cancel, monotonic() + SCAN_SECONDS)
    issues: Counter[str] = Counter()
    first = latest = None
    count = 0
    _cancelled(cancel)
    opening = True
    open_deadline = monotonic() + 8

    def check() -> None:
        if opening and monotonic() >= open_deadline:
            raise AppError("wsl_unavailable", "等待 WSL Codex 目录超时，请检查发行版。", 409)
        budget.check()

    with source_files(source, check) as files:
        opening = False
        try:
            for listed in files.files():
                budget.check()
                if budget.events >= MAX_SOURCE_EVENTS or budget.bytes_read >= MAX_SOURCE_BYTES:
                    raise _ScanLimit
                count += 1
                saved = load_cursor(listed.path) or {}
                if not _compatible_cursor(saved):
                    saved = {}
                events: list[NativeUsage]
                if saved.get("signature") == listed.signature and saved.get("finished") is True:
                    events, cursor = [], saved
                else:
                    try:
                        opened = files.open(listed.path)
                        events, cursor = _scan_file(opened, listed, saved, budget)
                    except (OSError, _CompareFailed):
                        issues["file_changed_or_unavailable"] += 1
                        continue
                    except _BadArchive as exc:
                        events = []
                        cursor = {
                            "version": CURSOR_VERSION, "signature": listed.signature,
                            "finished": True, "issues": {str(exc): 1},
                        }
                    files.close_file()
                    for event in events:
                        _cancelled(cancel)
                        on_event(event)
                    on_cursor(listed.path, cursor)
                budget.events += len(events)
                cursor_issues = cursor.get("issues")
                if isinstance(cursor_issues, dict):
                    issues.update({
                        key: value for key, value in cursor_issues.items()
                        if type(value) is int and value > 0
                    })
                for instant in (cursor.get("first_at"), cursor.get("last_at")):
                    if type(instant) is int:
                        first, latest = _merge_time(first, latest, instant)
        except _ScanLimit:
            issues["scan_limit"] += 1
        issues.update(files.issues)
    _cancelled(cancel)
    return {
        "files": count, "bytes_read": budget.bytes_read, "events": budget.events,
        "coverage": "partial" if issues else "complete", "issues": dict(issues),
        "first_at": first, "last_at": latest,
    }
