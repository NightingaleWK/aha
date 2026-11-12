"""Create a synthetic old ledger reproducing lost directories, ambiguity and a record exception."""

import json
import os
import runpy
import sys
from pathlib import Path


def main():
    source = Path(__file__).resolve().parents[4]
    task = Path(os.environ["AHA_QA_ROOT"])
    sys.path.insert(0, str(task / "baseline-source/src"))
    from aha.storage import Store
    from aha.domain import content_hash, record_key
    from aha import ledger

    helpers = runpy.run_path(str(source / "tests/test_storage_helpers.py"))
    detail, rollup, data = (helpers[k] for k in ("detail", "rollup", "source_data"))
    target = task / "association-ui-fixture-v2"
    assert not target.exists()
    target.mkdir()
    (target / "task-ownership.json").write_text(
        json.dumps({"task": "project-record-continuity", "synthetic": True}) + "\n", encoding="utf-8")
    store = Store(target / "store")
    groups = [("history-a", 80, "/old/a"), ("history-b", 55, "/old/b"),
              ("generic-work", 12, "/old/shared"), ("no-evidence", 3, None),
              ("ambiguous", 2, "/old/a")]
    rows = []
    metadata = {"sessions": {}}
    offset = 0
    for session, count, cwd in groups:
        for index in range(count):
            rows.append(detail(request_id=f"synthetic-{session}-{index}", session_id=session,
                               created_at=1792947600 + offset))
            offset += 1
        if cwd:
            metadata["sessions"][session] = {"status": "matched", "cwd": cwd, "parent_id": None}
    try:
        a = store.save_project(None, "合成项目甲", "历史目录与跨页归属验证", ["/old/a"])["project"]["id"]
        b = store.save_project(None, "合成项目乙", "历史恢复与逐条例外验证", ["/old/b"])["project"]["id"]
        c = store.save_project(None, "合成项目丙", "批量分配与报销材料验证", ["/new/c"])["project"]["id"]
        dataset = data(rows, [rollup()])
        store.sync_data(dataset, metadata, trust="live")
        store.assign_keys([record_key(next(r for r in rows if r["request_id"] == "synthetic-no-evidence-0"))], b)
        # Independently construct the pre-fix state: effective evidence was lost,
        # while accepted versions survived. The committed guard now prevents
        # reproducing this state just by refreshing nonexistent roots.
        with store._transaction():
            second = {"status": "matched", "cwd": "/old/b", "parent_id": None}
            store._db.execute("INSERT INTO session_metadata_versions(session_id,content_hash,payload_json,created_at) VALUES(?,?,?,?)",
                              ("ambiguous", content_hash(second), store._encode(second), store._now()))
            for session, _, cwd in groups:
                if not cwd:
                    continue
                missing = {"status": "missing", "cwd": None, "parent_id": None}
                fingerprint = content_hash(missing)
                store._db.execute("INSERT INTO session_metadata_versions(session_id,content_hash,payload_json,created_at) VALUES(?,?,?,?)",
                                  (session, fingerprint, store._encode(missing), store._now()))
                store._db.execute("UPDATE sessions SET status='missing',cwd=NULL,content_hash=? WHERE id=?", (fingerprint, session))
            ledger.reclassify(store._db)
            ledger.refresh_availability(store._db)
            store._advance_revision()
        with store.read_connection() as connection:
            assert connection.execute("PRAGMA user_version").fetchone()[0] == 3
            assert connection.execute("SELECT COUNT(*) FROM usage_records WHERE kind='detail'").fetchone()[0] == 152
            assert connection.execute("SELECT COUNT(*) FROM usage_records WHERE project_id!=''").fetchone()[0] == 1
        report = {"synthetic": True, "schema": 3, "data_directory": str(target / "store"),
                  "project_a": a, "project_b": b, "project_c": c, "detail_count": 152,
                  "rollup_count": 1, "record_count": 159, "initial_assigned": 1,
                  "cross_page_session": "history-a", "cross_page_count": 80}
        (target / "fixture.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (task / "association-fixture-info.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))
    finally:
        store.close()


if __name__ == "__main__":
    main()
