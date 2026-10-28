"""Reproducible local-ledger benchmarks; never reads or writes a real CCS source.

The row seeder models accumulated local facts, not one huge CCS import. Claims in
this isolated fixture are synthetic; a separate small Store workflow verifies the
actual sync/query/billing path before any timing is reported.
"""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import json
import math
import os
import platform
import random
import shutil
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from functools import cache
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aha import __version__, decimal_sql, ledger, migrations, queries  # noqa: E402
from aha.claims import member_from_row  # noqa: E402
from aha.domain import (
    BEIJING,
    build_source_data,
    content_hash,
    normalize_row,
    row_fingerprint,
)  # noqa: E402
from aha.storage import Store  # noqa: E402

FORMAT = 1
HISTORY_SOURCE = "benchmark-history"
LIVE_SOURCE = "benchmark-live"
BASE = datetime(2021, 10, 28, tzinfo=BEIJING)
HISTORY_END = datetime(2026, 10, 1, tzinfo=BEIJING)
END = datetime(2026, 10, 28, tzinfo=BEIJING)
SOURCE_NAMES = {HISTORY_SOURCE: "合成历史用量", LIVE_SOURCE: "合成固定来源窗口"}
MARKER = ".aha-ledger-benchmark.json"
BATCH_ID = "synthetic-ownership-fixture"


def current_rss() -> int:
    if sys.platform == "win32":

        class Memory(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = Memory()
        counters.cb = ctypes.sizeof(counters)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel.GetCurrentProcess.restype = ctypes.c_void_p
        psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
        if psapi.GetProcessMemoryInfo(
            kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb
        ):
            return int(counters.WorkingSetSize)
        raise OSError("Unable to sample process RSS")
    values = Path("/proc/self/statm").read_text().split()
    return int(values[1]) * os.sysconf("SC_PAGE_SIZE")


class PeakMemory:
    def __init__(self) -> None:
        self.baseline = current_rss()
        self.peak = self.baseline
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._sample, daemon=True)

    def _sample(self) -> None:
        while not self.stop.wait(0.01):
            self.peak = max(self.peak, current_rss())

    def __enter__(self) -> PeakMemory:
        self.thread.start()
        return self

    def __exit__(self, *arguments: Any) -> None:
        self.peak = max(self.peak, current_rss())
        self.stop.set()
        self.thread.join()

    def result(self) -> dict[str, int]:
        return {
            "baseline_rss_bytes": self.baseline,
            "peak_rss_bytes": self.peak,
            "extra_peak_rss_bytes": max(0, self.peak - self.baseline),
        }


def _record_coordinates(index: int, count: int, seed: int, live: bool) -> tuple[int, int, int]:
    project = (
        0
        if index % 2 == 0
        else -1
        if index % 97 == 1
        else 1 + ((index * 1103515245 + seed) & 0x7FFFFFFF) % 99
    )
    model = index % 20 if project <= 0 else project % 20
    start, end = (HISTORY_END, END) if live else (BASE, HISTORY_END)
    timestamp = int(start.timestamp()) + (
        (int((end - start).total_seconds()) - 1) * index // max(count - 1, 1)
    )
    return project, model, timestamp


def make_record(
    index: int, count: int, seed: int, *, live: bool = False
) -> tuple[dict[str, Any], int]:
    project, model, timestamp = _record_coordinates(index, count, seed, live)
    row = {
        "request_id": f"bench-{seed}-{'live' if live else 'history'}-{index}",
        "provider_id": "_codex_session",
        "app_type": "codex",
        "model": f"bench-model-{model:02d}",
        "request_model": "",
        "pricing_model": f"bench-model-{model:02d}",
        "input_tokens": 120 + index % 100,
        "output_tokens": 10 + index % 20,
        "cache_read_tokens": 100,
        "cache_creation_tokens": 5,
        "input_token_semantics": 1,
        "input_cost_usd": "0.0008",
        "output_cost_usd": "0.0003",
        "cache_read_cost_usd": "0.0001",
        "cache_creation_cost_usd": "0.000034567",
        "total_cost_usd": "0.001234567",
        "cost_multiplier": "1",
        "session_id": f"bench-session-{project}",
        "created_at": timestamp,
        "data_source": "codex_session",
    }
    return normalize_row(row, "detail"), project


@cache
def _seed_template(seed: int) -> dict[str, Any]:
    return make_record(0, 1, seed)[0]


def _fast_record(
    index: int, count: int, seed: int, *, live: bool = False
) -> tuple[dict[str, Any], int]:
    """Only seed fixtures: reuse validated constants; all varying values stay exact."""
    project, model, timestamp = _record_coordinates(index, count, seed, live)
    return {
        **_seed_template(seed),
        "request_id": f"bench-{seed}-{'live' if live else 'history'}-{index}",
        "model": f"bench-model-{model:02d}",
        "pricing_model": f"bench-model-{model:02d}",
        "input_tokens": 120 + index % 100,
        "output_tokens": 10 + index % 20,
        "session_id": f"bench-session-{project}",
        "created_at": timestamp,
    }, project


