# Usage evidence and local runtime contract

## 1. Scope / Trigger

Read this before changing `src/aha/*.py`, source schemas, persistence, HTTP endpoints, or Windows packaging. The application is an independent Python 3.12+ loopback tool. CCS is a read-only source; `Store` owns a separate application database. Do not reuse either database as the other.

## 2. Signatures

```python
load_sqlite(path: Path) -> dict[str, Any]
load_sql_dump(data: bytes, name: str) -> dict[str, Any]
scan_metadata(session_ids: set[str], roots: list[Path]) -> dict[str, Any]
analyze(data, metadata, config, start_date, end_date, project_id="all") -> dict[str, Any]
Store(data_dir: Path)
Store.retain(data, metadata) -> dict[str, Any]
Store.config() -> dict[str, Any]
Store.save_project(project_id, name, description, directories) -> dict[str, Any]
Store.create_batch(analysis, claim, idempotency_key, batch_id=None) -> dict[str, Any]
Store.download(batch_id, version) -> tuple[bytes, str]
```

Source dictionaries contain `schema_version`, `details`, `rollups`, `pricing`, `source`. Source schema is **23**; application `aha.sqlite3` schema is **1**. `storage.py` is the schema owner. Its tables are `settings`, `projects`, `overrides`, `captures`, `observations`, `batches`, `revisions`, `status_events`, and `idempotency`. Related modules use the `Store` facade and its serialized transaction boundary.

CLI: `python -m aha [--data-dir PATH] [--port 0] [--no-browser]`. Windows defaults to `%LOCALAPPDATA%\aha`; development/tests pass their own directory. `runtime.json` contains this launch's PID, run identity and private bootstrap URL. Cleanup removes only a descriptor belonging to that run.

## 3. Contracts

- SQLite sources use URI `mode=ro`, `query_only`, and SQLite backup into memory, including committed WAL contents. Do not use `immutable=1` for live databases or copy only the main file. SQL imports parse a bounded literal subset and project allowed fields; never execute imported SQL.
- Only `app_type=codex` and `data_source=codex_session` detail rows, and `_codex_session` Codex rollups, contribute. Raw-source identity and content fingerprints exclude derived project names.
- All costs cross JSON/CSV boundaries as exact decimal **strings**. Sum saved `total_cost_usd` using `Decimal`; do not multiply saved cost again or recalculate it from current prices. `analysis.py` is the single calculator for preview and package generation.
- `input_token_semantics`: `0` subtracts cache reads, `1` subtracts reads and creations, `2` is already fresh input. If subtraction would be negative, preserve the original input and flag the anomaly. Total tokens add fresh input, output, reads, creations exactly once.
- Date filters use Beijing midnight inclusive to next-day midnight exclusive. Rollups retain their actual daily grain and represented request count. Never manufacture per-request rows or treat an absent day as proof of zero usage.
- Classification uses content-bound manual overrides first, then longest complete directory prefix, then unassigned. Windows paths ignore case; Linux paths preserve it. Overlapping parent/child directory rules are allowed; duplicate canonical rules across projects are rejected. `config.revision` invalidates cached analyses after a classification change.
- `retain` stores immutable compressed allowed projections and metadata, with source observations separate from content identity. Each analysis chooses **one capture**. Reading twice neither doubles counts nor merges captures. Missing/corrupt historical files fail explicitly.
- `save_project` returns updated config plus the saved `project`; do not treat the whole return value as a project object. Metadata `errors` is a list of safe `{code,count}` records.
- A batch version freezes analysis, membership, claim, project name, source and generated ZIP. New versions start `draft`. Status (`draft`, `submitted`, `reimbursed`) is manually correctable per version and does not rewrite its ZIP. The same idempotency key reuses its saved version, including concurrent retries. Within an existing batch, an unchanged latest analysis and claim also reuse that revision with a new retry key. A deliberately created separate batch remains separate and receives overlap warnings.
- ZIP has exactly `使用明细.csv`, `每日汇总.csv`, `费用说明.html`, `导出信息.json`. CSV is UTF-8 BOM with formula protection; HTML is escaped. Manifest hashes cover the other three files; stored ZIP hash covers the whole package. Download returns the original bytes after validation.
- Shared artifacts omit credentials, full source paths, directory rules, conversation text, IPs and entire SQL. Manual purpose/project/amount-note text is deliberately included. Claim amount is nullable or a nonnegative decimal with at most two fractional digits; nonblank amount requires a note. No automatic subscription allocation or FX.
- HTTP binds only `127.0.0.1`. A random bootstrap credential exchanges for an HttpOnly SameSite cookie. Validate Host, Origin and CSRF for mutations; assets are bundled under a restrictive CSP. Public errors use `AppError(code,message,status)` and never include SQL, paths, tokens or tracebacks.

