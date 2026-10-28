"""Fresh ledger billing, indexed ownership, row-wise freezing and atomic publication."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

from . import decimal_sql
from .claims import member_from_row, scope_key, semantic_key, validate_members
from .domain import (
    DETAIL_FIELDS,
    ROLLUP_FIELDS,
    AppError,
    canonical_bytes,
    content_hash,
    parse_date,
)
from .evidence import build_evidence, file_hash, validate_claim

if TYPE_CHECKING:
    from .storage import Store

STATUSES = {"draft": "草稿", "submitted": "已提交", "reimbursed": "已报销"}
COUNT_FIELDS = (
    "record_count",
    "detail_count",
    "rollup_record_count",
    "rollup_count",
    "unpriced_count",
)
TOKEN_FIELDS = (
    "fresh_input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_creation_tokens",
    "total_tokens",
)
COST_FIELDS = ("total_cost_usd", "detail_cost_usd", "rollup_cost_usd")
FREEZE_FIELDS = (
    *DETAIL_FIELDS,
    *ROLLUP_FIELDS,
    "kind",
    "record_key",
    "version_id",
    "content_fingerprint",
    "date",
    "time",
    "project_id",
    "project_name",
    "assignment_origin",
    "fresh_input_tokens",
    "total_tokens",
    "pricing_status",
)
CHUNK_SIZE = 500


def initialize_schema(connection: sqlite3.Connection) -> None:
    """Create only the schema3 billing tables; called inside Store's transaction."""
    statements = (
        "CREATE TABLE billing_sequence(id INTEGER PRIMARY KEY CHECK(id=1),"
        "next_number INTEGER NOT NULL)",
        "INSERT INTO billing_sequence VALUES(1,1)",
        """CREATE TABLE batches(
            id TEXT PRIMARY KEY,number INTEGER NOT NULL UNIQUE,created_at TEXT NOT NULL,
            active_version INTEGER NOT NULL,lifecycle TEXT NOT NULL
              CHECK(lifecycle IN ('active','voided')),
            generation INTEGER NOT NULL CHECK(generation>=1),voided_at TEXT,void_reason TEXT,
            FOREIGN KEY(id,active_version) REFERENCES revisions(batch_id,version)
              DEFERRABLE INITIALLY DEFERRED)""",
        """CREATE TABLE revisions(
            batch_id TEXT NOT NULL REFERENCES batches(id),version INTEGER NOT NULL,
            created_at TEXT NOT NULL,status TEXT NOT NULL
              CHECK(status IN ('draft','submitted','reimbursed')),
            status_updated_at TEXT NOT NULL,analysis_json TEXT NOT NULL,claim_json TEXT NOT NULL,
            selection_hash TEXT NOT NULL,business_hash TEXT NOT NULL,
            zip_path TEXT NOT NULL,zip_hash TEXT NOT NULL,file_name TEXT NOT NULL,
            frozen_hash TEXT NOT NULL,PRIMARY KEY(batch_id,version))""",
        """CREATE TABLE revision_members(
            batch_id TEXT NOT NULL,version INTEGER NOT NULL,record_key TEXT NOT NULL,
            usage_version_id INTEGER NOT NULL REFERENCES usage_versions(id),kind TEXT NOT NULL,
            scope_key TEXT NOT NULL,semantic_key TEXT,member_json TEXT NOT NULL,
            frozen_json TEXT NOT NULL,PRIMARY KEY(batch_id,version,record_key),
            FOREIGN KEY(batch_id,version) REFERENCES revisions(batch_id,version))""",
        "CREATE INDEX revision_member_record ON revision_members(record_key,batch_id,version)",
        """CREATE TABLE usage_claims(
            record_key TEXT PRIMARY KEY,batch_id TEXT NOT NULL,owner_version INTEGER NOT NULL,
            kind TEXT NOT NULL CHECK(kind IN ('detail','rollup')),scope_key TEXT NOT NULL,
            semantic_key TEXT,member_json TEXT NOT NULL,
            FOREIGN KEY(batch_id,owner_version) REFERENCES revisions(batch_id,version))""",
        "CREATE INDEX usage_claim_scope ON usage_claims(scope_key,kind)",
        "CREATE INDEX usage_claim_semantic ON usage_claims(semantic_key) "
        "WHERE semantic_key IS NOT NULL",
        "CREATE INDEX usage_claim_owner ON usage_claims(batch_id)",
        """CREATE TABLE batch_events(
            id INTEGER PRIMARY KEY,batch_id TEXT NOT NULL REFERENCES batches(id),version INTEGER,
            action TEXT NOT NULL,reason TEXT NOT NULL,created_at TEXT NOT NULL,
            from_version INTEGER,to_version INTEGER,old_status TEXT,new_status TEXT)""",
        """CREATE TABLE idempotency(
            key TEXT PRIMARY KEY,operation TEXT NOT NULL,request_signature TEXT NOT NULL,
            batch_id TEXT NOT NULL,version INTEGER NOT NULL,
            FOREIGN KEY(batch_id,version) REFERENCES revisions(batch_id,version))""",
        """CREATE TRIGGER batch_events_no_update BEFORE UPDATE ON batch_events
            BEGIN SELECT RAISE(ABORT,'aha_immutable_history'); END""",
        """CREATE TRIGGER batch_events_no_delete BEFORE DELETE ON batch_events
            BEGIN SELECT RAISE(ABORT,'aha_immutable_history'); END""",
        """CREATE TRIGGER revision_members_no_update BEFORE UPDATE ON revision_members
            BEGIN SELECT RAISE(ABORT,'aha_immutable_members'); END""",
        """CREATE TRIGGER revision_members_no_delete BEFORE DELETE ON revision_members
            BEGIN SELECT RAISE(ABORT,'aha_immutable_members'); END""",
        """CREATE TRIGGER revisions_facts_no_update BEFORE UPDATE OF
            created_at,analysis_json,claim_json,selection_hash,business_hash,
            zip_path,zip_hash,file_name,frozen_hash ON revisions
            BEGIN SELECT RAISE(ABORT,'aha_immutable_revision'); END""",
    )
    for statement in statements:
        connection.execute(statement)