def price_rows() -> list[dict[str, str]]:
    return [
        {
            "model_id": f"bench-model-{i:02d}",
            "display_name": f"合成模型 {i}",
            "input_cost_per_million": "2",
            "output_cost_per_million": "3",
            "cache_read_cost_per_million": "0.1",
            "cache_creation_cost_per_million": "0",
        }
        for i in range(20)
    ]


def metadata() -> dict[str, Any]:
    return {
        "sessions": {
            f"bench-session-{i}": {
                "cwd": f"/benchmark/P{i:03d}" if i >= 0 else None,
                "status": "matched" if i >= 0 else "missing",
                "parent_id": None,
            }
            for i in range(-1, 100)
        },
        "errors": [],
    }


def _source(source_id: str) -> dict[str, Any]:
    return {
        "kind": "history",
        "name": SOURCE_NAMES[source_id],
        "fingerprint_kind": "synthetic_seed",
        "fingerprint": content_hash(["synthetic", source_id]),
    }


def _record_at(
    index: int, rows: int, source_window: int, seed: int, *, fast: bool = False
) -> tuple[dict[str, Any], int, int, str]:
    history_count = rows - source_window
    live = index >= history_count
    local_index = index - history_count if live else index
    count = source_window if live else history_count
    maker = _fast_record if fast else make_record
    row, project = maker(local_index, count, seed, live=live)
    return row, project, local_index, LIVE_SOURCE if live else HISTORY_SOURCE


def seed_database(
    store: Store, rows: int, source_window: int, seed: int, *, fast: bool = False
) -> dict[str, Any]:
    """Only the isolated seeder may defer secondary indexes and enlarge its cache."""
    connection = store._db
    original = {
        key: connection.execute("PRAGMA " + key).fetchone()[0]
        for key in ("cache_size", "temp_store", "wal_autocheckpoint", "synchronous")
    }
    indexes = [
        (row["name"], row["sql"])
        for row in connection.execute(
            "SELECT name,sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL "
            "ORDER BY name"
        )
        if not row["sql"].lstrip().upper().startswith("CREATE UNIQUE")
    ]
    started = time.perf_counter()
    try:
        if fast:
            connection.execute("PRAGMA cache_size=-131072")
            connection.execute("PRAGMA temp_store=FILE")
            connection.execute("PRAGMA wal_autocheckpoint=8192")
            with store._transaction():
                for name, _ in indexes:
                    connection.execute('DROP INDEX "' + name.replace('"', '""') + '"')
        result = _seed_database(
            store, rows, source_window, seed, batch_size=25000 if fast else 5000, fast=fast
        )
        if fast:
            indexing_started = time.perf_counter()
            for name, statement in indexes:
                with store._transaction():
                    connection.execute(statement)
                print(json.dumps({"phase": "rebuild_index", "name": name}), flush=True)
            connection.execute("ANALYZE")
            result["index_rebuild_seconds"] = time.perf_counter() - indexing_started
            actual = {
                (row["name"], row["sql"])
                for row in connection.execute(
                    "SELECT name,sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"
                )
            }
            assert set(indexes).issubset(actual), "formal secondary index definitions changed"
            assert connection.execute("PRAGMA foreign_key_check").fetchone() is None
        result["fast_seed"] = fast
        result["deferred_secondary_indexes"] = len(indexes) if fast else 0
        result["seconds_including_index_rebuild"] = time.perf_counter() - started
        return result
    finally:
        for key, value in original.items():
            connection.execute(f"PRAGMA {key}={value}")
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")


