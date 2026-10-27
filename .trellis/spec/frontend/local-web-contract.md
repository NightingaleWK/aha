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
| `POST /api/analysis` | original filters plus `availability_mode=available\|all`; new-claim/read-only subject |
| `POST /api/batches/{id}/analysis` | revision filters, `base_version`, `expected_generation`; effective draft subject |
| `GET /api/analysis/{id}/details` | `kind=detail\|rollup`, `page`, `size` (1–200) |
| `POST /api/batches/preview` | new analysis or frozen effective revision basis; `conflicts/overlaps/blocking`, never continue through a block |
| `POST /api/batches` | analysis/claim plus `idempotency_key`; frozen draft version |
| `POST /api/batches/{id}/revisions` | `base_version,expected_generation,claim,idempotency_key,analysis_id?`; atomic effective draft replacement |
| `POST /api/batches/{id}/revisions/{n}/status` | `{status,expected_generation}`; effective-version transitions only |
| `POST /api/batches/{id}/withdraw` / `void` | `{reason,expected_generation,idempotency_key}`; withdraw retains claims, void releases |
| `POST /api/batches/{id}/resolve` | lifecycle fields plus `selected_version`; explicit legacy choice |
| `GET /api/batches/{id}/revisions/{n}/download` | original ZIP with UTF-8 `Content-Disposition` |
| `POST /api/shutdown` | authenticated application exit |

## 3. Contracts

- `api()` sends same-origin cookies, JSON and `X-AHA-CSRF`; use the authenticated launch origin. Cookies are named per server port, managed by the browser. Never hardcode a cookie name or put bootstrap credentials into links, logs or exports.
- Source, metadata, directory rules, manual assignment, filters and occupancy changes invalidate previews. Clear old cards/selection and disable create until fresh. For `analysis_expired/classification_changed/availability_changed/usage_claimed`, also clear an open **current** revision's `state.revision.analysis`, replace its preview with an update instruction and disable save. Frozen revision retries keep their basis. Failed imports cannot present an old source as a new success.
- The backend owns calculations. Render exact money strings; use numeric formatting only for counts. Never calculate from the visible page. `analysis.availability` has matched/available/excluded summaries and grouped reasons/owners; `all` rows show `usage_state/usage_reason/usage_owners`. New-claim mode defaults to available; all-view and zero available members cannot save.
- `run()` serializes operations, exposes busy state and restores controls on errors. Maintain the idempotency key for an unchanged pending batch request so a network retry cannot create a second application.
- Optional string fields should be omitted when absent. A new batch preview has no `batch_id`; the server also accepts null for this one field so an already-open older page can continue. Other nonstring values fail validation. Revision previews include the actual stable batch ID.
- A blocking conflict provides existing-record navigation and refresh, without a continue action. Pending requests bind the actual analysis or effective frozen revision and claim; a different payload gets a new retry key. Successful requests can be replayed from persistent signatures after preview expiry/restart. Download success never marks a record submitted/reimbursed.
- Render actions from `is_effective/lifecycle/generation/can_*`. Historical and voided revisions remain downloadable. Only effective drafts edit; submitted records explicitly withdraw with a reason; reimbursed corrections explicitly void and start a new record. Void requires a reason and is terminal. Legacy candidates need explicit reasoned confirmation; never visually label a latest candidate as automatically valid.
- `revision-basis=current` uses a dedicated target-batch analysis, allowing that owner's usage. Its local capture/project/date controls have their own preview; filter changes disable save until updated. A new-claim analysis cannot borrow this exemption, and a global available preview cannot silently become revision evidence.
- A successful create saves the batch before fetching its package. If download fails, tell the user the saved original can be downloaded from records. Re-download must use the exact saved revision endpoint.
- Display user/source text via `textContent` and DOM creation. Do not interpolate it into `innerHTML`. Render CSV/report content on the backend with their own escaping rules.
- Purpose and amount-note limits are 4000 characters. Amount may be blank or zero; a filled amount requires its note and CNY/USD. Keep reference USD cost and requested amount visibly separate.
- After a successful new record, clear its purpose/amount/note (currency may persist). Changed scope prompts review instead of prorating or copying an old amount into the next application.
- The default source is platform-specific. Windows logs may contain Linux cwd paths; allow explicit text bindings as well as discovered-directory choices.
- Closing the browser tab leaves the local service running. The exit button calls authenticated shutdown; do not erase projects, captures or saved packages on exit.

