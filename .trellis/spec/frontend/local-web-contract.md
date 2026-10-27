# Local web application contract

## 1. Scope / Trigger

Read before changing `src/aha/web/` or its HTTP payloads. The interface is plain HTML/CSS/JavaScript served by `server.py`, without React, a bundler, remote assets or external services. Keep product text in Simplified Chinese.

## 2. Signatures

`app.js` owns `state`, `api(path, body?)`, `run(label, action)`, `invalidate()`, `prepareBatch(payload, batchId?)`, `saveBatch()` and `download(id, version)`.

| Endpoint | Request / response |
| --- | --- |
| `GET /api/status` | launch CSRF token, date and source availability |
| `POST /api/source/sql` | `{name, content_base64}`; bounded import and new capture |
| `POST /api/source/sqlite` | `{path}`; blank uses the current operating-system user's default |
| `POST /api/session-metadata` | `{capture_id, roots: string[]}` |
| `GET/POST /api/projects` | config / project mutation; names at most 160 characters |
| `POST /api/analysis` | `{capture_id,start_date,end_date,project_id,classification_revision}` |
| `GET /api/analysis/{id}/details` | `kind=detail\|rollup`, `page`, `size` (1–200) |
| `POST /api/batches/preview` | new analysis or frozen revision basis, optional string `batch_id`; overlaps |
| `POST /api/batches` | analysis/claim plus `idempotency_key`; frozen draft version |
| `POST /api/batches/{id}/revisions` | new immutable draft version |
| `POST /api/batches/{id}/revisions/{n}/status` | `{status}`; manual per-version status |
| `GET /api/batches/{id}/revisions/{n}/download` | original ZIP with UTF-8 `Content-Disposition` |
| `POST /api/shutdown` | authenticated application exit |

## 3. Contracts

- `api()` sends same-origin cookies, JSON and `X-AHA-CSRF`; use the authenticated launch origin. It surfaces public messages and invalidates stale analyses. Never put bootstrap credentials into links, logs or exports.
- Source, metadata, directory rules, manual assignment or filters invalidate the previous analysis. Clear old cards/selection and disable create until a fresh analysis exists. A failed import must not leave an old source looking like a successful new import.
- The backend owns calculations. Render exact money strings; use numeric formatting only for counts. Do not recompute totals from the currently displayed page.
- `run()` serializes operations, exposes busy state and restores controls on errors. Maintain the idempotency key for an unchanged pending batch request so a network retry cannot create a second application.
- Optional string fields should be omitted when absent. A new batch preview has no `batch_id`; the server also accepts null for this one field so an already-open older page can continue. Other nonstring values fail validation. Revision previews include the actual stable batch ID.
- Overlap preview may open a confirmation dialog; only its continue action saves. Pending operations bind an analysis ID or a frozen revision and the claim; preparing a different payload uses a new retry key. The backend rejects obsolete analysis IDs. Status labels represent saved manual state; download success never marks a version submitted/reimbursed.
- A successful create saves the batch before fetching its package. If download fails, tell the user the saved original can be downloaded from records. Re-download must use the exact saved revision endpoint.
- Display user/source text via `textContent` and DOM creation. Do not interpolate it into `innerHTML`. Render CSV/report content on the backend with their own escaping rules.
- Purpose and amount-note limits are 4000 characters. Amount may be blank or zero; a filled amount requires its note and CNY/USD. Keep reference USD cost and requested amount visibly separate.
- The default source is platform-specific. Windows logs may contain Linux cwd paths; allow explicit text bindings as well as discovered-directory choices.
- Closing the browser tab leaves the local service running. The exit button calls authenticated shutdown; do not erase projects, captures or saved packages on exit.

## 4. Validation & Error Matrix

| Condition | Interface behavior |
| --- | --- |
| No capture or no fresh analysis | clear empty state / disabled create |
| Empty date range result | zero matched records and explicit coverage explanation |
| Metadata missing/conflicting | coverage message, unassigned records remain usable |
| Invalid amount or missing amount note | actionable validation, no batch created |
| HTTP 409 stale classification/analysis | clear preview and request update |
| Network or download interruption | visible error; preserve saved batch and retry identity |
| Overlap warning | show batch/version/status and allow review or continue |
| Unknown source schema | show source error; no silent fallback |

## 5. Good / Base / Bad Cases

- Good: user binds directories, refreshes preview, checks all matching records, creates one draft, downloads and later re-downloads original bytes.
- Base: date-only export without any bound projects, blank requested amount, missing metadata, or historical daily rollups.
- Bad: rely on null being accepted by every string validator, export only the visible 50 rows, leave a previous source's result visible after failed import, or equate a matched directory with independently verified business attribution.

## 6. Tests Required

Run `node --check src/aha/web/app.js` using an available local Node runtime and the full backend HTTP tests. Exercise the actual browser after cross-layer changes; a direct Store call does not validate frontend payload shapes.

The browser release path covers SQL import, date/project selection, multiple directory bindings, current/history capture selection, metadata refresh, manual assignment, initial batch creation, original re-download, overlap continuation, new version, manual status, restart, exit and port closure. Inspect Chinese text, narrow viewport, errors and empty states. Keep personal screenshots and exported evidence outside Git.

## 7. Wrong vs Correct

```javascript
// Wrong: a new batch sends JSON null to a string field.
await api("/api/batches/preview", {...request, batch_id: batchId});

// Correct: absence and a real existing ID are distinct requests.
const preview = {...request};
if (batchId) preview.batch_id = batchId;
await api("/api/batches/preview", preview);
```
