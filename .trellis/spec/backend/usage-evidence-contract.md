# Usage evidence and local runtime contract

## 1. Scope / Trigger

Read this before changing `src/aha/*.py`, source schemas, persistence, HTTP endpoints, or Windows packaging. The application is an independent Python 3.12+ loopback tool. CCS is a read-only source; `Store` owns a separate application database. Do not reuse either database as the other.

## 2. Signatures

```python
load_sqlite(path: Path) -> dict[str, Any]
load_sql_dump(data: bytes, name: str) -> dict[str, Any]
scan_metadata(session_ids: set[str], roots: list[Path]) -> dict[str, Any]
analyze(data, metadata, config, start_date, end_date, project_id="all", *,
        claim_snapshot=None, availability_mode="all", target_batch_id=None,
        expected_generation=None, expected_active_version=None) -> dict[str, Any]
Store(data_dir: Path)
Store.retain(data, metadata) -> dict[str, Any]
Store.config() -> dict[str, Any]
Store.save_project(project_id, name, description, directories) -> dict[str, Any]
Store.claim_snapshot(exclude_batch_id=None) -> dict[str, Any]
Store.claim_revision() -> int
Store.create_batch(analysis, claim, idempotency_key, batch_id=None, *,
                   expected_generation=None, expected_active_version=None,
                   request_signature=None) -> dict[str, Any]
Store.replay_create(idempotency_key, request_signature) -> dict[str, Any] | None
Store.withdraw_batch(batch_id, expected_generation, reason, idempotency_key)
Store.void_batch(batch_id, expected_generation, reason, idempotency_key)
Store.resolve_legacy(batch_id, selected_version, expected_generation, reason, idempotency_key)
Store.download(batch_id, version) -> tuple[bytes, str]
```

Source dictionaries contain `schema_version`, `details`, `rollups`, `pricing`, `source`. Source schema is **23**; application `aha.sqlite3` schema is **2**. `storage.py` owns connections/transactions/backups; `migrations.py` owns the serialized schema steps. Existing tables remain, plus `batch_control`, `usage_claims`, `legacy_holds`, `claim_events` and `action_idempotency`. Related modules use the `Store` facade.

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
- Saving a draft reserves its usage. `usage_claims.record_key` is globally unique in this store; `claims.py` provides one identity/coverage evaluator for preview, migration and saving. Same-day disjoint details remain independently available. Suspected rebuilt keys, cross-grain coverage and every member of an internal overlapping group are excluded with a reason, never proportionally subtracted or silently merged.
- Pure `analyze` defaults to `all`; HTTP defaults to `available` using a current Store snapshot. Filter before accumulating all rows, daily/model totals and Decimal amounts. `availability` contains `matched_summary`, `available_summary`, `excluded_summary`, `excluded_groups`; `all` rows include `usage_state/usage_reason/usage_owners`. All-view or empty analyses cannot create a claim.
- A batch has one `active_version` and `lifecycle=active|voided|legacy_review`. Only an effective draft can be revised. Submitted records must explicitly withdraw with a reason before editing; reimbursed records require explicit voiding and a new batch. Voiding requires a reason, releases only that owner's claims/holds and is terminal. Ordinary status changes, withdrawal, downloads and restart do not release usage. Historical financial statuses/events and every original ZIP remain inspectable.
- Every reserve/swap/release/resolve runs in `BEGIN IMMEDIATE`, including generation, claim revision, conflicts, immutable package indexing, event and idempotency changes. RLock alone is insufficient across processes. Failed swaps retain the former active version and claims. Preview races return 409; saving never silently shrinks membership or changes the manually entered amount.
- Analyses bind `claim_revision`, `availability_mode`, `target_batch_id`, expected generation and active version. Only a dedicated revision preview may exempt its target batch; a new-batch request cannot borrow that exemption. HTTP persists a normalized request signature and checks replay before transient preview validation, including after cache clearing/restart. Replaying a voided creation or old void action never revives or removes another owner's usage.
- Same-key replay reuses its original version. Unchanged business content within an effective draft may also reuse the version with a new key. Hash only frozen business facts, source/capture/selection/classification and claim; exclude availability, authority counters, UI row state and warning wording so unrelated ledger or copy changes do not create false revisions.
- Existing v1 stores receive a verified SQLite backup under `backups/` before migration. Use a separate read-only source connection for backup and one explicit migration transaction with individual `execute` statements; `executescript` may implicitly commit. Recheck schema inside the write lock. Failed backup/DDL/backfill preserves schema1 and its data.
- Never select MAX(version) to discard old submitted/reimbursed candidates. Unsafe old batches enter `legacy_review`, retaining **all** candidate members in holds. Explicit reasoned void/resolve actions recheck every other claim/hold; do not automatically choose a winner or globally clear shared holds. Corrupt frozen members/packages fail closed without regeneration.
- New revision inserts use `claim_protocol=2`; status updates increment `write_generation` and target an effective active row. Persistent triggers reject the original v0.1.0 INSERT/UPDATE even on an already-open connection. Stop old programs before upgrading; recovering an older program requires the pre-upgrade database and matching immutable materials.
- ZIP has exactly `使用明细.csv`, `每日汇总.csv`, `费用说明.html`, `导出信息.json`. CSV is UTF-8 BOM with formula protection; HTML is escaped. New manifest version2 adds a whitelisted availability summary and `effective_basis`; old packages remain byte-identical. Manifest hashes cover the other three files; stored ZIP hash covers the whole package. Download returns original validated bytes regardless of later lifecycle.
- Shared artifacts omit credentials, full source paths, directory rules, conversation text, IPs and entire SQL. Manual purpose/project/amount-note text is deliberately included. Claim amount is nullable or a nonnegative decimal with at most two fractional digits; nonblank amount requires a note. No automatic subscription allocation or FX.
- HTTP binds only `127.0.0.1`. A random bootstrap credential exchanges for an HttpOnly SameSite cookie named `aha_session_<actual server_port>`; cookies are host-scoped, so a constant name breaks two app instances in one browser. Validate Host, Origin and CSRF for mutations; assets are bundled under a restrictive CSP. Public errors use safe `AppError(code,message,status)` without SQL, paths, tokens or tracebacks.

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
| Other owner or ambiguous usage / internal overlap | exclusion in available preview; `usage_claimed` / `usage_ambiguous` / `usage_internal_overlap` rejects saving |
| Occupancy revision or batch generation changed | `availability_changed` / `stale_batch`, HTTP409; refresh before saving |
| All-view / no available members | HTTP preview: `read_only_analysis` / `empty_analysis`; Store save: `readonly_analysis` / `empty_usage`; no new claim |
| Historical version, voided batch or invalid transition | `inactive_revision` / `batch_voided` / `invalid_transition`, HTTP409 |
| Unsafe legacy candidates | `legacy_review` with all candidate holds; explicit reasoned resolution required |

