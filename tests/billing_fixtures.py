"""Ledger billing fixtures use only synthetic data and temporary Store directories."""

from __future__ import annotations

import copy
from typing import Any

from test_storage_helpers import metadata, source_data

from aha.storage import Store


def seed_analysis(
    store: Store, data: dict[str, Any] | None = None, **selection: Any
) -> dict[str, Any]:
    store.sync_data(data or source_data(), metadata(), trust="live")
    return store.analyze(
        selection.pop("start_date", "2026-10-24"),
        selection.pop("end_date", "2026-10-27"),
        selection.pop("project_id", "all"),
        **selection,
    )


def frozen_analysis(store: Store, batch_id: str) -> dict[str, Any]:
    history = store.batch_detail(batch_id)
    current = next(
        item for item in history["revisions"] if item["version"] == history["active_version"]
    )
    analysis = copy.deepcopy(current["analysis"])
    analysis.update(
        frozen_basis={"batch_id": batch_id, "version": history["active_version"]},
        target_batch_id=batch_id,
        expected_generation=history["generation"],
        expected_active_version=history["active_version"],
        claim_revision=store.claim_revision(),
    )
    return analysis