def _seed_database(
    store: Store, rows: int, source_window: int, seed: int, *, batch_size: int, fast: bool
) -> dict[str, Any]:
    connection = store._db
    now = store._now()
    started = time.perf_counter()
    revisions = claimed = pending = 0
    summary = {
        key: 0
        for key in (
            "record_count",
            "detail_count",
            "rollup_record_count",
            "rollup_count",
            "unpriced_count",
            "fresh_input_tokens",
            "output_tokens",
            "cache_read_tokens",
            "cache_creation_tokens",
            "total_tokens",
        )
    }
    money = decimal_sql.DecimalSum()
    with store._transaction():
        for source_id in SOURCE_NAMES:
            connection.execute(
                "INSERT INTO source_profiles(id,kind,name,trust,created_at,last_run_id) "
                "VALUES(?,?,?,?,?,?)",
                (
                    source_id,
                    "history",
                    SOURCE_NAMES[source_id],
                    "live" if source_id == LIVE_SOURCE else "history",
                    now,
                    "seed-" + source_id,
                ),
            )
            count = source_window if source_id == LIVE_SOURCE else rows - source_window
            connection.execute(
                "INSERT INTO sync_runs(id,source_id,state,trigger,started_at,completed_at,"
                "heartbeat_at,result_json,data_revision) "
                "VALUES(?,?,'completed','history',?,?,?,?,1)",
                (
                    "seed-" + source_id,
                    source_id,
                    now,
                    now,
                    now,
                    json.dumps({"observed": {"detail": count, "rollup": 0, "pricing": 20}}),
                ),
            )
        for i in range(100):
            connection.execute(
                "INSERT INTO projects VALUES(?,?,?,?)",
                (
                    f"p{i:03d}",
                    f"项目 {i:03d}",
                    "合成基准项目",
                    json.dumps([f"/benchmark/P{i:03d}"]),
                ),
            )
        for session_id, entry in metadata()["sessions"].items():
            connection.execute(
                "INSERT INTO sessions(id,cwd,status,parent_id,content_hash) VALUES(?,?,?,?,?)",
                (session_id, entry["cwd"], entry["status"], None, content_hash(entry)),
            )
        connection.executemany(
            "INSERT INTO pricing VALUES(?,?)",
            ((row["model_id"], store._encode(row)) for row in price_rows()),
        )
        fixture_analysis = {
            "start_date": BASE.date().isoformat(),
            "end_date": (END - timedelta(days=1)).date().isoformat(),
            "project_id": "all",
            "project_name": "合成占用样例",
            "summary": {"total_cost_usd": "0"},
        }
        connection.execute(
            "INSERT INTO batches VALUES(?,1,?,1,'active',1,NULL,NULL)", (BATCH_ID, now)
        )
        connection.execute(
            "INSERT INTO revisions VALUES(?,1,?,'draft',?,?,?,?,?,?,?,?,?)",
            (
                BATCH_ID,
                now,
                now,
                store._encode(fixture_analysis),
                store._encode(
                    {
                        "purpose": "synthetic benchmark",
                        "amount": None,
                        "amount_note": "",
                        "currency": "CNY",
                    }
                ),
                "synthetic",
                "synthetic",
                "packages/synthetic-ownership-fixture.json",
                "synthetic",
                "synthetic-ownership-fixture.json",
                "synthetic",
            ),
        )
        connection.execute("UPDATE billing_sequence SET next_number=2 WHERE id=1")
    record_columns: tuple[str, ...] | None = None
    versions_batch: list[tuple[Any, ...]] = []
    records_batch: list[tuple[Any, ...]] = []
    evidence_batch: list[tuple[Any, ...]] = []
    coverage_batch: dict[str, tuple[Any, ...]] = {}
    claims_batch: list[tuple[Any, ...]] = []
    members_batch: list[tuple[Any, ...]] = []
    cases_batch: list[tuple[Any, ...]] = []

    def flush() -> None:
        if not versions_batch:
            return
        with store._transaction():
            connection.executemany("INSERT INTO usage_versions VALUES(?,?,?,?,?,?)", versions_batch)
            assert record_columns is not None
            connection.executemany(
                "INSERT INTO usage_records("
                + ",".join(record_columns)
                + ") VALUES("
                + ",".join("?" for _ in record_columns)
                + ")",
                records_batch,
            )
            connection.executemany("INSERT INTO record_evidence VALUES(?,?,?)", evidence_batch)
            connection.executemany(
                "INSERT INTO coverage_groups(id,scope_key,day,model,basis) VALUES(?,?,?,?,?) "
                "ON CONFLICT(id) DO NOTHING",
                coverage_batch.values(),
            )
            connection.executemany("INSERT INTO usage_claims VALUES(?,?,?,?,?,?,?)", claims_batch)
            connection.executemany(
                "INSERT INTO revision_members VALUES(?,?,?,?,?,?,?,?,?)", members_batch
            )
            connection.executemany(
                "INSERT INTO reconciliation_cases(id,type,record_key,source_id,message,info_json) "
                "VALUES(?,'revision',?,?,?,?)",
                cases_batch,
            )
        versions_batch.clear()
        records_batch.clear()
        evidence_batch.clear()
        coverage_batch.clear()
        claims_batch.clear()
        members_batch.clear()
        cases_batch.clear()

    for index in range(rows):
        row, project, local_index, source_id = _record_at(
            index, rows, source_window, seed, fast=fast
        )
        projection = ledger.record_projection(row, "detail")
        key, fingerprint = projection["record_key"], projection["content_hash"]
        current_version = index + 1
        old_hash = None
        if local_index % 100 == 0:
            revisions += 1
            old = {**row, "total_cost_usd": "0.001234560"}
            old_hash = row_fingerprint(old)
            versions_batch.append(
                (current_version, key, old_hash, store._encode(old), now, source_id)
            )
            current_version = rows + revisions
        versions_batch.append(
            (current_version, key, fingerprint, store._encode(row), now, source_id)
        )
        evidence_batch.append((current_version, source_id, "seed-" + source_id))
        is_claimed = local_index % 10 < 3
        is_pending = local_index % 10000 == 0
        project_id = f"p{project:03d}" if project >= 0 else ""
        project_name = f"项目 {project:03d}" if project >= 0 else "未归属"
        projection.update(
            version_id=current_version,
            project_id=project_id,
            assignment_origin="directory_rule" if project >= 0 else "unassigned",
            cwd=f"/benchmark/P{project:03d}" if project >= 0 else None,
            availability_state="pending"
            if is_pending
            else "claimed"
            if is_claimed
            else "available",
            usage_reason="reconciliation" if is_pending else "identity" if is_claimed else "",
            suppressed=0,
            pricing_status="available",
        )
        record_columns = record_columns or tuple(projection)
        records_batch.append(tuple(projection[key] for key in record_columns))
        coverage_batch[projection["coverage_key"]] = (
            projection["coverage_key"],
            projection["scope_key"],
            projection["day"],
            row["model"],
            "detail",
        )
        if is_pending:
            pending += 1
            cases_batch.append(
                (
                    f"synthetic-case-{index}",
                    key,
                    source_id,
                    "合成旧备份修订待核对。",
                    store._encode({"candidate_version_id": index + 1, "candidate_hash": old_hash}),
                )
            )
        if is_claimed:
            claimed += 1
            member = member_from_row(row, "detail")
            frozen = {
                **row,
                "kind": "detail",
                "record_key": key,
                "version_id": current_version,
                "content_fingerprint": fingerprint,
                "date": projection["day"],
                "time": datetime.fromtimestamp(projection["event_time"], BEIJING).isoformat(),
                "project_id": project_id or None,
                "project_name": project_name,
                "assignment_origin": projection["assignment_origin"],
                "pricing_status": "available",
                "fresh_input_tokens": int(projection["fresh_input_tokens"]),
                "total_tokens": int(projection["total_tokens"]),
            }
            member_json = store._encode(
                {
                    **member,
                    "version_id": current_version,
                    "project_id": project_id or None,
                    "project_name": project_name,
                    "assignment_origin": projection["assignment_origin"],
                    "pricing_status": "available",
                }
            )
            claims_batch.append(
                (
                    key,
                    BATCH_ID,
                    1,
                    "detail",
                    projection["scope_key"],
                    projection["semantic_key"],
                    member_json,
                )
            )
            members_batch.append(
                (
                    BATCH_ID,
                    1,
                    key,
                    current_version,
                    "detail",
                    projection["scope_key"],
                    projection["semantic_key"],
                    member_json,
                    store._encode(frozen),
                )
            )
            summary["record_count"] += 1
            summary["detail_count"] += 1
            for field in (
                "fresh_input_tokens",
                "output_tokens",
                "cache_read_tokens",
                "cache_creation_tokens",
                "total_tokens",
            ):
                summary[field] += int(projection[field])
            money.step(row["total_cost_usd"])
        if len(records_batch) >= batch_size:
            flush()
            print(json.dumps({"phase": "seed", "rows": index + 1, "total": rows}), flush=True)
    flush()
    with store._transaction():
        ledger.refresh_daily(connection)
        connection.execute(
            "UPDATE settings SET value='1' "
            "WHERE key IN ('revision','data_revision','claim_revision')"
        )
    connection.execute("PRAGMA optimize")
    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return {
        "seconds": time.perf_counter() - started,
        "detail_rows": rows,
        "content_revisions": revisions,
        "usage_claims": claimed,
        "pending_rows": pending,
        "synthetic_ownership_notice": (
            "Ownership headers/members are controlled fixtures, not generated customer evidence; "
            "actual billing is verified separately."
        ),
        "claimed_summary_crosscheck": {**summary, "total_cost_usd": money.finalize()},
    }