## 5. Good / Base / Bad Cases

- Good: reserve one project's usage, preview only the remaining members for another claim, void with a reason, and re-use released members; old ZIP hashes remain unchanged after restart.
- Base: missing metadata leaves detail rows unassigned; date-only export still works. Complete daily rollups may be manually assigned but cannot be split proportionally.
- Bad: continue through an overlap warning, trust a stale preview outside the write transaction, release every matching key without owner qualification, select a newer draft and drop old paid members, or recreate a damaged original package. Source/cost/privacy rules above still apply.

## 6. Tests Required

Run `python -m unittest discover -s tests -v`, `python -m ruff check src tests scripts`, `python -m mypy src/aha`, and `python -m compileall -q src/aha` in the isolated environment.

- `test_sources.py`: committed WAL included; original source bytes unchanged; imported SQL cannot execute side effects.
- `test_analysis.py`: all three token semantics, exact decimal sum, Beijing boundaries, mixed grain, project partition and no pagination truncation.
- `test_session_meta.py`: ordinary/zstd bounded headers, missing/conflicting metadata and no conversation payload retention. Explicitly close SQLite connections so Windows can remove fixtures.
- `test_storage.py`: duplicate retention, atomic write/transaction failure, restart without original source, corrupt object and version rejection.
- `test_claims.py` / `test_batches.py`: exact and ambiguous identity, internal groups, effective version, owner-qualified release, immutable packages and old-request replay after reuse.
- `test_claim_concurrency.py`: independent connections and spawned processes competing for usage and migration; same-key retries return one version.
- `test_migrations.py`: actual file backup/WAL, full legacy holds, old cached writer rejection, corrupted members/packages and transaction/commit failure rollback.
- `test_evidence.py`: exact available members and all three sums, manifest2/effective basis, BOM/formula/HTML and privacy; old packages are never rebuilt.
- `test_http.py` / `test_http_cli.py`: stale availability, revision-subject binding, persistent request replay, two servers sharing one CookieJar, original bytes, owned shutdown/restart. Windows launcher PID may differ from the service; verify the descriptor's server and closed port.
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

```python
# Wrong: preview is only a hint; another process can reserve before the insert.
if not store.overlaps(result):
    insert_revision(result)

# Correct: the Store repeats authority/member checks inside its write transaction.
result = analyze(data, metadata, config, start_date, end_date,
                 claim_snapshot=store.claim_snapshot(), availability_mode="available")
result["capture_id"] = capture_id
saved = store.create_batch(result, claim, idempotency_key)
```
