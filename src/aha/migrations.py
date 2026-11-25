"""Versioned ledger schemas and upgrades of existing local data."""

from __future__ import annotations

import json
import sqlite3
from functools import lru_cache
from typing import TYPE_CHECKING

from .domain import AppError

if TYPE_CHECKING:
    from .storage import Store

SCHEMA_VERSION = 6
SUPPORTED_BACKUP_SCHEMAS = (3, 4, 5, SCHEMA_VERSION)
MONTHLY_SCHEMA = """
CREATE TABLE IF NOT EXISTS monthly_usage_stats(month TEXT NOT NULL,
 project_id TEXT NOT NULL,model TEXT NOT NULL,kind TEXT NOT NULL,state TEXT NOT NULL,
 row_count INTEGER NOT NULL,record_count TEXT NOT NULL,fresh_input_tokens TEXT NOT NULL,
 output_tokens TEXT NOT NULL,cache_read_tokens TEXT NOT NULL,
 cache_creation_tokens TEXT NOT NULL,total_tokens TEXT NOT NULL,total_cost_usd TEXT NOT NULL,
 unpriced_count TEXT NOT NULL DEFAULT '0',
 PRIMARY KEY(month,project_id,model,kind,state));
CREATE INDEX IF NOT EXISTS monthly_stats_project_month ON monthly_usage_stats(project_id,month);
"""
SOURCE_OBSERVATIONS_SCHEMA = """CREATE TABLE IF NOT EXISTS source_rollup_observations(
 source_id TEXT NOT NULL REFERENCES source_profiles(id),record_key TEXT NOT NULL,
 request_count TEXT NOT NULL,PRIMARY KEY(source_id,record_key))"""