def verify_sample(store: Store, rows: int, source_window: int, seed: int) -> dict[str, Any]:
    chooser = random.Random(seed)
    indices = sorted(
        {
            0,
            min(1, rows - 1),
            min(100, rows - 1),
            max(0, (rows - source_window) // 2),
            rows - source_window,
            rows - 1,
            *(chooser.randrange(rows) for _ in range(100)),
        }
    )
    expected = [_record_at(index, rows, source_window, seed)[0] for index in indices]
    with tempfile.TemporaryDirectory(prefix=".store-sample-", dir=store.data_dir) as directory:
        reference = Store(Path(directory))
        try:
            for i in range(100):
                reference.save_project(None, f"项目 {i:03d}", "", [f"/benchmark/P{i:03d}"])
            reference.sync_data(
                build_source_data(expected, [], price_rows(), _source(HISTORY_SOURCE)),
                metadata(),
                trust="live",
            )
            analysis = reference.analyze(
                BASE.date().isoformat(),
                (END - timedelta(days=1)).date().isoformat(),
                availability_mode="all",
            )
            actual = {row["request_id"]: row for row in reference.iter_analysis_rows(analysis)}
            with store.read_connection() as connection:
                for source_row in expected:
                    derived = ledger.record_projection(source_row, "detail")
                    row = connection.execute(
                        "SELECT r.*,v.payload_json,p.name AS project_name FROM usage_records r "
                        "JOIN usage_versions v ON v.id=r.version_id "
                        "LEFT JOIN projects p ON p.id=r.project_id WHERE r.record_key=?",
                        (derived["record_key"],),
                    ).fetchone()
                    assert row is not None
                    assert json.loads(row["payload_json"]) == source_row
                    assert all(row[key] == value for key, value in derived.items())
                    canonical = actual[source_row["request_id"]]
                    assert row["record_key"] == canonical["record_key"]
                    assert row["content_hash"] == canonical["content_fingerprint"]
                    assert row["total_cost_usd"] == canonical["total_cost_usd"]
                    assert int(row["total_tokens"]) == canonical["total_tokens"]
                    assert (row["project_name"] or "未归属") == canonical["project_name"]
            available = reference.analyze(
                BASE.date().isoformat(), (END - timedelta(days=1)).date().isoformat()
            )
            saved = reference.create_batch(
                available,
                {"purpose": "合成链路对账", "amount": None, "amount_note": "", "currency": "CNY"},
                "sample-billing",
            )
            package, _ = reference.download(saved["id"], 1)
            assert package.is_file()
            assert (
                reference.analyze(
                    BASE.date().isoformat(), (END - timedelta(days=1)).date().isoformat()
                )["summary"]["record_count"]
                == 0
            )
            reference.void_batch(saved["id"], saved["generation"], "合成验证结束", "sample-void")
            assert reference.analyze(
                BASE.date().isoformat(), (END - timedelta(days=1)).date().isoformat()
            )["summary"]["record_count"] == len(expected)
            return {
                "checked_rows": len(expected),
                "key_hash_project_cost_tokens": "passed",
                "actual_store_sync_query_billing_download_void": "passed",
            }
        finally:
            reference.close()


def measure(action: Callable[[], Any], warmup: int, samples: int) -> dict[str, Any]:
    try:
        for _ in range(warmup):
            action()
        timings = []
        with PeakMemory() as memory:
            for _ in range(samples):
                started = time.perf_counter()
                action()
                timings.append((time.perf_counter() - started) * 1000)
        ordered = sorted(timings)
        return {
            "samples": samples,
            "warmup": warmup,
            "p50_ms": statistics.median(ordered),
            "p95_ms": ordered[max(0, math.ceil(samples * 0.95) - 1)],
            "max_ms": max(ordered),
            **memory.result(),
        }
    except Exception as error:
        return {"error": type(error).__name__, "message": str(error)}


@contextlib.contextmanager
def bounded_queries(store: Store, timeout: float) -> Iterator[None]:
    original = store.read_connection

    @contextlib.contextmanager
    def reader() -> Iterator[sqlite3.Connection]:
        with original() as connection:
            deadline = time.monotonic() + timeout
            connection.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
            try:
                yield connection
            finally:
                connection.set_progress_handler(None, 0)

    store.read_connection = reader  # type: ignore[method-assign]
    try:
        yield
    finally:
        store.read_connection = original  # type: ignore[method-assign]


def _plans(store: Store, analysis: dict[str, Any], cursor: str | None) -> list[dict[str, Any]]:
    statements: list[str] = []
    original = store.read_connection

    @contextlib.contextmanager
    def reader() -> Iterator[sqlite3.Connection]:
        with original() as connection:
            connection.set_trace_callback(statements.append)
            yield connection

    store.read_connection = reader  # type: ignore[method-assign]
    try:
        store.analysis_details(analysis, cursor=cursor)
    finally:
        store.read_connection = original  # type: ignore[method-assign]
    with original() as connection:
        return [
            {
                "sql": sql,
                "plan": [dict(row) for row in connection.execute("EXPLAIN QUERY PLAN " + sql)],
            }
            for sql in dict.fromkeys(statements)
            if sql.lstrip().upper().startswith("SELECT")
        ]


def run_queries(store: Store, args: argparse.Namespace) -> dict[str, Any]:
    results: dict[str, Any] = {}
    with bounded_queries(store, args.query_timeout):
        for project in ("all", "p000"):
            for mode in ("available", "all"):
                label = project + "_" + mode
                started = time.perf_counter()
                analysis = store.analyze(
                    BASE.date().isoformat(),
                    (END - timedelta(days=1)).date().isoformat(),
                    project,
                    availability_mode=mode,
                )
                results[label + "_analysis_setup_ms"] = (time.perf_counter() - started) * 1000
                with store.read_connection() as connection:
                    positions = {}
                    for label_position, proportion in (("middle", 0.5), ("deep", 0.95)):
                        timestamp = int(
                            BASE.timestamp() + (END.timestamp() - BASE.timestamp()) * proportion
                        )
                        sql = "SELECT event_time,record_key FROM usage_records WHERE event_time>=?"
                        parameters: list[Any] = [timestamp]
                        if project != "all":
                            sql += " AND project_id=?"
                            parameters.append(project)
                        if mode == "available":
                            sql += " AND availability_state='available' AND suppressed=0"
                        row = connection.execute(
                            sql + " ORDER BY event_time,record_key LIMIT 1", parameters
                        ).fetchone()
                        positions[label_position] = (
                            None
                            if row is None
                            else queries._cursor_encode(
                                analysis, "detail", [row[0], row[1]], "next"
                            )
                        )
                for position, cursor in (("first", None), *positions.items()):
                    name = label + "_" + position
                    results[name] = measure(
                        lambda a=analysis, c=cursor: store.analysis_details(a, cursor=c, size=50),
                        args.warmup,
                        args.samples,
                    )
                    results[name]["target_p95_ms"] = 300 if args.rows <= 1000000 else 500
                    if "p95_ms" in results[name]:
                        results[name]["target_met"] = (
                            results[name]["p95_ms"] <= results[name]["target_p95_ms"]
                        )
                    results[name]["explain"] = _plans(store, analysis, cursor)
                    print(
                        json.dumps(
                            {
                                "phase": "query",
                                "name": name,
                                "p95_ms": results[name].get("p95_ms"),
                                "error": results[name].get("error"),
                            }
                        ),
                        flush=True,
                    )
        for name, start, end, project in (
            ("project_month", "2025-07-01", "2025-07-31", "p000"),
            ("project_year", "2025-01-01", "2025-12-31", "p000"),
            ("all_month", "2025-07-01", "2025-07-31", "all"),
            ("all_year", "2025-01-01", "2025-12-31", "all"),
        ):
            results[name] = measure(
                lambda a=start, b=end, p=project: store.analyze(a, b, p), args.warmup, args.samples
            )
            results[name]["target_p95_ms"] = 1000
            if "p95_ms" in results[name]:
                results[name]["target_met"] = results[name]["p95_ms"] <= 1000
    return results


def _window_data(window: int, seed: int, mutation: dict[str, Any] | None = None) -> dict[str, Any]:
    mutation = mutation or {}
    rows = []
    for index in range(window):
        row, _ = make_record(index, window, seed, live=True)
        if index < mutation.get("revised", 0):
            row["total_cost_usd"] = "0.002345678"
        rows.append(row)
    for index in range(mutation.get("added", 0)):
        row, _ = make_record(index, max(1, mutation["added"]), seed, live=True)
        row["request_id"] = f"bench-{seed}-added-{index}"
        row["created_at"] = int(END.timestamp()) + index
        rows.append(row)
    return build_source_data(rows, [], price_rows(), _source(LIVE_SOURCE))


def _fact_counts(store: Store) -> dict[str, int]:
    with store.read_connection() as connection:
        return {
            "records": connection.execute("SELECT COUNT(*) FROM usage_records").fetchone()[0],
            "versions": connection.execute("SELECT COUNT(*) FROM usage_versions").fetchone()[0],
        }


def _database_bytes(store: Store) -> int:
    return sum(
        path.stat().st_size for path in store.data_dir.glob("aha.sqlite3*") if path.is_file()
    )


def unchanged_sync(store: Store, data: dict[str, Any], samples: int) -> dict[str, Any]:
    before = _fact_counts(store)
    initial_size = _database_bytes(store)
    timings = []
    phase_timings: dict[str, list[float]] = {}
    with PeakMemory() as memory:
        for index in range(samples):
            started = time.perf_counter()
            run = store.sync_data(data, metadata(), source_id=LIVE_SOURCE, trust="live")
            timings.append(time.perf_counter() - started)
            for phase, milliseconds in run.get("timings_ms", {}).items():
                phase_timings.setdefault(phase, []).append(milliseconds)
            assert run["new_count"] == 0 and run["revised_count"] == 0, run
            if index == 0 or (index + 1) % 10 == 0:
                print(
                    json.dumps(
                        {"phase": "unchanged_sync", "sample": index + 1, "seconds": timings[-1]}
                    ),
                    flush=True,
                )
    after = _fact_counts(store)
    assert before == after, (before, after)
    return {
        "samples": samples,
        "measured_scope": "normalized source window through Store.sync_data; input build excluded",
        "source_detail_rows": len(data["details"]),
        "allowed_projection_sha256": content_hash(
            {key: data[key] for key in ("schema_version", "details", "rollups", "pricing")}
        ),
        "p50_seconds": statistics.median(timings),
        "p95_seconds": sorted(timings)[max(0, math.ceil(samples * 0.95) - 1)],
        "phases_ms": {
            phase: {"p50_ms": statistics.median(values),
                    "p95_ms": sorted(values)[max(0, math.ceil(len(values) * 0.95) - 1)]}
            for phase, values in phase_timings.items()
        },
        "before": before,
        "after": after,
        "new_fact_versions": after["versions"] - before["versions"],
        "database_growth_bytes_including_wal": _database_bytes(store) - initial_size,
        **memory.result(),
    }


def incremental_sync(
    store: Store,
    data: dict[str, Any],
    added: int,
    revised: int,
) -> dict[str, Any]:
    from concurrent.futures import ThreadPoolExecutor

    from aha.domain import AppError

    before = _fact_counts(store)
    query_times: list[float] = []
    invalidations = 0
    started = time.perf_counter()
    with PeakMemory() as memory, ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            store.sync_data, data, metadata(), source_id=LIVE_SOURCE, trust="live"
        )
        while not future.done():
            query_start = time.perf_counter()
            try:
                analysis = store.analyze("2026-10-01", "2026-10-29")
                store.analysis_details(analysis)
                query_times.append((time.perf_counter() - query_start) * 1000)
            except AppError as error:
                if error.code not in {"analysis_expired", "availability_changed"}:
                    raise
                invalidations += 1
            time.sleep(0.01)
        run = future.result()
    elapsed = time.perf_counter() - started
    after = _fact_counts(store)
    assert run["new_count"] == added, run
    assert run["revised_count"] == revised, run
    assert after["records"] - before["records"] == added
    assert after["versions"] - before["versions"] == added + revised
    ordered = sorted(query_times)
    return {
        "seconds": elapsed,
        "measured_scope": "normalized source window through Store.sync_data; input build excluded",
        "added": added,
        "revised": revised,
        "run": run,
        "concurrent_query_samples": len(query_times),
        "preview_invalidations": invalidations,
        "query_p95_ms": ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)] if ordered else None,
        "query_max_ms": max(ordered) if ordered else None,
        "before": before,
        "after": after,
        **memory.result(),
    }


