"""Dense-scope claim refreshes must use related index ranges, not pairwise scans."""

from __future__ import annotations

import json
import tempfile
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from test_storage_helpers import claim, detail, rollup, source_data

from aha import claims, ledger, queries
from aha.domain import record_key
from aha.storage import Store


@contextmanager
def dense_store(count: int, *, backlog: bool = False) -> Iterator[tuple[Store, dict, str]]:
    """30% persistent owners, a semantic overlap, and optional unrelated open cases."""
    with tempfile.TemporaryDirectory(prefix="aha-dense-claims-") as directory:
        store = Store(Path(directory))
        try:
            base = detail()["created_at"]
            main = [detail(str(i), created_at=base + i) for i in range(count)]
            historical = [detail(f"old-{i}", created_at=base - 86400 - i)
                          for i in range(count // 5)] if backlog else []
            store.sync_data(source_data([*main, *historical]), trust="live")
            project = store.save_project(None, "baseline", "", [])["project"]["id"]
            store.assign_keys(
                [record_key(row) for i, row in enumerate(main) if i % 10 < 3], project
            )
            saved = store.create_batch(store.analyze("2026-10-26", "2026-10-26", project),
                                       claim(), "baseline")
            if historical:
                backup = source_data([{**row, "total_cost_usd": "0.5"} for row in historical])
                backup["source"]["name"] = "backlog.sql"
                store.sync_data(backup)
                empty_backup = source_data([])
                empty_backup["source"]["name"] = "backlog.sql"
                store.sync_data(empty_backup)
            store.sync_data(source_data([
                *main, *historical, {**main[0], "request_id": "semantic-overlap"},
            ]), trust="live")
            scope = store._db.execute(
                "SELECT scope_key FROM usage_records WHERE record_key=?", (record_key(main[0]),)
            ).fetchone()[0]
            store._db.execute("ANALYZE")
            yield store, saved, scope
        finally:
            store.close()


def measured(connection, action) -> tuple[Any, int]:
    instructions = 0

    def progress():
        nonlocal instructions
        instructions += 100
        return 0

    connection.set_progress_handler(progress, 100)
    try:
        result = action()
    finally:
        connection.set_progress_handler(None, 0)
    return result, instructions


def snapshot(store: Store) -> dict[str, Any]:
    return {"claims": [
        {"member": json.loads(row["member_json"]),
         "owner": {"batch_id": row["batch_id"], "version": row["owner_version"],
                   "number": f"AHA-{row['number']:06d}", "status": "draft", "lifecycle": "active"}}
        for row in store._db.execute(
            "SELECT c.*,b.number FROM usage_claims c JOIN batches b ON b.id=c.batch_id"
        )
    ]}


class DenseAvailabilityTests(unittest.TestCase):
    def test_refresh_density_doubles_work_linearly_and_preserves_reference_decisions(self) -> None:
        for backlog in (False, True):
            with self.subTest(backlog=backlog):
                work = []
                for count in (200, 400):
                    with dense_store(count, backlog=backlog) as (store, _, scope):
                        analysis = store.analyze(
                            "2026-10-26", "2026-10-26", availability_mode="all"
                        )
                        rows = list(store.iter_analysis_rows(analysis))
                        members = [claims.member_from_row(row, row["kind"]) for row in rows]
                        expected = claims.evaluate(members, snapshot(store))
                        excluded = {
                            entry["key"]: entry["reasons"] for entry in expected["excluded"]
                        }

                        def refresh():
                            with store._transaction():
                                ledger.refresh_availability(store._db, {scope})

                        _, steps = measured(store._db, refresh)
                        work.append(steps)
                        actual = {
                            row["record_key"]: (row["availability_state"], row["usage_reason"])
                            for row in store._db.execute(
                                "SELECT * FROM usage_records WHERE scope_key=?", (scope,)
                            )
                        }
                        for row in rows:
                            reasons = excluded.get(row["record_key"], [])
                            decision = (("claimed", "identity") if "identity" in reasons
                                        else ("pending", "overlap") if reasons
                                        else ("available", ""))
                            self.assertEqual(actual[row["record_key"]], decision)
                self.assertLess(work[1], work[0] * 2.5,
                                f"dense peer claims/cases caused quadratic refresh: {work}")

    def test_target_and_fifty_owner_explanations_do_not_scan_peer_detail_claims(self) -> None:
        target_work, owner_work = [], []
        for count in (200, 400):
            with dense_store(count, backlog=True) as (store, saved, _):
                analysis = store.analyze("2026-10-26", "2026-10-26", availability_mode="all")
                rows = list(store.iter_analysis_rows(analysis))
                members = [claims.member_from_row(row, row["kind"]) for row in rows]
                expected = claims.evaluate(members, snapshot(store), saved["id"])
                where, parameters = queries._filters({**analysis, "availability_mode": "available",
                                                       "target_batch_id": saved["id"]})
                selected, steps = measured(store._db, lambda: {
                    row[0] for row in store._db.execute(
                        "SELECT r.record_key FROM usage_records r WHERE " + where, parameters
                    )
                })
                self.assertEqual(selected, set(expected["available_keys"]))
                target_work.append(steps)
                records = store._db.execute(
                    "SELECT r.*,v.payload_json,'' AS project_name FROM usage_records r "
                    "JOIN usage_versions v ON v.id=r.version_id "
                    "WHERE r.availability_state='claimed' ORDER BY r.record_key LIMIT 50"
                ).fetchall()
                owners, steps = measured(store._db, lambda: [
                    queries._enrich_row(store, store._db, row, owners=True)["usage_owners"]
                    for row in records
                ])
                self.assertTrue(all(value == [{"batch_id": saved["id"], "version": 1}]
                                    for value in owners))
                owner_work.append(steps)
        self.assertLess(target_work[1], target_work[0] * 2.5, target_work)
        self.assertLessEqual(owner_work[1], owner_work[0] + 500, owner_work)

    def test_cross_grain_owners_and_pending_priority_survive_exact_index_branches(self) -> None:
        for owned_kind in ("detail", "rollup"):
            with self.subTest(owned_kind=owned_kind), tempfile.TemporaryDirectory() as directory:
                store = Store(Path(directory))
                try:
                    first, history = detail(), rollup(date="2026-10-26", request_model="separate")
                    store.sync_data(source_data([first], [history]), trust="live")
                    projects = {kind: store.save_project(None, kind, "", [])["project"]["id"]
                                for kind in ("detail", "rollup")}
                    for kind, row in (("detail", first), ("rollup", history)):
                        store.assign_keys([record_key(row, kind)], projects[kind])
                    saved = store.create_batch(
                        store.analyze("2026-10-26", "2026-10-26", projects[owned_kind]),
                        claim(), "cross-grain-owner",
                    )
                    self.assertEqual(store.list_reconciliations(), [])
                    peer = "rollup" if owned_kind == "detail" else "detail"
                    states = {row["kind"]: (row["availability_state"], row["usage_reason"])
                              for row in store._db.execute("SELECT * FROM usage_records")}
                    self.assertEqual(states[owned_kind], ("claimed", "identity"))
                    self.assertEqual(states[peer], ("pending", "overlap"))
                    peer_row = store._db.execute(
                        "SELECT r.*,v.payload_json,'' AS project_name FROM usage_records r "
                        "JOIN usage_versions v ON v.id=r.version_id WHERE kind=?", (peer,)
                    ).fetchone()
                    self.assertEqual(queries._enrich_row(
                        store, store._db, peer_row, owners=True,
                    )["usage_owners"], [{"batch_id": saved["id"], "version": 1}])
                    own_target = store.analyze("2026-10-26", "2026-10-26", projects[peer],
                                               target_batch_id=saved["id"])
                    self.assertEqual(own_target["summary"]["record_count"],
                                     1 if peer == "detail" else history["request_count"])
                    candidate = source_data(
                        [{**first, "total_cost_usd": "9"}] if owned_kind == "detail" else [],
                        [{**history, "total_cost_usd": "9"}] if owned_kind == "rollup" else [],
                    )
                    candidate["source"]["name"] = "revision.sql"
                    store.sync_data(candidate)
                    owned_state = store._db.execute(
                        "SELECT availability_state,usage_reason FROM usage_records WHERE kind=?",
                        (owned_kind,),
                    ).fetchone()
                    self.assertEqual(tuple(owned_state), ("pending", "reconciliation"))
                    store.sync_data(source_data([]), trust="live")
                    self.assertTrue(all(tuple(row) == ("pending", "reconciliation")
                                        for row in store._db.execute(
                                            "SELECT availability_state,usage_reason "
                                            "FROM usage_records"
                                        )))
                    self.assertEqual(store._db.execute(
                        "SELECT COUNT(*) FROM usage_claims"
                    ).fetchone()[0], 1)
                finally:
                    store.close()
