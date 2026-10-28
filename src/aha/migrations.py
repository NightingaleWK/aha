"""Fresh schema3 only: trial business databases are deliberately not migrated."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from .domain import AppError

if TYPE_CHECKING:
    from .storage import Store

SCHEMA_VERSION = 3
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


def initialize(store: Store, base_schema: str = "") -> None:
    connection = store._db
    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if version == SCHEMA_VERSION:
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