def export_selection(store: Store, minimum_rows: int) -> dict[str, Any]:
    count = 0
    last_day = None
    with store.read_connection() as connection:
        for row in connection.execute(
            "SELECT day,SUM(row_count) AS n FROM daily_usage_stats "
            "WHERE state='available' AND kind='detail' GROUP BY day ORDER BY day"
        ):
            count += row["n"]
            last_day = row["day"]
            if count >= minimum_rows:
                break
    if last_day is None or count < minimum_rows:
        return {
            "skipped": "not enough available facts",
            "requested_minimum_rows": minimum_rows,
            "available_rows": count,
        }
    analysis = store.analyze(BASE.date().isoformat(), last_day)
    actual_count = analysis["summary"]["record_count"]
    assert actual_count == count
    print(json.dumps({"phase": "export_start", "members": actual_count}), flush=True)
    started = time.perf_counter()
    with PeakMemory() as memory:
        saved = store.create_batch(
            analysis,
            {"purpose": "合成导出基准", "amount": None, "amount_note": "", "currency": "CNY"},
            "benchmark-export-" + str(time.time_ns()),
        )
        package, _ = store.download(saved["id"], saved["version"])
        byte_count = 0
        digest = __import__("hashlib").sha256()
        with package.open("rb") as stream:
            while block := stream.read(1024 * 1024):
                digest.update(block)
                byte_count += len(block)
        assert digest.hexdigest() == saved["sha256"]
    elapsed = time.perf_counter() - started
    usage = memory.result()
    print(
        json.dumps({"phase": "export_verified", "members": saved["member_count"],
                    "seconds": elapsed, "package_bytes": byte_count, **usage}),
        flush=True,
    )
    # Keep the evidence for size inspection, but return ownership to the baseline.
    release_started = time.perf_counter()
    store.void_batch(
        saved["id"],
        saved["generation"],
        "合成基准结束",
        "benchmark-export-void-" + str(time.time_ns()),
    )
    print(
        json.dumps({"phase": "export_claims_released", "members": saved["member_count"],
                    "seconds": time.perf_counter() - release_started}),
        flush=True,
    )
    return {
        "requested_minimum_rows": minimum_rows,
        "actual_member_count": saved["member_count"],
        "actual_record_count": actual_count,
        "seconds": elapsed,
        "package_bytes": byte_count,
        "sha256_verified": True,
        "selection": {"start_date": analysis["start_date"], "end_date": last_day},
        "target_extra_rss_bytes": 128 * 1024 * 1024,
        "target_met": usage["extra_peak_rss_bytes"] <= 128 * 1024 * 1024,
        **usage,
    }


