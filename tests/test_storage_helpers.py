"""Synthetic fixtures shared by persistence tests; no user data is loaded."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from aha.domain import build_source_data


def detail(request_id: str = "r1", **changes: Any) -> dict[str, Any]:
    row = {
        "request_id": request_id,
        "provider_id": "_codex_session",
        "app_type": "codex",
        "model": "model-a",
        "request_model": "",
        "pricing_model": "model-a",
        "input_tokens": 120,
        "output_tokens": 10,
        "cache_read_tokens": 100,
        "cache_creation_tokens": 5,
        "input_token_semantics": 1,
        "input_cost_usd": "0.01",
        "output_cost_usd": "0.02",
        "cache_read_cost_usd": "0.003",
        "cache_creation_cost_usd": "0.004",
        "total_cost_usd": "0.1234567",
        "cost_multiplier": "1",
        "session_id": "s1",
        "created_at": int(datetime.fromisoformat("2026-10-26T01:00:00+08:00").timestamp()),
        "data_source": "codex_session",
    }
    row.update(changes)
    return row


def rollup(**changes: Any) -> dict[str, Any]:
    row = {
        "date": "2026-10-24",
        "provider_id": "_codex_session",
        "app_type": "codex",
        "model": "model-a",
        "request_model": "",
        "pricing_model": "model-a",
        "request_count": 7,
        "input_tokens": 1000,
        "output_tokens": 20,
        "cache_read_tokens": 500,
        "cache_creation_tokens": 10,
        "input_token_semantics": 2,
        "total_cost_usd": "1.00000001",
    }
    row.update(changes)
    return row


def source_data(
    details: list[dict[str, Any]] | None = None, rollups: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    return build_source_data(
        [detail()] if details is None else details,
        [] if rollups is None else rollups,
        [
            {
                "model_id": "model-a",
                "display_name": "模型 A",
                "input_cost_per_million": "1000",
                "output_cost_per_million": "2000",
                "cache_read_cost_per_million": "50",
                "cache_creation_cost_per_million": "100",
            }
        ],
        {
            "kind": "sql",
            "name": "C:\\private\\usage.sql",
            "fingerprint_kind": "sha256",
            "fingerprint": "a" * 64,
            "observed_at": "2026-10-27T01:00:00+00:00",
        },
    )


def metadata(cwd: str = "/work/a") -> dict[str, Any]:
    return {
        "sessions": {"s1": {"cwd": cwd, "status": "matched", "parent_id": None}},
        "matched_sessions": 1,
        "total_sessions": 1,
        "errors": 0,
    }


def claim(**changes: Any) -> dict[str, Any]:
    result = {"purpose": "项目开发", "amount": None, "currency": "CNY", "amount_note": ""}
    result.update(changes)
    return result


def analyze_capture(
    store: Any, data: dict[str, Any] | None = None, **selection: Any
) -> dict[str, Any]:
    from aha.analysis import analyze

    capture = store.retain(data or source_data(), metadata())
    loaded = store.get_capture(capture["id"])
    result = analyze(
        loaded["data"],
        loaded["metadata"],
        store.config(),
        selection.get("start_date", "2026-10-24"),
        selection.get("end_date", "2026-10-26"),
        selection.get("project_id", "all"),
    )
    result["capture_id"] = capture["id"]
    result["claim_revision"] = store.claim_revision()
    result["availability_mode"] = "available"
    result["target_batch_id"] = selection.get("target_batch_id")
    return result