Typography uses a 16px body/input base, 15px table/button text, 14px labels/headers and at least 13px secondary text. Controls/primary buttons are about44px high; smaller buttons reduce padding, not readable type. Use system fonts, normal Chinese tracking, tabular numeric alignment, wrapping and container scrolling. Responsive layouts do not shrink required text to9–11px.

Keep the teal/nav/card identity. Product titles are direct (`用量与费用/项目管理/报销记录`), actions describe results (`保存并下载/修改报销记录/下载材料`). Put data/pricing explanations in optional help. Do not add slogans, assistant narration, repeated disclaimers or internal protocol/epoch details to user flows. The main order is filters → metrics → exclusions when needed → claim form → optional long preview. Saving must not be buried behind hundreds of rows. Success is a short floating notice; actionable errors remain visible, including inside modals.

## 4. Validation & Error Matrix

| Condition | Interface behavior |
| --- | --- |
| No capture or no fresh analysis | clear empty state / disabled create |
| Zero available / all matched members occupied | no new record, show excluded owners and useful next action; not a claim of zero consumption |
| Metadata missing/conflicting | coverage message, unassigned records remain usable |
| Invalid amount or missing amount note | actionable validation, no batch created |
| Preview expiry (`analysis_expired`, `classification_changed`, `availability_changed`, `usage_claimed`) | clear the affected main/current-revision preview, disable its save and request update |
| Batch authority changed (`stale_batch`, `inactive_revision`, `batch_voided`) | show the failed operation's error; refresh records and reopen the current record before retrying |
| Network or download interruption | visible error; preserve saved batch and retry identity |
| Blocking overlap or legacy ambiguity | show reason and existing record; no bypass |
| Missing withdrawal/void reason | keep modal open and explain required field |
| Unknown source schema | show source error; no silent fallback |

## 5. Good / Base / Bad Cases

- Good: reserve one project's members, see only the remainder for another record, revise the same draft, void with a reason and still download the original bytes.
- Base: date-only export without any bound projects, blank requested amount, missing metadata, or historical daily rollups.
- Bad: leave an expired modal preview enabled, use a new-record preview as a self-exempt revision, shrink text to fit columns, truncate CNY/USD, leave an old error over a successful result, or describe source metadata as proven business attribution.

## 6. Tests Required

Run `node --check src/aha/web/app.js` using an available local Node runtime and the full backend HTTP tests. Exercise the actual browser after cross-layer changes; a direct Store call does not validate frontend payload shapes.

The browser release path covers SQL import, project/date/history, metadata, reservation→remaining preview→blocked stale save→targeted revision→withdraw→void→reuse→old-request replay→restart/original download→exit. Include legacy conflicting version resolution and a real stale **open revision modal**. Check actual computed type, viewport screenshots at1440/1366/1280 and430/375, long names/amounts, complete currency labels, empty/error states and modal feedback. Inspect physical rendering; do not replace browser checks with CSS-string unit tests or confuse device pixel density with browser zoom. Keep personal evidence outside Git.

## 7. Wrong vs Correct

```javascript
// Wrong: only invalidate the main page while a current revision can still save.
invalidate();

// Correct: the current modal also loses its stale authority.
invalidate("用量已变化，请更新预览");
if (state.revision && $("revision-basis").value === "current") {
  state.revision.analysis = null;
  $("revision-preview").replaceChildren(node("p", "", "用量已变化，请点击“更新用量”。"));
  syncActions();
}
```