def _key(value: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise AppError("invalid_idempotency_key", "操作信息不完整，请刷新后重试。")


def _revision(connection: sqlite3.Connection, batch_id: str, version: int) -> sqlite3.Row:
    row = connection.execute(
        "SELECT * FROM revisions WHERE batch_id=? AND version=?", (batch_id, version)
    ).fetchone()
    if row is None:
        raise AppError("revision_not_found", "找不到这份材料，请刷新报销记录。", 404)
    return cast(sqlite3.Row, row)


def _batch(connection: sqlite3.Connection, batch_id: str) -> sqlite3.Row:
    row = connection.execute("SELECT * FROM batches WHERE id=?", (batch_id,)).fetchone()
    if row is None:
        raise AppError("batch_not_found", "找不到这条报销记录，请刷新。", 404)
    return cast(sqlite3.Row, row)


def _check_generation(control: sqlite3.Row, expected: int | None) -> None:
    if expected is not None and (
        isinstance(expected, bool)
        or not isinstance(expected, int)
        or expected != control["generation"]
    ):
        raise AppError("stale_batch", "这条报销记录已更新，请刷新后重试。", 409)


def _effective(
    connection: sqlite3.Connection,
    batch_id: str,
    version: int | None = None,
    generation: int | None = None,
) -> tuple[sqlite3.Row, sqlite3.Row]:
    control = _batch(connection, batch_id)
    if control["lifecycle"] == "voided":
        raise AppError("batch_voided", "这条报销记录已作废，可查看或下载历史材料。", 409)
    if version is not None and version != control["active_version"]:
        raise AppError("inactive_revision", "这是历史版本，请使用当前记录。", 409)
    _check_generation(control, generation)
    return control, _revision(connection, batch_id, control["active_version"])


def _decoded_object(value: str) -> dict[str, Any]:
    try:
        decoded = json.loads(value)
        if not isinstance(decoded, dict):
            raise ValueError
        return cast(dict[str, Any], decoded)
    except (TypeError, ValueError) as exc:
        raise AppError("storage_damaged", "本地报销资料损坏，请保留资料目录。", 409) from exc


def _revision_result(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    *,
    include_analysis: bool = False,
) -> dict[str, Any]:
    batch = _batch(connection, row["batch_id"])
    analysis, claim = _decoded_object(row["analysis_json"]), _decoded_object(row["claim_json"])
    effective = batch["lifecycle"] == "active" and batch["active_version"] == row["version"]
    draft = effective and row["status"] == "draft"
    number = f"AHA-{batch['number']:06d}"
    result: dict[str, Any] = {
        "id": row["batch_id"],
        "batch_id": row["batch_id"],
        "number": number,
        "batch_number": number,
        "version": row["version"],
        "status": row["status"],
        "created_at": row["created_at"],
        "status_updated_at": row["status_updated_at"],
        "filename": row["file_name"],
        "sha256": row["zip_hash"],
        "zip_sha256": row["zip_hash"],
        "frozen_hash": row["frozen_hash"],
        "total_cost_usd": analysis["summary"]["total_cost_usd"],
        "claim": claim,
        "summary": analysis["summary"],
        "start_date": analysis["start_date"],
        "end_date": analysis["end_date"],
        "project_id": analysis.get("project_id", "all"),
        "project_name": analysis.get("project_name", "全部项目"),
        "classification_revision": analysis.get("classification_revision", 0),
        "data_revision": analysis.get("data_revision", 0),
        "lifecycle": batch["lifecycle"],
        "active_version": batch["active_version"],
        "generation": batch["generation"],
        "is_effective": effective,
        "voided_at": batch["voided_at"],
        "void_reason": batch["void_reason"],
        "can_edit": draft,
        "can_submit": draft,
        "can_reimburse": effective and row["status"] in {"draft", "submitted"},
        "can_withdraw": effective and row["status"] == "submitted",
        "can_void": effective,
        "member_count": analysis.get("member_count", 0),
    }
    if include_analysis:
        result["analysis"] = analysis
    return result


def _current_result(connection: sqlite3.Connection, batch_id: str) -> dict[str, Any]:
    control = _batch(connection, batch_id)
    return _revision_result(connection, _revision(connection, batch_id, control["active_version"]))


def _request_signature(
    analysis: dict[str, Any],
    claim: dict[str, Any],
    batch_id: str | None,
    expected_generation: int | None,
    expected_active_version: int | None,
    supplied: str | None,
) -> str:
    if supplied is not None:
        if not isinstance(supplied, str) or not supplied or len(supplied) > 512:
            raise AppError("invalid_request_signature", "请求依据无效，请重新发起。")
        return supplied
    return content_hash(
        {
            "operation": "create",
            "analysis": analysis,
            "claim": claim,
            "batch_id": batch_id,
            "generation": expected_generation,
            "active_version": expected_active_version,
        }
    )


def _prior(
    connection: sqlite3.Connection,
    key: str,
    signature: str,
    operation: str,
) -> dict[str, Any] | None:
    row = connection.execute("SELECT * FROM idempotency WHERE key=?", (key,)).fetchone()
    if row is None:
        return None
    if row["operation"] != operation or row["request_signature"] != signature:
        raise AppError("idempotency_conflict", "请求内容已变化，请重新发起操作。", 409)
    return _revision_result(connection, _revision(connection, row["batch_id"], row["version"]))


def replay_create(
    store: Store, idempotency_key: str, request_signature: str
) -> dict[str, Any] | None:
    _key(idempotency_key)
    with store.read_connection() as connection:
        result = _prior(connection, idempotency_key, request_signature, "create")
    if result is not None:
        download(store, result["id"], result["version"])
    return result


def _validate_preview(analysis: dict[str, Any], batch_id: str | None) -> None:
    if not isinstance(analysis, dict) or not isinstance(analysis.get("summary"), dict):
        raise AppError("invalid_analysis", "用量预览无效，请更新预览。")
    try:
        start, end = parse_date(analysis["start_date"]), parse_date(analysis["end_date"])
        if start > end:
            raise ValueError
    except (KeyError, TypeError, ValueError) as exc:
        raise AppError("invalid_analysis", "用量预览无效，请更新预览。") from exc
    if analysis.get("availability_mode", "available") != "available":
        raise AppError("readonly_analysis", "请选择可用用量后再保存报销记录。", 409)
    if analysis.get("target_batch_id") != batch_id:
        raise AppError("analysis_target_mismatch", "请为这条报销记录重新预览用量。", 409)
    if not analysis["summary"].get("record_count"):
        raise AppError("empty_usage", "当前没有可用用量，请调整项目或日期。", 409)


def _frozen_basis(analysis: dict[str, Any], batch_id: str | None) -> tuple[str, int] | None:
    value = analysis.get("frozen_basis")
    if value is None:
        return None
    if (
        not isinstance(value, dict)
        or batch_id is None
        or value.get("batch_id") != batch_id
        or isinstance(value.get("version"), bool)
        or not isinstance(value.get("version"), int)
    ):
        raise AppError("analysis_target_mismatch", "冻结用量不属于当前报销记录。", 409)
    return batch_id, value["version"]


def _frozen_rows(
    connection: sqlite3.Connection,
    batch_id: str,
    version: int,
) -> Iterator[dict[str, Any]]:
    for row in connection.execute(
        "SELECT frozen_json FROM revision_members WHERE batch_id=? AND version=? "
        "ORDER BY record_key",
        (batch_id, version),
    ):
        yield _decoded_object(row["frozen_json"])


@contextmanager
def _candidate_connection(path: Path) -> Iterator[sqlite3.Connection]:
    uri = path.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA cache_size=-8192")
        decimal_sql.register(connection)
        yield connection


def _candidate_rows(path: Path, column: str = "frozen_json") -> Iterator[dict[str, Any]]:
    if column not in {"frozen_json", "member_json"}:
        raise ValueError("invalid internal projection")
    with _candidate_connection(path) as connection:
        for row in connection.execute(f"SELECT {column} FROM members ORDER BY record_key"):
            yield _decoded_object(row[column])


def _candidate_daily(path: Path) -> Iterator[dict[str, Any]]:
    columns = ",".join(f"integer_sum({key}) AS {key}" for key in (*COUNT_FIELDS, *TOKEN_FIELDS))
    columns += "," + ",".join(f"decimal_sum({key}) AS {key}" for key in COST_FIELDS)
    with _candidate_connection(path) as connection:
        for row in connection.execute(
            "SELECT project_id,MIN(project_name) AS project_name,day AS date,model,"
            + columns
            + ",CASE WHEN MIN(kind)<>MAX(kind) THEN 'mixed' WHEN MIN(kind)='detail' THEN 'detail' "
            "ELSE 'daily_rollup' END AS source_grain FROM members "
            "GROUP BY project_id,day,model ORDER BY day,project_id,model"
        ):
            result = dict(row)
            result["project_id"] = result["project_id"] or None
            for key in (*COUNT_FIELDS, *TOKEN_FIELDS):
                result[key] = int(result[key])
            yield result


@dataclass
class FrozenSelection:
    path: Path
    analysis: dict[str, Any]
    selection_hash: str
    member_count: int

    def close(self) -> None:
        self.path.unlink(missing_ok=True)


def _prepare_selection(
    store: Store,
    analysis: dict[str, Any],
    batch_id: str | None,
    expected_generation: int | None,
    expected_active_version: int | None,
) -> FrozenSelection:
    directory = store.data_dir / "temporary"
    directory.mkdir(exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix="billing-", suffix=".sqlite3", dir=directory)
    os.close(descriptor)
    path = Path(name)
    selection = FrozenSelection(path, {}, "", 0)
    money = {key: decimal_sql.DecimalSum() for key in COST_FIELDS}
    totals = {key: 0 for key in (*COUNT_FIELDS, *TOKEN_FIELDS)}
    grains: set[str] = set()
    digest = hashlib.sha256()
    try:
        with closing(sqlite3.connect(path)) as frozen, store.read_connection() as reader:
            frozen.execute("PRAGMA journal_mode=OFF")
            frozen.execute("PRAGMA cache_size=-8192")
            frozen.execute("PRAGMA temp_store=FILE")
            frozen.execute("""CREATE TABLE members(
                record_key TEXT PRIMARY KEY,kind TEXT NOT NULL,usage_version_id INTEGER NOT NULL,
                scope_key TEXT NOT NULL,semantic_key TEXT,frozen_json TEXT NOT NULL,
                member_json TEXT NOT NULL,day TEXT NOT NULL,project_id TEXT NOT NULL,
                project_name TEXT NOT NULL,model TEXT NOT NULL,record_count TEXT NOT NULL,
                detail_count TEXT NOT NULL,rollup_record_count TEXT NOT NULL,
                rollup_count TEXT NOT NULL,
                unpriced_count TEXT NOT NULL,fresh_input_tokens TEXT NOT NULL,
                output_tokens TEXT NOT NULL,cache_read_tokens TEXT NOT NULL,
                cache_creation_tokens TEXT NOT NULL,total_tokens TEXT NOT NULL,
                total_cost_usd TEXT NOT NULL,detail_cost_usd TEXT NOT NULL,
                rollup_cost_usd TEXT NOT NULL)""")
            frozen.execute("CREATE INDEX member_scope ON members(scope_key,kind)")
            basis = _frozen_basis(analysis, batch_id)
            if basis is None:
                store.validate_analysis(analysis, connection=reader)
                rows = store.iter_analysis_rows(analysis, connection=reader)
            else:
                control, saved = _effective(reader, basis[0], basis[1], expected_generation)
                if (
                    control["active_version"] != expected_active_version
                    or saved["status"] != "draft"
                ):
                    raise AppError("batch_not_editable", "请先撤回已提交记录，再修改。", 409)
                saved_analysis = _decoded_object(saved["analysis_json"])
                for key in ("start_date", "end_date", "project_id", "project_name", "summary"):
                    if analysis.get(key) != saved_analysis.get(key):
                        raise AppError(
                            "invalid_analysis", "冻结依据已变化，请重新打开报销记录。", 409
                        )
                rows = _frozen_rows(reader, *basis)
            pending: list[tuple[Any, ...]] = []
            for original in rows:
                row = {key: original[key] for key in FREEZE_FIELDS if key in original}
                kind = row.get("kind")
                if not isinstance(kind, str) or kind not in {"detail", "rollup"}:
                    raise AppError("storage_damaged", "用量粒度无效，请保留本地资料。", 409)
                member = member_from_row(row, kind)
                member["key"] = (
                    store.canonical_record_key(member["key"], connection=reader)
                    if basis is None
                    else row["record_key"]
                )
                member = validate_members([member])[0]
                if member["key"] != row.get("record_key") or member["content_hash"] != row.get(
                    "content_fingerprint"
                ):
                    raise AppError("storage_damaged", "用量事实校验失败，请保留本地资料。", 409)
                version_id = row.get("version_id")
                if (
                    isinstance(version_id, bool)
                    or not isinstance(version_id, int)
                    or version_id <= 0
                ):
                    raise AppError("storage_damaged", "用量版本依据无效，请保留本地资料。", 409)
                row["project_id"] = row.get("project_id") or None
                row["project_name"] = row.get("project_name") or "未归属"
                count = 1 if kind == "detail" else member["request_count"]
                values = {
                    "record_count": count,
                    "detail_count": int(kind == "detail"),
                    "rollup_record_count": count if kind == "rollup" else 0,
                    "rollup_count": int(kind == "rollup"),
                    "unpriced_count": count if row.get("pricing_status") == "unpriced" else 0,
                }
                values.update({key: member[key] for key in TOKEN_FIELDS})
                for key, value in values.items():
                    totals[key] += int(value)
                costs = {
                    "total_cost_usd": row["total_cost_usd"],
                    "detail_cost_usd": row["total_cost_usd"] if kind == "detail" else "0",
                    "rollup_cost_usd": row["total_cost_usd"] if kind == "rollup" else "0",
                }
                for key in COST_FIELDS:
                    money[key].step(costs[key])
                grains.add(kind)
                frozen_json = canonical_bytes(row).decode()
                member.update(
                    {
                        "version_id": version_id,
                        **{
                            key: row.get(key)
                            for key in (
                                "project_id",
                                "project_name",
                                "assignment_origin",
                                "pricing_status",
                            )
                        },
                    }
                )
                pending.append(
                    (
                        member["key"],
                        kind,
                        version_id,
                        scope_key(member),
                        semantic_key(member),
                        frozen_json,
                        canonical_bytes(member).decode(),
                        member["date"],
                        row["project_id"] or "",
                        row["project_name"],
                        row["model"],
                        *(str(values[key]) for key in (*COUNT_FIELDS, *TOKEN_FIELDS)),
                        *(str(costs[key]) for key in COST_FIELDS),
                    )
                )
                if len(pending) == CHUNK_SIZE:
                    frozen.executemany(
                        "INSERT INTO members VALUES(" + ",".join("?" for _ in pending[0]) + ")",
                        pending,
                    )
                    pending.clear()
                selection.member_count += 1
            if pending:
                frozen.executemany(
                    "INSERT INTO members VALUES(" + ",".join("?" for _ in pending[0]) + ")", pending
                )
            frozen.commit()
            if not selection.member_count:
                raise AppError("empty_usage", "当前没有可用用量，请更新预览。", 409)
            for row in frozen.execute("SELECT frozen_json FROM members ORDER BY record_key"):
                digest.update(row[0].encode())
                digest.update(b"\n")
            summary: dict[str, Any] = {
                **totals,
                **{key: value.finalize() for key, value in money.items()},
            }
            summary["source_grain"] = (
                "mixed" if len(grains) > 1 else "detail" if "detail" in grains else "daily_rollup"
            )
            expected = analysis["summary"]
            for key in (*COUNT_FIELDS, *TOKEN_FIELDS):
                if expected.get(key) != summary[key]:
                    raise AppError(
                        "selection_changed", "冻结用量与预览合计不一致，请重新预览。", 409
                    )
            for key in COST_FIELDS:
                comparator = decimal_sql.DecimalSum()
                comparator.step(expected.get(key))
                if comparator.finalize() != summary[key]:
                    raise AppError(
                        "selection_changed", "冻结费用与预览合计不一致，请重新预览。", 409
                    )
            selection.selection_hash = digest.hexdigest()
            if basis is not None and selection.selection_hash != saved["selection_hash"]:
                raise AppError("storage_damaged", "冻结用量校验失败，请保留本地资料。", 409)
            fields = (
                "start_date",
                "end_date",
                "project_id",
                "project_name",
                "timezone",
                "data_revision",
                "classification_revision",
                "claim_revision",
                "warnings",
                "availability",
            )
            selection.analysis = {key: analysis[key] for key in fields if key in analysis}
            selection.analysis.update(
                summary=summary,
                member_count=selection.member_count,
                selection_hash=selection.selection_hash,
                availability_mode="available",
            )
        return selection
    except BaseException:
        selection.close()
        raise


def _dirty_scopes(
    connection: sqlite3.Connection, batch_id: str | None = None, *, candidate: bool = False
) -> None:
    connection.execute(
        "CREATE TEMP TABLE IF NOT EXISTS billing_dirty_scopes(scope_key TEXT PRIMARY KEY)"
    )
    connection.execute("DELETE FROM billing_dirty_scopes")
    if batch_id is not None:
        connection.execute(
            "INSERT OR IGNORE INTO billing_dirty_scopes "
            "SELECT DISTINCT scope_key FROM usage_claims WHERE batch_id=?",
            (batch_id,),
        )
    if candidate:
        connection.execute(
            "INSERT OR IGNORE INTO billing_dirty_scopes "
            "SELECT DISTINCT scope_key FROM billing_candidate.members"
        )


def _refresh(store: Store, connection: sqlite3.Connection) -> None:
    connection.execute(
        "UPDATE settings SET value=CAST(value AS INTEGER)+1 WHERE key='claim_revision'"
    )
    cursor = connection.execute("SELECT scope_key FROM billing_dirty_scopes ORDER BY scope_key")
    while rows := cursor.fetchmany(CHUNK_SIZE):
        store.refresh_availability(connection, {row[0] for row in rows})


def _check_candidate_conflicts(connection: sqlite3.Connection, batch_id: str | None) -> None:
    internal = connection.execute(
        "SELECT 1 FROM billing_candidate.members GROUP BY scope_key HAVING "
        "MAX(kind='rollup')=1 AND COUNT(*)>1 LIMIT 1"
    ).fetchone()
    if internal is not None:
        raise AppError("usage_internal_overlap", "所选明细和来源汇总可能重复，请核对。", 409)
    branches = (
        ("c.record_key=m.record_key", "usage_claimed"),
        (
            "c.scope_key=m.scope_key AND m.kind='detail' AND c.kind='rollup' "
            "AND c.record_key<>m.record_key",
            "usage_ambiguous",
        ),
        (
            "c.scope_key=m.scope_key AND m.kind='rollup' AND c.record_key<>m.record_key",
            "usage_ambiguous",
        ),
        (
            "c.semantic_key=m.semantic_key AND m.semantic_key IS NOT NULL "
            "AND c.record_key<>m.record_key",
            "usage_ambiguous",
        ),
    )
    for relation, code in branches:
        found = connection.execute(
            "SELECT 1 FROM billing_candidate.members m JOIN usage_claims c ON "
            + relation
            + " WHERE (? IS NULL OR c.batch_id<>?) LIMIT 1",
            (batch_id, batch_id),
        ).fetchone()
        if found is not None:
            raise AppError(code, "部分用量已被占用或可能重复，请更新预览。", 409)


def _record_event(
    store: Store,
    batch_id: str,
    version: int,
    action: str,
    reason: str,
    from_version: int | None,
    to_version: int | None,
    old_status: str | None,
    new_status: str | None,
) -> None:
    store._db.execute(
        "INSERT INTO batch_events(batch_id,version,action,reason,created_at,"
        "from_version,to_version,old_status,new_status) VALUES(?,?,?,?,?,?,?,?,?)",
        (
            batch_id,
            version,
            action,
            reason,
            store._now(),
            from_version,
            to_version,
            old_status,
            new_status,
        ),
    )


def _discard_unreferenced(store: Store, relative: str) -> None:
    try:
        with store.read_connection() as connection:
            referenced = connection.execute(
                "SELECT 1 FROM revisions WHERE zip_path=?", (relative,)
            ).fetchone()
        if referenced is None:
            store._file_path(relative).unlink(missing_ok=True)
    except (AppError, OSError, sqlite3.Error):
        # Preserve uncertain artifacts for inspection rather than risking a registered package.
        return


def create_batch(
    store: Store,
    analysis: dict[str, Any],
    claim: dict[str, Any],
    idempotency_key: str,
    batch_id: str | None = None,
    *,
    expected_generation: int | None = None,
    expected_active_version: int | None = None,
    request_signature: str | None = None,
) -> dict[str, Any]:
    _key(idempotency_key)
    claim = validate_claim(claim)
    signature = _request_signature(
        analysis, claim, batch_id, expected_generation, expected_active_version, request_signature
    )
    with store.read_connection() as connection:
        replayed = _prior(connection, idempotency_key, signature, "create")
    if replayed is not None:
        download(store, replayed["id"], replayed["version"])
        return replayed
    _validate_preview(analysis, batch_id)
    if batch_id is not None:
        expected_generation = (
            expected_generation
            if expected_generation is not None
            else analysis.get("expected_generation")
        )
        expected_active_version = (
            expected_active_version
            if expected_active_version is not None
            else analysis.get("expected_active_version")
        )
        if expected_generation is None or expected_active_version is None:
            raise AppError("stale_batch", "记录依据不完整，请重新打开报销记录。", 409)
    try:
        selection = _prepare_selection(
            store, analysis, batch_id, expected_generation, expected_active_version
        )
    except AppError:
        # Another process may commit this very request after the initial replay
        # read, before candidate preparation opens its snapshot. Its claim change
        # invalidates that old preview; persisted idempotency still wins.
        with store.read_connection() as connection:
            replayed = _prior(connection, idempotency_key, signature, "create")
        if replayed is None:
            raise
        download(store, replayed["id"], replayed["version"])
        return replayed
    except (OSError, sqlite3.Error) as exc:
        raise AppError("storage_write_failed", "冻结用量失败，请检查本地空间后重试。", 500) from exc
    published: str | None = None
    temporary: Path | None = None
    try:
        business_hash = content_hash(
            {
                "selection_hash": selection.selection_hash,
                "claim": claim,
                "selection": {
                    key: selection.analysis.get(key)
                    for key in ("start_date", "end_date", "project_id", "project_name")
                },
                "summary": selection.analysis["summary"],
            }
        )
        with store._transaction():
            existing = _prior(store._db, idempotency_key, signature, "create")
            if existing is not None:
                return existing
            basis = _frozen_basis(analysis, batch_id)
            if basis is None:
                store.validate_analysis(analysis, connection=store._db)
            if batch_id is None:
                number = store._db.execute(
                    "SELECT next_number FROM billing_sequence WHERE id=1"
                ).fetchone()[0]
                store._db.execute(
                    "UPDATE billing_sequence SET next_number=next_number+1 WHERE id=1"
                )
                batch_id_value, version = str(uuid4()), 1
            else:
                control, active = _effective(
                    store._db, batch_id, expected_active_version, expected_generation
                )
                if active["status"] != "draft":
                    raise AppError("batch_not_editable", "请先撤回已提交记录，再修改。", 409)
                if active["business_hash"] == business_hash:
                    store._db.execute(
                        "INSERT INTO idempotency VALUES(?,?,?,?,?)",
                        (idempotency_key, "create", signature, batch_id, active["version"]),
                    )
                    return _revision_result(store._db, active)
                batch_id_value = batch_id
                number = control["number"]
                version = store._db.execute(
                    "SELECT MAX(version)+1 FROM revisions WHERE batch_id=?", (batch_id,)
                ).fetchone()[0]
        created_at = store._now()
        batch = {
            "id": batch_id_value,
            "number": f"AHA-{number:06d}",
            "version": version,
            "created_at": created_at,
        }
        temporary = store.data_dir / "temporary" / f"billing-{uuid4().hex}.zip"
        _, filename, package = build_evidence(
            temporary,
            selection.analysis,
            claim,
            batch,
            rows=lambda: _candidate_rows(selection.path),
            daily_rows=lambda: _candidate_daily(selection.path),
            members=lambda: _candidate_rows(selection.path, "member_json"),
        )
        # Batch/version/hash already live in the immutable revision and manifest.
        # Keep the physical name short enough for normal nested Windows data paths.
        relative = f"packages/{uuid4().hex}.zip"
        frozen_hash = content_hash(
            {
                "selection_hash": selection.selection_hash,
                "analysis": selection.analysis,
                "claim": claim,
                "batch": batch,
            }
        )
        with store._lock:
            store._ensure_open()
            store._db.execute("ATTACH DATABASE ? AS billing_candidate", (str(selection.path),))
            try:
                with store._transaction():
                    existing = _prior(store._db, idempotency_key, signature, "create")
                    if existing is not None:
                        return existing
                    if basis is None:
                        store.validate_analysis(analysis, connection=store._db)
                    if batch_id is not None:
                        _, active = _effective(
                            store._db, batch_id, expected_active_version, expected_generation
                        )
                        if active["status"] != "draft":
                            raise AppError(
                                "batch_not_editable", "请先撤回已提交记录，再修改。", 409
                            )
                    _check_candidate_conflicts(store._db, batch_id)
                    _dirty_scopes(store._db, batch_id, candidate=True)
                    store.publish_file(relative, temporary)
                    published = relative
                    if batch_id is None:
                        store._db.execute(
                            "INSERT INTO batches VALUES(?,?,?,?,?,?,?,?)",
                            (batch_id_value, number, created_at, version, "active", 1, None, None),
                        )
                    else:
                        store._db.execute("DELETE FROM usage_claims WHERE batch_id=?", (batch_id,))
                    store._db.execute(
                        "INSERT INTO revisions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            batch_id_value,
                            version,
                            created_at,
                            "draft",
                            created_at,
                            store._encode(selection.analysis),
                            store._encode(claim),
                            selection.selection_hash,
                            business_hash,
                            relative,
                            package["sha256"],
                            filename,
                            frozen_hash,
                        ),
                    )
                    store._db.execute(
                        "INSERT INTO revision_members SELECT ?,?,record_key,usage_version_id,"
                        "kind,scope_key,semantic_key,member_json,frozen_json "
                        "FROM billing_candidate.members",
                        (batch_id_value, version),
                    )
                    store._db.execute(
                        "INSERT INTO usage_claims SELECT record_key,?,?,kind,scope_key,"
                        "semantic_key,member_json FROM billing_candidate.members",
                        (batch_id_value, version),
                    )
                    if batch_id is not None:
                        store._db.execute(
                            "UPDATE batches SET active_version=?,generation=generation+1 "
                            "WHERE id=?",
                            (version, batch_id),
                        )
                    _refresh(store, store._db)
                    _record_event(
                        store,
                        batch_id_value,
                        version,
                        "create" if batch_id is None else "revise",
                        "",
                        None if batch_id is None else expected_active_version,
                        version,
                        None if batch_id is None else "draft",
                        "draft",
                    )
                    store._db.execute(
                        "INSERT INTO idempotency VALUES(?,?,?,?,?)",
                        (idempotency_key, "create", signature, batch_id_value, version),
                    )
                    result = _revision_result(
                        store._db, _revision(store._db, batch_id_value, version)
                    )
                return result
            finally:
                store._db.execute("DETACH DATABASE billing_candidate")
    except AppError:
        raise
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError) as exc:
        raise AppError(
            "storage_write_failed", "报销资料保存失败，请检查本地空间后重试。", 500
        ) from exc
    finally:
        if published is not None:
            _discard_unreferenced(store, published)
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        selection.close()