def machine_info(directory: Path) -> dict[str, Any]:
    cpu = platform.processor()
    if not cpu and Path("/proc/cpuinfo").is_file():
        cpu = next(
            (
                line.split(":", 1)[1].strip()
                for line in Path("/proc/cpuinfo").read_text().splitlines()
                if line.startswith("model name")
            ),
            "unknown",
        )
    filesystem = "not_detected"
    mounts = Path("/proc/self/mountinfo")
    if mounts.is_file():
        candidates: list[tuple[int, str]] = []
        for line in mounts.read_text().splitlines():
            before, _, after = line.partition(" - ")
            mount = Path(before.split()[4].replace("\\040", " "))
            if directory.resolve().is_relative_to(mount):
                candidates.append((len(str(mount)), after.split()[0]))
        if candidates:
            filesystem = max(candidates)[1]
    return {
        "os": platform.platform(),
        "cpu": cpu,
        "logical_cpu_count": os.cpu_count(),
        "python": platform.python_version(),
        "sqlite": sqlite3.sqlite_version,
        "application_version": __version__,
        "disk_type": "not_detected",
        "filesystem_type": filesystem,
        "disk_free_bytes": shutil.disk_usage(directory).free,
        "clock": "time.perf_counter",
        "cold_definition": (
            "new process: Store open + full-range analysis + first50 rows; "
            "interpreter import excluded; OS cache not flushed"
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, required=True)
    parser.add_argument("--seed", type=int, default=20261028)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-window", type=int, default=10000)
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--samples", type=int, default=100)
    parser.add_argument("--query-timeout", type=float, default=30)
    parser.add_argument("--query-only", action="store_true")
    parser.add_argument(
        "--refresh-derived", action="store_true",
        help="Explicitly update this task's isolated pre-release fixture projections",
    )
    parser.add_argument("--fast-seed", action="store_true")
    parser.add_argument("--skip-queries", action="store_true")
    parser.add_argument("--sync-samples", type=int, default=0)
    parser.add_argument("--sync-added", type=int, default=0)
    parser.add_argument("--sync-revised", type=int, default=0)
    parser.add_argument("--export-rows", type=int, action="append", default=[])
    parser.add_argument("--cold-probe", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.refresh_derived and not args.query_only:
        parser.error("--refresh-derived requires an existing isolated --query-only fixture")
    if args.rows < 10 or args.samples < 1 or args.warmup < 0 or args.query_timeout <= 0:
        parser.error("rows>=10, samples>=1, warmup>=0 and positive timeout are required")
    source_window = min(args.source_window, max(1, args.rows // 10))
    if (
        source_window <= 0
        or args.sync_samples < 0
        or args.sync_added < 0
        or not 0 <= args.sync_revised <= source_window
        or any(count <= 0 for count in args.export_rows)
    ):
        parser.error("source window/export rows must be positive; sync counts must be valid")
    marker = args.data_dir / MARKER
    existing: dict[str, Any] = {}
    if args.cold_probe:
        if not marker.is_file() or not json.loads(marker.read_text()).get("completed"):
            parser.error("cold probes require a completed isolated benchmark marker")
        started = time.perf_counter()
        store = Store(args.data_dir)
        try:
            analysis = store.analyze(
                BASE.date().isoformat(), (END - timedelta(days=1)).date().isoformat()
            )
            page = store.analysis_details(analysis)
            print(
                json.dumps(
                    {
                        "milliseconds": (time.perf_counter() - started) * 1000,
                        "rows": len(page["rows"]),
                    }
                )
            )
        finally:
            store.close()
        return
    if marker.exists():
        existing = json.loads(marker.read_text())
        if (
            existing.get("format") != FORMAT
            or existing.get("rows") != args.rows
            or existing.get("seed") != args.seed
            or existing.get("source_window") != source_window
        ):
            parser.error("existing benchmark marker does not match; use a new isolated directory")
        if not args.query_only or not existing.get("completed"):
            parser.error("existing samples require --query-only and a completed marker")
    elif args.query_only or (args.data_dir.exists() and any(args.data_dir.iterdir())):
        parser.error("refusing an unmarked/nonempty data directory")
    args.data_dir.mkdir(parents=True, exist_ok=True)
    state = (
        dict(existing)
        if args.query_only
        else {
            "format": FORMAT,
            "rows": args.rows,
            "seed": args.seed,
            "source_window": source_window,
            "completed": False,
        }
    )
    if not args.query_only:
        marker.write_text(json.dumps(state), encoding="utf-8")
    store = Store(args.data_dir)
    result: dict[str, Any] = {
        **state,
        "machine": machine_info(args.data_dir),
        "distribution": {
            "years": 5,
            "projects": 100,
            "models": 20,
            "project_zero_fraction": 0.5,
            "revisions_fraction": 0.01,
            "claims_fraction": 0.3,
            "pending_fraction": 0.0001,
            "model_assignment": "project0 varies by index; other projects map to model modulo20",
        },
    }
    try:
        if args.refresh_derived:
            refresh_started = time.perf_counter()
            with store._transaction():
                migrations.initialize_monthly(store._db)
                migrations.initialize_source_observations(store._db)
                migrations.initialize_query_indexes(store._db)
                ledger.refresh_monthly(store._db)
            result["derived_projection_refresh_seconds"] = time.perf_counter() - refresh_started
        if not args.query_only:
            with PeakMemory() as memory:
                result["seed_run"] = seed_database(
                    store, args.rows, source_window, args.seed, fast=args.fast_seed
                )
            result["seed_memory"] = memory.result()
            state["completed"] = True
            result["completed"] = True
            marker.write_text(json.dumps(state), encoding="utf-8")
        if not state.get("incremental"):
            result["sample_verification"] = verify_sample(
                store, args.rows, source_window, args.seed
            )
        else:
            result["sample_verification"] = {
                "skipped": (
                    "dataset includes a recorded incremental mutation; "
                    "see original baseline verification"
                )
            }
        result["queries"] = {} if args.skip_queries else run_queries(store, args)
        cold = (
            None
            if args.skip_queries
            else subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--rows",
                    str(args.rows),
                    "--seed",
                    str(args.seed),
                    "--data-dir",
                    str(args.data_dir),
                    "--output",
                    str(args.output),
                    "--cold-probe",
                ],
                capture_output=True,
                text=True,
                timeout=max(120, args.query_timeout * 2),
            )
        )
        result["process_cold"] = (
            {"skipped": True}
            if cold is None
            else json.loads(cold.stdout)
            if cold.returncode == 0
            else {"error": cold.stderr[-4000:]}
        )
        if "milliseconds" in result["process_cold"]:
            result["process_cold"]["target_ms"] = 1500
            result["process_cold"]["target_met"] = result["process_cold"]["milliseconds"] <= 1500
        if args.sync_samples:
            result["unchanged_sync"] = unchanged_sync(
                store,
                _window_data(source_window, args.seed, state.get("incremental")),
                args.sync_samples,
            )
        if args.sync_added or args.sync_revised:
            if state.get("incremental"):
                result["incremental"] = {
                    "skipped": "incremental mutation already recorded",
                    "previous": state["incremental"],
                }
            else:
                mutation = {"added": args.sync_added, "revised": args.sync_revised}
                result["incremental"] = incremental_sync(
                    store, _window_data(source_window, args.seed, mutation), **mutation
                )
                state["incremental"] = mutation
                marker.write_text(json.dumps(state), encoding="utf-8")
        result["exports"] = []
        for count in args.export_rows:
            result["exports"].append(export_selection(store, count))
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        result["storage"] = {
            path.name: path.stat().st_size for path in args.data_dir.iterdir() if path.is_file()
        }
    except Exception as error:
        result["fatal_error"] = {"type": type(error).__name__, "message": str(error)}
        raise
    finally:
        store.close()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