QUERY_INDEXES = """
CREATE INDEX IF NOT EXISTS stats_excluded_day_model_state
 ON daily_usage_stats(day,model,state) WHERE state!='available';
CREATE INDEX IF NOT EXISTS stats_excluded_project_day_model_state
 ON daily_usage_stats(project_id,day,model,state) WHERE state!='available';
"""
SCHEMA = """
CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
INSERT INTO settings VALUES('revision','0'),('data_revision','0'),('claim_revision','0');
CREATE TABLE projects(id TEXT PRIMARY KEY,name TEXT NOT NULL,description TEXT NOT NULL,
 directories_json TEXT NOT NULL);
CREATE TABLE overrides(record_key TEXT PRIMARY KEY,content_hash TEXT NOT NULL,
 project_id TEXT NOT NULL REFERENCES projects(id));
CREATE TABLE source_profiles(id TEXT PRIMARY KEY,kind TEXT NOT NULL,name TEXT NOT NULL,
 location TEXT,trust TEXT NOT NULL,created_at TEXT NOT NULL,last_run_id TEXT);
CREATE TABLE source_epochs(id TEXT PRIMARY KEY,source_id TEXT NOT NULL REFERENCES
source_profiles(id),
 state TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE sync_runs(id TEXT PRIMARY KEY,source_id TEXT REFERENCES source_profiles(id),
 state TEXT NOT NULL,trigger TEXT NOT NULL,startup_id TEXT UNIQUE,started_at TEXT NOT NULL,
 completed_at TEXT,heartbeat_at TEXT NOT NULL,result_json TEXT NOT NULL DEFAULT '{}',
 error_code TEXT,error_message TEXT,data_revision INTEGER);
CREATE UNIQUE INDEX one_sync_running ON sync_runs(state) WHERE state='running';
CREATE TABLE usage_versions(id INTEGER PRIMARY KEY,record_key TEXT NOT NULL,
 content_hash TEXT NOT NULL,payload_json TEXT NOT NULL,created_at TEXT NOT NULL,
 source_id TEXT NOT NULL REFERENCES source_profiles(id),UNIQUE(record_key,content_hash));
CREATE TABLE usage_records(record_key TEXT PRIMARY KEY,kind TEXT NOT NULL,
 version_id INTEGER NOT NULL REFERENCES usage_versions(id),content_hash TEXT NOT NULL,
 day TEXT NOT NULL,event_time INTEGER NOT NULL,scope_key TEXT NOT NULL,coverage_key TEXT NOT NULL,
 semantic_key TEXT,model TEXT NOT NULL,pricing_model TEXT NOT NULL DEFAULT '',session_id
TEXT,project_id TEXT NOT NULL DEFAULT '',
 assignment_origin TEXT NOT NULL DEFAULT 'unassigned',cwd TEXT,
 availability_state TEXT NOT NULL DEFAULT 'available',usage_reason TEXT NOT NULL DEFAULT '',
 suppressed INTEGER NOT NULL DEFAULT 0,request_count TEXT NOT NULL,
 fresh_input_tokens TEXT NOT NULL,output_tokens TEXT NOT NULL,cache_read_tokens TEXT NOT NULL,
 cache_creation_tokens TEXT NOT NULL,total_tokens TEXT NOT NULL,total_cost_usd TEXT NOT NULL,
 pricing_status TEXT NOT NULL DEFAULT 'missing_basis');
CREATE INDEX usage_time ON usage_records(event_time,record_key);
CREATE INDEX usage_project_time ON usage_records(project_id,event_time,record_key);
CREATE INDEX usage_available_time ON
usage_records(availability_state,suppressed,event_time,record_key);
CREATE INDEX usage_project_available_time ON
usage_records(project_id,availability_state,suppressed,event_time,record_key);
CREATE INDEX usage_scope ON usage_records(scope_key);
CREATE INDEX usage_coverage ON usage_records(coverage_key,kind);
CREATE INDEX usage_semantic ON usage_records(semantic_key) WHERE semantic_key IS NOT NULL;
CREATE INDEX usage_pricing ON usage_records(pricing_model,scope_key);
CREATE INDEX usage_model ON usage_records(model,scope_key);
CREATE INDEX usage_session ON usage_records(session_id) WHERE session_id IS NOT NULL;
CREATE INDEX usage_day ON usage_records(day,project_id,model);
CREATE TABLE record_evidence(version_id INTEGER NOT NULL REFERENCES usage_versions(id),
 source_id TEXT NOT NULL REFERENCES source_profiles(id),run_id TEXT NOT NULL REFERENCES
sync_runs(id),
 PRIMARY KEY(version_id,source_id));
CREATE TABLE record_aliases(alias_key TEXT PRIMARY KEY,canonical_key TEXT NOT NULL,reason TEXT
NOT NULL);
CREATE TABLE sessions(id TEXT PRIMARY KEY,cwd TEXT,status TEXT NOT NULL,parent_id TEXT,
 content_hash TEXT NOT NULL,last_checked TEXT NOT NULL DEFAULT '');
CREATE TABLE session_metadata_versions(id INTEGER PRIMARY KEY,session_id TEXT NOT NULL,
 content_hash TEXT NOT NULL,payload_json TEXT NOT NULL,created_at TEXT NOT NULL,
 UNIQUE(session_id,content_hash));
CREATE TABLE pricing(model_id TEXT PRIMARY KEY,payload_json TEXT NOT NULL);
CREATE TABLE coverage_groups(id TEXT PRIMARY KEY,scope_key TEXT NOT NULL,day TEXT NOT NULL,
 model TEXT NOT NULL,basis TEXT NOT NULL DEFAULT 'unknown',generation INTEGER NOT NULL DEFAULT 1);
CREATE TABLE reconciliation_cases(id TEXT PRIMARY KEY,type TEXT NOT NULL,
 coverage_key TEXT,record_key TEXT,source_id TEXT,state TEXT NOT NULL DEFAULT 'open',
 generation INTEGER NOT NULL DEFAULT 1,message TEXT NOT NULL,info_json TEXT NOT NULL,
 UNIQUE(type,coverage_key,record_key,source_id));
CREATE INDEX cases_coverage ON reconciliation_cases(coverage_key,state);
CREATE INDEX cases_source ON reconciliation_cases(source_id,state);
CREATE INDEX cases_record ON reconciliation_cases(record_key,state);
CREATE TABLE reconciliation_events(id INTEGER PRIMARY KEY,case_id TEXT NOT NULL,
 choice TEXT NOT NULL,reason TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE reconciliation_idempotency(key TEXT PRIMARY KEY,payload_hash TEXT NOT
NULL,result_json TEXT NOT NULL);
CREATE TABLE daily_usage_stats(day TEXT NOT NULL,project_id TEXT NOT NULL,model TEXT NOT NULL,
 kind TEXT NOT NULL,state TEXT NOT NULL,row_count INTEGER NOT NULL,record_count TEXT NOT NULL,
 fresh_input_tokens TEXT NOT NULL,output_tokens TEXT NOT NULL,cache_read_tokens TEXT NOT NULL,
 cache_creation_tokens TEXT NOT NULL,total_tokens TEXT NOT NULL,total_cost_usd TEXT NOT NULL,
 unpriced_count TEXT NOT NULL DEFAULT '0',
 PRIMARY KEY(day,project_id,model,kind,state));
CREATE INDEX stats_project_day ON daily_usage_stats(project_id,day);
CREATE TABLE sync_stage(run_id TEXT NOT NULL,record_key TEXT NOT NULL,kind TEXT NOT NULL,
 content_hash TEXT NOT NULL,payload_json TEXT NOT NULL,PRIMARY KEY(run_id,record_key));
CREATE TABLE sync_pricing(run_id TEXT NOT NULL,model_id TEXT NOT NULL,payload_json TEXT NOT NULL,
 PRIMARY KEY(run_id,model_id));
"""
SCHEMA_V3 = SCHEMA
ASSOCIATION_SCHEMA = """
CREATE TABLE record_project_links(record_key TEXT PRIMARY KEY REFERENCES usage_records(record_key),
 project_id TEXT REFERENCES projects(id),basis TEXT NOT NULL,basis_json TEXT NOT NULL,
 generation INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE INDEX record_links_project ON record_project_links(project_id,record_key);
CREATE TABLE session_project_bindings(session_id TEXT PRIMARY KEY REFERENCES sessions(id),
 project_id TEXT NOT NULL REFERENCES projects(id),basis TEXT NOT NULL,basis_json TEXT NOT NULL,
 generation INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE project_assignment_events(id INTEGER PRIMARY KEY,operation_id TEXT NOT NULL,
 record_key TEXT,session_id TEXT,old_project_id TEXT,project_id TEXT,basis TEXT NOT NULL,
 reason TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE INDEX assignment_events_record ON project_assignment_events(record_key,id);
CREATE INDEX assignment_events_operation ON project_assignment_events(operation_id,id);
"""
SCHEMA_V4 = SCHEMA_V3 + ASSOCIATION_SCHEMA
CODEX_SCHEMA = """
CREATE INDEX sync_runs_source ON sync_runs(source_id);
CREATE INDEX codex_history_session_time ON usage_records(session_id,day,model,event_time)
 WHERE kind='detail' AND semantic_key IS NOT NULL AND suppressed=0;
CREATE TABLE codex_file_progress(source_id TEXT NOT NULL REFERENCES source_profiles(id),
 path_key TEXT NOT NULL,cursor_json TEXT NOT NULL,PRIMARY KEY(source_id,path_key));
CREATE TABLE codex_event_evidence(version_id INTEGER NOT NULL REFERENCES usage_versions(id),
 source_id TEXT NOT NULL REFERENCES source_profiles(id),evidence_hash TEXT NOT NULL,
 event_id TEXT NOT NULL,run_id TEXT NOT NULL REFERENCES sync_runs(id),pricing_basis TEXT,
 evidence_json TEXT NOT NULL,PRIMARY KEY(version_id,source_id,evidence_hash));
CREATE INDEX codex_snapshot_identity ON codex_event_evidence(
 json_extract(evidence_json,'$.snapshot_id'),event_id);
"""
LEGACY_ROLLUP_INDEX = """
CREATE INDEX codex_history_rollup_day ON usage_records(day)
 WHERE kind='rollup' AND suppressed=0;
"""
SCHEMA_V5 = SCHEMA_V4 + CODEX_SCHEMA + LEGACY_ROLLUP_INDEX
SCHEMA = SCHEMA_V4 + CODEX_SCHEMA
DETAIL_ONLY_GUARDS = (
    """CREATE TRIGGER usage_records_detail_insert BEFORE INSERT ON usage_records
    WHEN NEW.kind!='detail' BEGIN SELECT RAISE(ABORT,'aha_detail_required'); END""",
    """CREATE TRIGGER usage_records_detail_update BEFORE UPDATE OF kind ON usage_records
    WHEN NEW.kind!='detail' BEGIN SELECT RAISE(ABORT,'aha_detail_required'); END""",
)
ARCHIVED_CLAIM_INDEX = """CREATE INDEX usage_claim_archived_day
    ON usage_claims(json_extract(member_json,'$.date')) WHERE kind='rollup'"""