def list_batches(store: Store) -> list[dict[str, Any]]:
    with store.read_connection() as connection:
        return [
            _revision_result(connection, row)
            for row in connection.execute(
                "SELECT r.* FROM batches b JOIN revisions r ON r.batch_id=b.id "
                "AND r.version=b.active_version ORDER BY b.number DESC"
            )
        ]


def batch_detail(store: Store, batch_id: str) -> dict[str, Any]:
    with store.read_connection() as connection:
        result = _current_result(connection, batch_id)
        result["revisions"] = [
            _revision_result(connection, row, include_analysis=True)
            for row in connection.execute(
                "SELECT * FROM revisions WHERE batch_id=? ORDER BY version", (batch_id,)
            )
        ]
        result["events"] = [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM batch_events WHERE batch_id=? ORDER BY id", (batch_id,)
            )
        ]
        result["current_difference_count"] = connection.execute(
            "SELECT COUNT(*) FROM revision_members m LEFT JOIN usage_records u "
            "ON u.record_key=m.record_key LEFT JOIN projects p ON p.id=u.project_id "
            "WHERE m.batch_id=? AND m.version=? "
            "AND (u.record_key IS NULL OR u.version_id<>m.usage_version_id "
            "OR u.suppressed=1 OR u.availability_state='pending' "
            "OR COALESCE(u.project_id,'')<>"
            "COALESCE(json_extract(m.frozen_json,'$.project_id'),'') "
            "OR COALESCE(p.name,'未归属')<>"
            "COALESCE(json_extract(m.frozen_json,'$.project_name'),'未归属'))",
            (batch_id, result["active_version"]),
        ).fetchone()[0]
        return result


