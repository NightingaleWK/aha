"""Versioned local schemas and lossless project-association migration."""

from __future__ import annotations

import sqlite3
from functools import lru_cache
from typing import TYPE_CHECKING

from .domain import AppError

if TYPE_CHECKING:
    from .storage import Store

SCHEMA_VERSION = 4
SUPPORTED_BACKUP_SCHEMAS = (3, 4)
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
SCHEMA = SCHEMA_V3 + ASSOCIATION_SCHEMA


@lru_cache(maxsize=2)
def schema_definition(
    version: int,
) -> tuple[dict[str, list[tuple[object, ...]]], dict[str, str]]:
    """Build each supported definition from its production, versioned DDL."""
    if version not in SUPPORTED_BACKUP_SCHEMAS:
        raise AppError("unsupported_backup_store", "这份 aha 资料版本不受支持。", 409)
    connection = sqlite3.connect(":memory:")
    try:
        connection.executescript(SCHEMA_V3 if version == 3 else SCHEMA)
        initialize_monthly(connection)
        initialize_source_observations(connection)
        initialize_query_indexes(connection)
        from . import batches

        batches.initialize_schema(connection)
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
    connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise AppError("storage_damaged", "资料关联校验失败，升级未完成。", 409)


def initialize(store: Store, base_schema: str = "") -> None:
    connection = store._db
    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if version == SCHEMA_VERSION:
        return
    if version == 3:
        upgrade_schema3(connection, store._now())
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
    initialize_source_observations(connection)
    initialize_query_indexes(connection)
    from . import batches

    batches.initialize_schema(connection)
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