## 4. Validation & Error Matrix

| Condition | Result |
| --- | --- |
| Unsupported CCS schema or missing required columns | `unsupported_schema` / `incompatible_schema`; no successful capture |
| SQL over 128 MiB / oversized database or row count | explicit size error / HTTP 413 |
| Nonfinite/negative cost, invalid token integer or duplicate source key | reject import; never silently coerce/deduplicate |
| Invalid dates or reversed range | `invalid_date` / `invalid_date_range` |
| Classification revision changed | `classification_changed` / `analysis_expired`, HTTP 409 |
| Missing/corrupt retained object or package | `artifact_missing`, `capture_damaged` or `package_damaged`, HTTP 409; an immutable write collision may return `artifact_damaged`; never regenerate an old artifact |
| Unknown application store version | `unsupported_store`, HTTP 409; preserve files |
| Retry key reused for different content | explicit idempotency conflict |
| Foreign Host/Origin or wrong CSRF | HTTP 403 |
| Export overlaps another batch | warning with status and certainty; user may continue |

## 5. Good / Base / Bad Cases

- Good: bind two explicit Windows/Linux directories to one stable project, import once, filter one capture, export and reopen the same ZIP after restart.
- Base: missing metadata leaves detail rows unassigned; date-only export still works. Complete daily rollups may be manually assigned but cannot be split proportionally.
- Bad: add totals from two captures, classify from a similar directory basename, use float money, infer actual subscription payments from reference cost, or recreate a damaged old ZIP from today's source.

## 6. Tests Required

Run `python -m unittest discover -s tests -v`, `python -m ruff check src tests scripts`, `python -m mypy src/aha`, and `python -m compileall -q src/aha` in the isolated environment.

- `test_sources.py`: committed WAL included; original source bytes unchanged; imported SQL cannot execute side effects.
- `test_analysis.py`: all three token semantics, exact decimal sum, Beijing boundaries, mixed grain, project partition and no pagination truncation.
- `test_session_meta.py`: ordinary/zstd bounded headers, missing/conflicting metadata and no conversation payload retention. Explicitly close SQLite connections so Windows can remove fixtures.
- `test_storage.py`: duplicate retention, atomic write/transaction failure, restart without original source, corrupt object and version rejection.
- `test_batches.py` / `test_evidence.py`: concurrent retry, original bytes after rule/status changes, cross-grain overlap, BOM/formula/HTML protection and privacy.
- `test_http.py` / `test_http_cli.py`: real loopback access boundaries, stale analysis, download hash, owned-server shutdown and persistent restart. Windows venv launchers may have a different PID from the service; verify the descriptor's server process and closed port.
- Native release gate: Windows directory build first, actual EXE/browser import and download, CSV in target Excel, HTML print, then OneFile build and restart smoke. A Linux test pass alone is insufficient.

## 7. Wrong vs Correct

```python
# Wrong: historical estimates become a different amount; live WAL may be lost.
cost = float(tokens) * current_price
connection = sqlite3.connect("file:cc-switch.db?immutable=1", uri=True)

# Correct: reuse validated saved costs and the source snapshot reader.
data = load_sqlite(source_path)
result = analyze(data, metadata, config, start_date, end_date, project_id)
cost_text = result["summary"]["total_cost_usd"]
```