def _reason(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 4000:
        raise AppError("reason_required", "请填写操作原因（最多 4000 个字符）。")
    return value.strip()


def set_status(
    store: Store,
    batch_id: str,
    version: int,
    status: str,
    expected_generation: int | None = None,
) -> dict[str, Any]:
    if status not in STATUSES:
        raise AppError("invalid_status", "请选择有效的报销状态。")
    with store._transaction():
        control, revision = _effective(store._db, batch_id, version, expected_generation)
        old_status = revision["status"]
        if status == old_status:
            return _revision_result(store._db, revision)
        if (
            status
            not in {
                "draft": {"submitted", "reimbursed"},
                "submitted": {"reimbursed"},
                "reimbursed": set(),
            }[old_status]
        ):
            raise AppError("invalid_transition", "请通过撤回或作废操作纠正这条记录。", 409)
        store._db.execute(
            "UPDATE revisions SET status=?,status_updated_at=? WHERE batch_id=? AND version=?",
            (status, store._now(), batch_id, version),
        )
        store._db.execute("UPDATE batches SET generation=generation+1 WHERE id=?", (batch_id,))
        _record_event(store, batch_id, version, "status", "", version, version, old_status, status)
        return _current_result(store._db, batch_id)


def lifecycle_action(
    store: Store,
    action: str,
    batch_id: str,
    expected_generation: int,
    reason: str,
    idempotency_key: str,
) -> dict[str, Any]:
    if action not in {"withdraw", "void"}:
        raise AppError("invalid_action", "请选择有效的报销操作。")
    _key(idempotency_key)
    reason = _reason(reason)
    signature = content_hash(
        {
            "action": action,
            "batch_id": batch_id,
            "generation": expected_generation,
            "reason": reason,
        }
    )
    with store._transaction():
        replayed = _prior(store._db, idempotency_key, signature, action)
        if replayed is not None:
            return _current_result(store._db, batch_id)
        control, revision = _effective(store._db, batch_id, generation=expected_generation)
        version, old_status = control["active_version"], revision["status"]
        if action == "withdraw":
            if old_status != "submitted":
                raise AppError("invalid_transition", "仅已提交记录可以撤回为草稿。", 409)
            store._db.execute(
                "UPDATE revisions SET status='draft',status_updated_at=? "
                "WHERE batch_id=? AND version=?",
                (store._now(), batch_id, version),
            )
            store._db.execute("UPDATE batches SET generation=generation+1 WHERE id=?", (batch_id,))
            new_status = "draft"
        else:
            _dirty_scopes(store._db, batch_id)
            store._db.execute("DELETE FROM usage_claims WHERE batch_id=?", (batch_id,))
            store._db.execute(
                "UPDATE batches SET lifecycle='voided',generation=generation+1,"
                "voided_at=?,void_reason=? WHERE id=?",
                (store._now(), reason, batch_id),
            )
            _refresh(store, store._db)
            new_status = old_status
        _record_event(
            store, batch_id, version, action, reason, version, version, old_status, new_status
        )
        store._db.execute(
            "INSERT INTO idempotency VALUES(?,?,?,?,?)",
            (idempotency_key, action, signature, batch_id, version),
        )
        return _current_result(store._db, batch_id)


def overlaps(
    store: Store,
    analysis: dict[str, Any],
    exclude_batch_id: str | None = None,
) -> list[dict[str, Any]]:
    target = analysis.get("target_batch_id")
    if exclude_batch_id is not None and exclude_batch_id != target:
        raise AppError("analysis_target_mismatch", "请为这条报销记录重新预览用量。", 409)
    _validate_preview(analysis, target)
    basis = _frozen_basis(analysis, target)
    with store.read_connection() as connection:
        if basis is None:
            store.validate_analysis(analysis, connection=connection)
            return []
        control, revision = _effective(
            connection, basis[0], basis[1], analysis.get("expected_generation")
        )
        if revision["status"] != "draft" or control["active_version"] != analysis.get(
            "expected_active_version"
        ):
            raise AppError("batch_not_editable", "请先撤回已提交记录，再修改。", 409)
        # Existing frozen members retain their own claims. Related ownership is indexed,
        # and no caller-supplied target may exempt a new application.
        found = connection.execute(
            "SELECT c.batch_id,c.owner_version,COUNT(*) AS conflicts FROM revision_members m "
            "JOIN usage_claims c ON c.record_key=m.record_key "
            "WHERE m.batch_id=? AND m.version=? AND c.batch_id<>? "
            "GROUP BY c.batch_id,c.owner_version LIMIT 50",
            (basis[0], basis[1], basis[0]),
        ).fetchall()
        return [
            {
                "batch_id": row["batch_id"],
                "version": row["owner_version"],
                "certain_count": row["conflicts"],
                "blocking": True,
                "types": ["identity"],
                "message": "冻结用量已被其他记录占用，请更新预览。",
            }
            for row in found
        ]


def download(store: Store, batch_id: str, version: int) -> tuple[Path, str]:
    with store.read_connection() as connection:
        revision = _revision(connection, batch_id, version)
        relative, expected, filename = (
            revision["zip_path"],
            revision["zip_hash"],
            revision["file_name"],
        )
    try:
        path = store._file_path(relative)
        if file_hash(path) != expected:
            raise AppError("package_damaged", "原材料校验失败，请保留本地资料。", 409)
        return path, filename
    except OSError as exc:
        raise AppError("artifact_missing", "原材料缺失或无法读取，请保留本地资料。", 409) from exc
