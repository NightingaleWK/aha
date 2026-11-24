"""Synthetic, deterministic Codex session input shared by HTTP and EXE checks."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

START = datetime(2026, 10, 26, tzinfo=UTC)
SESSION = "019aa0bf-0730-7000-8000-000000000001"
MODEL = "gpt-6.2-sol"
INPUT = 20
CACHED = 5
OUTPUT = 10
COST = "0.0001305"


def write_rollout(
    root: Path, count: int, *, session: str = SESSION, cwd: str = "C:/synthetic/project",
    start: datetime = START, first_index: int = 0,
) -> Path:
    root = Path(root)
    directory = root / "sessions" / start.strftime("%Y/%m/%d")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"rollout-{start:%Y-%m-%dT%H-%M-%S}-{session}.jsonl"

    def emit(timestamp: datetime, kind: str, payload: dict[str, Any]) -> str:
        return json.dumps({
            "timestamp": timestamp.isoformat().replace("+00:00", "Z"),
            "type": kind, "payload": payload,
        }) + "\n"

    single = {
        "input_tokens": INPUT, "cached_input_tokens": CACHED, "output_tokens": OUTPUT,
        "reasoning_output_tokens": 3, "total_tokens": INPUT + OUTPUT,
    }
    with path.open("w" if first_index == 0 else "a", encoding="utf-8", newline="\n") as stream:
        if first_index == 0:
            stream.write(emit(start, "session_meta", {"id": session, "cwd": cwd}))
        for index in range(first_index, count):
            stamp = start + timedelta(seconds=index)
            turn = f"turn-{index}"
            stream.write(emit(stamp, "turn_context", {"turn_id": turn, "model": MODEL}))
            stream.write(emit(stamp, "event_msg", {
                "type": "token_count",
                "info": {
                    "last_token_usage": single,
                    "total_token_usage": {
                        key: value * (index + 1) for key, value in single.items()
                    },
                },
            }))
    return path