@lru_cache(maxsize=len(SUPPORTED_BACKUP_SCHEMAS))
def schema_definition(
    version: int,
) -> tuple[dict[str, list[tuple[object, ...]]], dict[str, str]]:
    """Build each supported definition from its production, versioned DDL."""
    if version not in SUPPORTED_BACKUP_SCHEMAS:
        raise AppError("unsupported_backup_store", "这份 aha 资料版本不受支持。", 409)
    connection = sqlite3.connect(":memory:")
    try:
        connection.executescript(
            {3: SCHEMA_V3, 4: SCHEMA_V4, 5: SCHEMA_V5, SCHEMA_VERSION: SCHEMA}[version]
        )
        initialize_monthly(connection)
        if version <= 5:
            initialize_source_observations(connection)
        else:
            for statement in DETAIL_ONLY_GUARDS:
                connection.execute(statement)
        initialize_query_indexes(connection)
        from . import batches

        batches.initialize_schema(connection)
        if version == SCHEMA_VERSION:
            connection.execute(ARCHIVED_CLAIM_INDEX)
        tables = {
            str(row[0]): [tuple(column) for column in connection.execute(
                f'PRAGMA table_info("{row[0]}")'
            )]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        definitions = {
            str(kind) + ":" + str(name): " ".join(str(sql).split())
            for kind, name, sql in connection.execute(
                "SELECT type,name,sql FROM sqlite_master WHERE type IN ('table','index','trigger')"
            )
        }
        return tables, definitions
    finally:
        connection.close()


def validate_structure(connection: sqlite3.Connection, version: int) -> None:
    expected, definitions = schema_definition(version)
    tables = {
        str(row[0]) for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    actual = {
        str(kind) + ":" + str(name): " ".join(str(sql).split())
        for kind, name, sql in connection.execute(
            "SELECT type,name,sql FROM sqlite_master WHERE type IN ('table','index','trigger')"
        )
    }
    if (tables != set(expected) or actual != definitions or connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='view' LIMIT 1"
    ).fetchone() is not None):
        raise AppError("invalid_backup", "资料结构不完整或不兼容，未执行升级或还原。", 409)
    for table, columns in expected.items():
        if [tuple(row) for row in connection.execute(f'PRAGMA table_info("{table}")')] != columns:
            raise AppError("invalid_backup", "资料字段不兼容，未执行升级或还原。", 409)


def upgrade_schema3(connection: sqlite3.Connection, now: str) -> None:
    """Run only inside the caller's transaction, after preserving the schema3 source."""
    validate_structure(connection, 3)
    for statement in ASSOCIATION_SCHEMA.split(";"):
        if statement.strip():
            connection.execute(statement)
    connection.execute(
        """INSERT INTO record_project_links(record_key,project_id,basis,basis_json,
        created_at,updated_at) SELECT r.record_key,
        CASE WHEN r.assignment_origin='directory_rule' THEN NULLIF(r.project_id,'') END,
        CASE WHEN r.assignment_origin='directory_rule' THEN 'directory_rule' ELSE 'unassigned' END,
        json_object('cwd',r.cwd,'migration',3),?,? FROM usage_records r""",
        (now, now),
    )
    connection.execute(
        """INSERT INTO session_project_bindings(session_id,project_id,basis,basis_json,
        created_at,updated_at) SELECT r.session_id,MIN(r.project_id),'directory_rule',
        json_object('migration',3),?,? FROM usage_records r JOIN sessions s ON s.id=r.session_id
        WHERE r.assignment_origin='directory_rule' AND r.project_id!=''
        GROUP BY r.session_id HAVING COUNT(DISTINCT r.project_id)=1""", (now, now),
    )
    connection.execute("PRAGMA user_version=4")
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise AppError("storage_damaged", "资料关联校验失败，升级未完成。", 409)


def _retire_rollup_only_cases(connection: sqlite3.Connection) -> None:
    from . import ledger
    from .codex_sessions import _timestamp

    for case_id, version_id, raw_payload in connection.execute("""
        SELECT c.id,v.id,v.payload_json FROM reconciliation_cases c
        LEFT JOIN usage_records r ON r.record_key=c.record_key
        LEFT JOIN usage_versions v ON v.id=r.version_id
        WHERE c.type='native_overlap' AND c.state='open'
          AND json_extract(c.info_json,'$.pending_reason')='historical_rollup'
          AND c.id NOT IN (SELECT id FROM temp.retired_usage_cases)
    """):
        if raw_payload is not None:
            payload = json.loads(raw_payload)
            if payload.get("data_source") != "codex_native":
                continue
            pairs = (
                stamp[0] for row in connection.execute("""
                    SELECT json_extract(evidence_json,'$.snapshot_timestamp')
                    FROM codex_event_evidence WHERE version_id=?
                      AND json_extract(evidence_json,'$.kind')='response'
                      AND json_extract(evidence_json,'$.pending_reason') IS NULL
                """, (version_id,))
                if (stamp := _timestamp(row[0])) is not None
            )
            detail, session = ledger.historical_detail_overlap(
                connection, payload, ledger.record_projection(payload, "detail"), pairs
            )
            if detail or session:
                continue
        connection.execute("INSERT INTO temp.retired_usage_cases VALUES(?)", (case_id,))


def _retire_rollups(connection: sqlite3.Connection) -> None:
    """Delete retired facts while keeping versions referenced by frozen materials."""
    from . import ledger

    before = connection.total_changes
    connection.execute(ARCHIVED_CLAIM_INDEX)
    connection.execute("""CREATE TEMP TABLE retired_usage_keys AS
        SELECT record_key FROM usage_records WHERE kind='rollup'
        UNION SELECT record_key FROM usage_versions WHERE record_key GLOB 'rollup:*'""")
    connection.execute(
        "CREATE UNIQUE INDEX temp.retired_usage_key ON retired_usage_keys(record_key)"
    )
    connection.execute("""CREATE TEMP TABLE retired_usage_versions AS
        SELECT v.id FROM usage_versions v
        JOIN temp.retired_usage_keys k ON k.record_key=v.record_key
        WHERE NOT EXISTS(SELECT 1 FROM revision_members m WHERE m.usage_version_id=v.id)""")
    connection.execute("""CREATE TEMP TABLE retired_usage_cases AS
        SELECT id FROM reconciliation_cases
        WHERE type IN ('coverage','rollup_origin')
          OR record_key IN (SELECT record_key FROM temp.retired_usage_keys)
          OR json_extract(info_json,'$.other_record_key') IN
             (SELECT record_key FROM temp.retired_usage_keys)
          OR (type='source' AND json_type(info_json,'$.previous.detail')='integer'
              AND json_type(info_json,'$.observed.detail')='integer'
              AND json_extract(info_json,'$.observed.detail')*2 >=
                  json_extract(info_json,'$.previous.detail')
              AND json_type(info_json,'$.rollup_request_count_regressed') IS NOT NULL)""")

    # The former aggregate-only decision had hidden these already stored details.
    connection.execute("""UPDATE usage_records SET suppressed=0
        WHERE kind='detail' AND suppressed=1
          AND coverage_key IN (SELECT id FROM coverage_groups WHERE basis='rollup')
          AND record_key NOT IN (SELECT alias_key FROM record_aliases)
          AND NOT EXISTS(SELECT 1 FROM reconciliation_cases c
            JOIN reconciliation_events e ON e.case_id=c.id AND e.choice='same'
            WHERE c.record_key=usage_records.record_key
              AND c.type='identity' AND c.state='resolved')""")
    connection.execute("""UPDATE coverage_groups SET basis='detail',generation=generation+1
        WHERE basis='rollup'""")
    _retire_rollup_only_cases(connection)
    connection.execute("""UPDATE reconciliation_cases
        SET info_json=json_set(info_json,'$.pending_reason','historical_usage_unverified'),
            generation=generation+1
        WHERE type='native_overlap'
          AND json_extract(info_json,'$.pending_reason')='historical_rollup'""")
    connection.execute("""UPDATE reconciliation_cases
        SET info_json=json_remove(
            info_json,'$.observed.rollup','$.previous.rollup','$.rollup_request_count_regressed'
        ) WHERE type='source'
          AND json_type(info_json,'$.rollup_request_count_regressed') IS NOT NULL
          AND id NOT IN (SELECT id FROM temp.retired_usage_cases)""")
    connection.execute("""DELETE FROM reconciliation_events
        WHERE case_id IN (SELECT id FROM temp.retired_usage_cases)""")
    connection.execute("""DELETE FROM reconciliation_idempotency
        WHERE json_extract(result_json,'$.id') IN (SELECT id FROM temp.retired_usage_cases)""")
    connection.execute(
        "DELETE FROM reconciliation_cases WHERE id IN (SELECT id FROM temp.retired_usage_cases)"
    )
    for table in ("record_project_links", "project_assignment_events", "overrides"):
        connection.execute(
            f"DELETE FROM {table} WHERE record_key IN "
            "(SELECT record_key FROM temp.retired_usage_keys)"
        )
    connection.execute("""DELETE FROM record_aliases
        WHERE alias_key IN (SELECT record_key FROM temp.retired_usage_keys)
          OR canonical_key IN (SELECT record_key FROM temp.retired_usage_keys)""")
    connection.execute("DELETE FROM usage_records WHERE kind='rollup'")
    for table in ("record_evidence", "codex_event_evidence"):
        connection.execute(
            f"DELETE FROM {table} WHERE version_id IN (SELECT id FROM temp.retired_usage_versions)"
        )
    connection.execute(
        "DELETE FROM usage_versions WHERE id IN (SELECT id FROM temp.retired_usage_versions)"
    )
    connection.execute("DELETE FROM sync_stage WHERE kind='rollup'")
    connection.execute("""UPDATE sync_runs
        SET result_json=json_remove(result_json,'$.observed.rollup')
        WHERE json_type(result_json,'$.observed.rollup') IS NOT NULL""")
    changed = connection.total_changes != before
    if changed or connection.execute(
        "SELECT 1 FROM usage_claims WHERE kind='rollup' LIMIT 1"
    ).fetchone() is not None:
        ledger.refresh_availability(connection)
    if changed:
        connection.execute("""UPDATE settings SET value=CAST(value AS INTEGER)+1
            WHERE key IN ('revision','data_revision')""")
    else:
        connection.execute("DELETE FROM daily_usage_stats WHERE kind='rollup'")
        connection.execute("DELETE FROM monthly_usage_stats WHERE kind='rollup'")

    for table in ("retired_usage_keys", "retired_usage_versions", "retired_usage_cases"):
        connection.execute(f"DROP TABLE temp.{table}")
    connection.execute("DROP TABLE source_rollup_observations")
    connection.execute("DROP INDEX codex_history_rollup_day")
    for statement in DETAIL_ONLY_GUARDS:
        connection.execute(statement)


def upgrade(connection: sqlite3.Connection, version: int, now: str) -> None:
    """Upgrade an isolated restore or a live ledger with a verified rollback backup."""
    if version == 3:
        upgrade_schema3(connection, now)
    if version <= 4:
        validate_structure(connection, 4)
        for statement in (CODEX_SCHEMA + LEGACY_ROLLUP_INDEX).split(";"):
            if statement.strip():
                connection.execute(statement)
    validate_structure(connection, 5)
    _retire_rollups(connection)
    connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
    validate_structure(connection, SCHEMA_VERSION)
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise AppError("storage_damaged", "资料关联校验失败，升级未完成。", 409)


def initialize(store: Store, base_schema: str = "") -> None:
    connection = store._db
    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if version == SCHEMA_VERSION:
        return
    if version in SUPPORTED_BACKUP_SCHEMAS:
        upgrade(connection, version, store._now())
        return
    if (
        version != 0
        or connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone()
    ):
        raise AppError(
            "unsupported_store", "这份试用资料需要先保全历史用量并受控重建；未改动原资料。", 409
        )
    for statement in SCHEMA.split(";"):
        if statement.strip():
            connection.execute(statement)
    initialize_monthly(connection)
    initialize_query_indexes(connection)
    for statement in DETAIL_ONLY_GUARDS:
        connection.execute(statement)
    from . import batches

    batches.initialize_schema(connection)
    connection.execute(ARCHIVED_CLAIM_INDEX)
    connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise AppError("storage_damaged", "资料结构校验失败。", 500)


def initialize_monthly(connection: sqlite3.Connection) -> None:
    """Fresh schema3 DDL; also used explicitly to update isolated benchmark fixtures."""
    for statement in MONTHLY_SCHEMA.split(";"):
        if statement.strip():
            connection.execute(statement)


def initialize_source_observations(connection: sqlite3.Connection) -> None:
    connection.execute(SOURCE_OBSERVATIONS_SCHEMA)


def initialize_query_indexes(connection: sqlite3.Connection) -> None:
    for statement in QUERY_INDEXES.split(";"):
        if statement.strip():
            connection.execute(statement)


def sqlite_wal_safe(version: tuple[int, ...] | None = None) -> bool:
    actual = version or sqlite3.sqlite_version_info
    return (
        actual >= (3, 51, 3)
        or (actual[:2] == (3, 50) and actual >= (3, 50, 7))
        or (actual[:2] == (3, 44) and actual >= (3, 44, 6))
    )
