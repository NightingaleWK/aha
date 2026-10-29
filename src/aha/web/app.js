"use strict";

const $ = (id) => document.getElementById(id);
const state = {
  csrf: "", today: "", now: "", ledger: null, sync: null, syncBusy: false, reconciliations: [],
  config: {revision: 0, projects: []}, analysis: null, tab: "daily", page: 1,
  rows: [], total: 0, cursor: null, nextCursor: null, cursors: [null], selected: new Map(), batches: [], batch: null,
  busy: false, pendingBatch: null, revision: null, lifecycle: null, noticeTimer: null, stopped: false,
  filterGeneration: 0, analysisRequest: 0,
};
const labels = {draft: "草稿", submitted: "已提交", reimbursed: "已报销", voided: "已作废"};
const origins = {manual: "手动分配", directory_rule: "目录匹配", unassigned: "未归属"};
const counts = (value) => new Intl.NumberFormat("zh-CN").format(value ?? 0);
const money = (value) => String(value ?? "0").replace(/(\.\d*?[1-9])0+$|\.0+$/, "$1");
const lines = (value) => value.split(/\r?\n/).map((part) => part.trim()).filter(Boolean);
const timeContext = () => ({now: state.now, coverage: state.ledger?.coverage});
const timeRange = AhaTimeRange.create($("time-range-control"), {
  id: "usage-range", context: timeContext, onApply: applyTimeRange,
});
const revisionTimeRange = AhaTimeRange.create($("revision-range-control"), {
  id: "revision-range", label: "修订时间范围", context: timeContext, onApply: applyRevisionTimeRange,
});

function node(tag, className, text) {
  const item = document.createElement(tag);
  if (className) item.className = className;
  if (text !== undefined && text !== null) item.textContent = String(text);
  return item;
}
function hasUsage(summary) {
  try { return BigInt(summary?.record_count ?? 0) > 0n; } catch { return false; }
}
function dateTime(value) {
  if (!value) return "时间未提供";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit",
  }).format(date);
}
function clearFeedback() {
  clearTimeout(state.noticeTimer);
  state.noticeTimer = null;
  document.querySelectorAll(".dialog-message").forEach((item) => item.remove());
  const notice = $("notice");
  notice.hidden = true;
  notice.replaceChildren();
  notice.className = "notice";
}
function notify(message, kind = "success") {
  clearFeedback();
  if (kind === "error") {
    const dialog = document.querySelector("dialog[open]");
    if (dialog) {
      const alert = node("p", "dialog-message", message); alert.setAttribute("role", "alert");
      const heading = dialog.querySelector(".dialog-heading");
      heading.after(alert);
    }
  }
  const notice = $("notice");
  notice.replaceChildren(node("span", "", message));
  notice.className = `notice ${kind}`;
  notice.hidden = false;
  if (kind === "success") state.noticeTimer = setTimeout(() => { notice.hidden = true; }, 4500);
}
async function api(path, body, isCurrent = () => true) {
  const options = {credentials: "same-origin", cache: "no-store", headers: {}};
  if (body !== undefined) {
    options.method = "POST";
    options.headers["Content-Type"] = "application/json";
    options.headers["X-AHA-CSRF"] = state.csrf;
    options.body = JSON.stringify(body);
  }
  let response;
  try { response = await fetch(path, options); }
  catch { throw new Error("连接中断。请确认程序仍在运行，必要时重新启动。"); }
  let result;
  try { result = await response.json(); }
  catch { throw new Error("程序返回了无法读取的结果，请重新打开页面。"); }
  if (!response.ok) {
    const error = new Error(result.message || "操作未完成，请重试。");
    error.code = result.code;
    if (isCurrent() && ["analysis_expired", "classification_changed", "availability_changed", "usage_claimed", "data_changed", "stale_analysis", "ledger_changed"].includes(error.code)) {
      invalidate("用量已变化，请更新预览");
      error.invalidated = true;
    }
    throw error;
  }
  return result;
}
async function run(label, action, {rethrow = false} = {}) {
  if (state.busy || state.stopped) return;
  clearFeedback();
  state.busy = true;
  $("busy-label").textContent = label;
  $("busy").hidden = false;
  const focused = document.activeElement;
  const controls = [...document.querySelectorAll("button:not([data-sync-control]),input,textarea,select")];
  const previous = controls.map((control) => control.disabled);
  controls.forEach((control) => { control.disabled = true; });
  AhaForms.closeAll(); AhaForms.sync();
  try { return await action(); }
  catch (error) {
    notify(error.message || "操作未完成，请重试。", "error");
    if (rethrow) throw error;
  }
  finally {
    controls.forEach((control, index) => { control.disabled = previous[index]; });
    state.busy = false;
    $("busy").hidden = true;
    syncActions();
    if (document.activeElement === document.body && focused?.isConnected && !focused.disabled && focused.getClientRects().length) focused.focus({preventScroll: true});
  }
}
function syncActions() {
  if (state.stopped) {
    document.querySelectorAll("button,input,textarea,select").forEach((control) => { control.disabled = true; });
    AhaForms.sync(); timeRange.setDisabled(true); revisionTimeRange.setDisabled(true);
    return;
  }
  document.querySelectorAll("[data-sync-control]").forEach((control) => { control.disabled = state.syncBusy; });
  $("analyze").disabled = state.busy || !state.ledger;
  $("view-details").disabled = state.busy || !state.analysis;
  $("create-batch").disabled = state.busy || !state.analysis || state.analysis.availability_mode !== "available" || Boolean(state.analysis.target_batch_id) || !hasUsage(state.analysis.summary);
  $("refresh-availability").disabled = state.busy || !state.ledger;
  $("save-revision").disabled = state.busy || !state.revision || ($("revision-basis").value === "current" && (!state.revision.analysis || !hasUsage(state.revision.analysis.summary)));
  $("refresh-metadata").disabled = state.busy || !state.ledger;
  $("scan-metadata").disabled = state.busy || !state.ledger;
  $("assign").disabled = state.busy || state.selected.size === 0;
  $("prev-page").disabled = state.busy || state.page <= 1;
  $("next-page").disabled = state.busy || !state.nextCursor;
  $("revision-analyze").disabled = state.busy || !state.revision || !state.ledger;
  timeRange.setDisabled(state.busy || !state.now);
  revisionTimeRange.setDisabled(state.busy || !state.now || !state.revision || $("revision-basis").value !== "current");
  AhaForms.sync();
}
function page(name) {
  const titles = {usage: "用量与费用", projects: "项目管理", batches: "报销记录"};
  document.querySelectorAll(".page").forEach((item) => { item.hidden = item.id !== `page-${name}`; });
  document.querySelectorAll("[data-page]").forEach((item) => {
    item.classList.toggle("active", item.dataset.page === name);
    if (item.dataset.page === name) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  });
  $("breadcrumb").textContent = titles[name];
}
function empty(target, title, description) {
  const wrap = node("div", "empty-state");
  wrap.append(node("span", "empty-icon", "▤"), node("h3", "", title), node("p", "", description));
  target.replaceChildren(wrap);
}
function invalidate(message = "条件已更改，请更新预览") {
  state.filterGeneration += 1;
  if (state.analysis && ["claim-purpose", "claim-amount", "claim-note"].some((id) => $(id).value.trim())) {
    $("claim-explanation").textContent = "用量范围已变化，请核对用途和金额后保存。";
  }
  state.analysis = null;
  state.pendingBatch = null;
  state.selected.clear();
  state.rows = [];
  state.page = 1; state.cursor = null; state.nextCursor = null; state.cursors = [null];
  invalidateRevision();
  timeRange.markPending();
  $("reconciliation-note").hidden = true;
  $("time-coverage-note").hidden = true;
  ["metric-cost", "metric-count", "metric-tokens", "metric-unassigned"].forEach((id) => { $(id).textContent = "—"; });
  $("availability-panel").hidden = true;
  $("token-strip").hidden = true;
  $("coverage-note").hidden = true;
  $("analysis-warnings").replaceChildren();
  $("pagination").hidden = true;
  $("assignment-bar").hidden = true;
  $("filter-status").textContent = message;
  $("preview-caption").textContent = "选择条件后更新预览。";
  empty($("preview-table"), state.ledger ? "请更新预览" : "正在读取本地资料",
    state.ledger ? "按所选项目和时间查看本地台账。" : "本地资料加载后即可查询。");
  syncActions();
}
function invalidateRevision(message = "用量已变化，请点击“更新用量”。") {
  if (!state.revision || $("revision-basis").value !== "current") return;
  state.revision.analysis = null;
  state.revision.filterGeneration += 1;
  if (state.pendingBatch?.batchId === state.revision.batchId) state.pendingBatch = null;
  revisionTimeRange.markPending();
  $("revision-preview").replaceChildren(node("p", "", message));
}
async function applyTimeRange(intent) {
  if (state.busy || state.stopped) throw new Error("请等待当前操作完成后重试。");
  timeRange.setIntent(intent);
  await run("正在更新预览…", analyze, {rethrow: true});
}
async function applyRevisionTimeRange(intent) {
  if (state.busy || !state.revision || $("revision-basis").value !== "current") throw new Error("请重新打开当前报销记录后选择用量。");
  revisionTimeRange.setIntent(intent);
  await run("正在更新用量…", prepareRevisionPreview, {rethrow: true});
}
function rangeDescription(result) {
  return AhaTimeRange.describe(AhaTimeRange.fromAnalysis(result)) || `${result.start_date} 至 ${result.end_date}`;
}
function renderTimeCoverage(target, result, onWholeDays = null, frozen = false) {
  target.replaceChildren();
  const coverage = result.time_coverage;
  target.hidden = coverage?.complete !== false;
  if (target.hidden) return;
  const days = (coverage.omitted_days || []).join("、");
  target.append(node("strong", "", "统计不完整"), node("p", "", `${days ? `${days} 的` : "部分日期的"}${counts(coverage.omitted_rollup_count)} 条历史日汇总没有发生时间，无法按此时间范围拆分，未计入当前统计。`),
    node("p", "field-help", frozen ? "此记录沿用已确定的冻结用量，材料保留此说明。" : "当前合计仅含已确定的用量；有可用用量时仍可保存，材料将保留此说明。"));
  if (onWholeDays) target.append(actionButton("改查整天", onWholeDays, "button small"));
}
async function refreshLedger() {
  state.ledger = await api("/api/ledger");
  renderSource();
}
function renderSource() {
  const ledger = state.ledger;
  const amount = ledger?.counts || {};
  const coverage = ledger?.coverage || {};
  const needsReview = state.sync?.status === "needs_review" || state.sync?.result?.status === "needs_review";
  const last = ledger?.last_successful_sync_at ||
    (["completed", "succeeded", "success"].includes(ledger?.last_sync?.status) ? ledger.last_sync.finished_at || ledger.last_sync.completed_at : null);
  $("source-name").textContent = "本地用量台账";
  $("source-mode").textContent = state.syncBusy ? "同步中" : needsReview ? "需要核对" : last ? "已同步" : "本地资料";
  const period = coverage.start_date ? ` · ${coverage.start_date} 至 ${coverage.end_date}` : "";
  $("source-description").textContent = ledger
    ? `${counts(amount.detail_count)} 条明细 · ${counts(amount.rollup_count)} 条来源日汇总${period} · ${last ? `上次成功 ${dateTime(last)}` : "尚无成功同步"}${needsReview ? " · 本次来源需要核对" : ""}`
    : "正在读取本地资料。";
  $("load-default").textContent = state.syncBusy ? "正在同步…" : "立即同步";
  const failed = state.sync?.status === "failed";
  $("sync-error").hidden = !failed;
  $("sync-error").textContent = failed ? state.sync.message || "同步未完成，原本地数据仍可查询。" : "";
  $("reconciliation-count").textContent = counts(amount.pending_count || state.reconciliations.length);
  renderDirectories(); syncActions();
}
async function refreshReconciliations() {
  state.reconciliations = (await api("/api/reconciliations")).cases;
  $("reconciliation-count").textContent = counts(state.reconciliations.length);
}
async function watchSync(job) {
  state.sync = job; state.syncBusy = job.status === "running";
  renderSource();
  while (!state.stopped && state.sync.status === "running") {
    await new Promise((resolve) => setTimeout(resolve, 450));
    if (state.stopped) return;
    state.sync = await api(`/api/sync/${encodeURIComponent(job.id)}`);
    renderSource();
  }
  state.syncBusy = false;
  if (state.stopped) return;
  await Promise.all([refreshLedger(), refreshProjects(), refreshReconciliations()]);
  if (state.sync.status === "failed") { renderSource(); return; }
  invalidate("同步已完成，请更新预览");
  if (!state.busy) await run("正在更新本地预览…", analyze);
  renderSource();
  const needsReview = state.sync.status === "needs_review" || state.sync.result?.status === "needs_review";
  notify(needsReview
    ? "本次来源需要核对，已保留本地用量。请查看“数据核对”。"
    : "同步已完成。后续查询使用本地台账。", needsReview ? "info" : "success");
}
async function loadSource(path = "/api/sync", body = {}) {
  if (state.syncBusy || state.stopped) return;
  state.syncBusy = true; syncActions();
  try {
    const job = await api(path, {...body, idempotency_key: crypto.randomUUID()});
    $("source-dialog").close();
    await watchSync(job);
  } catch (error) {
    state.sync = {status: "failed", message: error.message || "同步未完成，原本地数据仍可查询。"};
    notify(state.sync.message, "error");
  } finally {
    state.syncBusy = false; renderSource();
  }
}
async function importSQL(file) {
  if (!file) return;
  if (file.size > 128 * 1024 * 1024) throw new Error("SQL 文件不能超过 128 MiB。");
  const encoded = await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1]);
    reader.onerror = () => reject(new Error("无法读取此文件，请重新选择。"));
    reader.readAsDataURL(file);
  });
  await loadSource("/api/source/sql", {name: file.name, content_base64: encoded});
}
async function refreshProjects() {
  state.config = await api("/api/projects");
  const previous = $("project-select").value;
  const select = $("project-select");
  const all = node("option", "", "全部项目（含未归属）"); all.value = "all";
  const unassigned = node("option", "", "未归属"); unassigned.value = "unassigned";
  select.replaceChildren(all, unassigned);
  const assignment = $("assignment-project");
  const clear = node("option", "", "清除人工指定"); clear.value = "";
  assignment.replaceChildren(clear);
  for (const project of state.config.projects) {
    const option = node("option", "", project.name); option.value = project.id;
    select.append(option);
    assignment.append(option.cloneNode(true));
  }
  select.value = previous;
  if (select.selectedIndex < 0) select.value = "all";
  if (state.revision && $("revision-dialog").open) {
    const revisionProject = $("revision-project"); const selectedProject = revisionProject.value;
    revisionProject.replaceChildren(...[...select.options].map((option) => option.cloneNode(true)));
    revisionProject.value = selectedProject;
    if (revisionProject.selectedIndex < 0) revisionProject.value = "all";
  }
  AhaForms.sync();
  $("project-nav-count").textContent = counts(state.config.projects.length);
  renderProjects();
}
function renderProjects() {
  const target = $("project-list");
  if (!state.config.projects.length) {
    empty(target, "暂无项目", "新建项目并选择它的工作目录。");
    return;
  }
  target.replaceChildren();
  for (const project of state.config.projects) {
    const card = node("article", "project-card");
    const heading = node("div", "project-card-heading");
    const edit = node("button", "button small", "编辑");
    edit.addEventListener("click", () => openProject(project));
    heading.append(node("h2", "", project.name), edit);
    card.append(heading, node("p", "", project.description || "未填写项目说明"));
    const dirs = node("ul");
    for (const directory of project.directories) dirs.append(node("li", "", directory));
    card.append(dirs, node("div", "project-card-footer", `${counts(project.directories.length)} 个工作目录（包含子目录）`));
    target.append(card);
  }
}
function renderDirectories() {
  const directories = state.ledger?.directories || [];
  const coverage = state.ledger?.metadata_coverage;
  $("directory-summary").textContent = coverage
    ? `已识别 ${counts(coverage.matched_sessions)} / ${counts(coverage.total_sessions)} 个会话，共 ${counts(directories.length)} 个工作目录。`
    : "加载用量后显示工作目录。";
  const target = $("directory-list"); target.replaceChildren();
  for (const directory of directories) {
    const row = node("div", "directory-row");
    row.append(node("code", "", directory.path), node("span", "", `${counts(directory.session_count)} 个会话${directory.detail_count === undefined ? "" : ` · ${counts(directory.detail_count)} 条明细`}`));
    target.append(row);
  }
  const unresolved = state.ledger?.unresolved_sessions || [];
  if (unresolved.length) {
    const conflicts = unresolved.filter((session) => session.status === "conflict").length;
    target.append(node("p", "field-help", `${counts(unresolved.length)} 个会话的目录待确认，其中 ${counts(conflicts)} 个存在冲突。可在明细中手动分配项目。`));
  }
}
function openProject(project = null) {
  clearFeedback();
  $("edit-project-id").value = project?.id || "";
  $("project-dialog-title").textContent = project ? "编辑项目" : "新建项目";
  $("edit-project-name").value = project?.name || "";
  $("edit-project-description").value = project?.description || "";
  const selected = new Set(project?.directories || []);
  const known = new Set();
  const target = $("project-candidates"); target.replaceChildren();
  for (const candidate of state.ledger?.directories || []) {
    known.add(candidate.path);
    const label = node("label", "candidate-item");
    const check = node("input"); check.type = "checkbox"; check.value = candidate.path;
    check.checked = selected.has(candidate.path);
    const text = node("span");
    text.append(node("code", "", candidate.path), node("small", "", `${counts(candidate.session_count)} 个会话${candidate.detail_count === undefined ? "" : ` · ${counts(candidate.detail_count)} 条明细`}`));
    label.append(check, text); target.append(label);
  }
  $("edit-project-directories").value = [...selected].filter((directory) => !known.has(directory)).join("\n");
  $("project-dialog").showModal();
}
async function saveProject() {
  const selected = [...$("project-candidates").querySelectorAll("input:checked")].map((input) => input.value);
  const id = $("edit-project-id").value;
  await api(id ? `/api/projects/${encodeURIComponent(id)}` : "/api/projects", {
    name: $("edit-project-name").value, description: $("edit-project-description").value,
    directories: [...new Set([...selected, ...lines($("edit-project-directories").value)])],
  });
  await refreshProjects(); invalidate("项目规则已更新，请重新预览");
  $("project-dialog").close(); notify("已保存项目。");
}
async function analyze() {
  if (!state.ledger) throw new Error("请先加载本地资料。");
  invalidate("正在更新预览…");
  const generation = state.filterGeneration; const request = ++state.analysisRequest;
  const isCurrent = () => generation === state.filterGeneration && request === state.analysisRequest && !state.stopped;
  let result;
  try {
    result = await api("/api/analysis", {
      classification_revision: state.config.revision, time_range: timeRange.getIntent(),
      project_id: $("project-select").value, availability_mode: $("availability-mode").value,
    }, isCurrent);
  } catch (error) { if (!isCurrent() && !error.invalidated) return; throw error; }
  if (!isCurrent()) return;
  state.analysis = result; state.page = 1; state.cursor = null; state.nextCursor = null; state.cursors = [null]; state.selected.clear();
  if (result.time_range?.resolved_at) state.now = result.time_range.resolved_at;
  timeRange.setResolved(AhaTimeRange.fromAnalysis(result));
  renderAvailability(result);
  renderTimeCoverage($("time-coverage-note"), result, () => { void applyTimeRange(AhaTimeRange.wholeDays(result)).catch(() => {}); });
  const summary = result.summary;
  const availableOnly = result.availability_mode === "available";
  const pending = result.pending_count || 0;
  $("reconciliation-note").hidden = !pending;
  $("reconciliation-note").textContent = pending ? `有 ${counts(pending)} 项用量待核对，当前合计仅含已核实部分。可点击“数据核对”查看原始依据。` : "";
  $("metric-cost-label").textContent = availableOnly ? "可用参考成本" : "期间参考成本";
  $("metric-count-label").textContent = availableOnly ? "可用用量" : "用量记录数";
  $("metric-token-label").textContent = availableOnly ? "可用 Token" : "总 Token";
  const omittedOnly = result.time_coverage?.complete === false && !hasUsage(summary);
  $("metric-cost").textContent = omittedOnly ? "—" : money(summary.total_cost_usd);
  $("metric-count").textContent = omittedOnly ? "—" : counts(summary.record_count);
  $("metric-count-note").textContent = omittedOnly ? "所选时段缺少可确定的用量，请查看完整性说明" : `${counts(summary.detail_count)} 条明细 + ${counts(summary.rollup_record_count)} 条历史代表记录`;
  $("metric-tokens").textContent = omittedOnly ? "—" : counts(summary.total_tokens);
  $("metric-unassigned").textContent = counts(result.unassigned_count);
  $("token-input").textContent = counts(summary.fresh_input_tokens);
  $("token-output").textContent = counts(summary.output_tokens);
  $("token-read").textContent = counts(summary.cache_read_tokens);
  $("token-write").textContent = counts(summary.cache_creation_tokens);
  $("token-strip").hidden = omittedOnly;
  const coverage = result.metadata_coverage || state.ledger.metadata_coverage || {matched_sessions: 0, total_sessions: 0};
  $("coverage-note").textContent = `已识别 ${counts(coverage.matched_sessions)} / ${counts(coverage.total_sessions)} 个会话的工作目录。项目按目录设置或手动分配。`;
  $("coverage-note").hidden = false;
  $("analysis-warnings").replaceChildren();
  for (const warning of result.warnings || []) {
    $("analysis-warnings").append(node("div", "warning", typeof warning === "string" ? warning : warning.message || warning.code));
  }
  $("filter-status").textContent = "预览已更新";
  $("preview-caption").textContent = `${result.project_name} · ${rangeDescription(result)}（北京时间）`;
  await renderPreview(); syncActions();
}
function table(columns, rows, selectable = false) {
  const item = node("table"); const head = node("thead"); const tr = node("tr");
  if (selectable) {
    const cell = node("th", "table-check"); const check = node("input");
    check.type = "checkbox"; check.setAttribute("aria-label", "选择当前页全部记录");
    check.checked = rows.length > 0 && rows.every((row) => state.selected.has(row.record_key));
    check.addEventListener("change", () => {
      rows.forEach((row) => check.checked ? state.selected.set(row.record_key, row) : state.selected.delete(row.record_key));
      renderRowTable(); renderSelection();
    });
    cell.append(check); tr.append(cell);
  }
  for (const column of columns) tr.append(node("th", column.numeric ? "numeric" : "", column.title));
  head.append(tr); item.append(head); const body = node("tbody");
  for (const row of rows) {
    const line = node("tr", state.selected.has(row.record_key) ? "selected-row" : "");
    if (selectable) {
      const cell = node("td", "table-check"); const check = node("input");
      check.type = "checkbox"; check.checked = state.selected.has(row.record_key);
      check.setAttribute("aria-label", `选择 ${row.time || row.date} ${row.model} 记录`);
      check.addEventListener("change", () => {
        check.checked ? state.selected.set(row.record_key, row) : state.selected.delete(row.record_key);
        line.classList.toggle("selected-row", check.checked); renderSelection();
      }); cell.append(check); line.append(cell);
    }
    for (const column of columns) {
      const cell = node("td", `${column.numeric ? "numeric" : ""}${column.wrap ? " wrap" : ""}`);
      const value = column.value(row);
      if (value instanceof Node) cell.append(value); else cell.textContent = value ?? "—";
      line.append(cell);
    }
    body.append(line);
  }
  item.append(body); return item;
}
function costCell(row) {
  const text = node("span", "", money(row.total_cost_usd));
  if (row.pricing_status === "unpriced") text.append(node("span", "subline", "未计价"));
  if (row.pricing_status === "missing_basis") text.append(node("span", "subline", "沿用历史金额"));
  return text;
}
function projectCell(row) {
  const text = node("span", "", row.project_name || "未归属");
  text.append(node("span", "subline", origins[row.assignment_origin] || row.assignment_origin || "未归属"));
  return text;
}
function aggregateColumns(kind) {
  const result = kind === "daily" ? [
    {title: "日期", value: (row) => row.date}, {title: "项目", value: (row) => row.project_name, wrap: true},
  ] : [];
  return [...result, {title: "模型", value: (row) => row.model},
    {title: "明细 / 历史记录", numeric: true, value: (row) => `${counts(row.detail_count)} / ${counts(row.rollup_record_count)}`},
    {title: "输入", numeric: true, value: (row) => counts(row.fresh_input_tokens)},
    {title: "输出", numeric: true, value: (row) => counts(row.output_tokens)},
    {title: "总 Token", numeric: true, value: (row) => counts(row.total_tokens)},
    {title: "参考成本 USD", numeric: true, value: costCell}];
}
function renderRowTable() {
  const rollup = state.tab === "rollups";
  const columns = [
    {title: rollup ? "来源日期" : "北京时间", value: (row) => rollup ? row.date : row.time?.replace("T", " ").replace("+08:00", ""), wrap: false},
    {title: "项目", value: projectCell, wrap: true},
    ...(state.analysis?.availability_mode === "all" ? [{title: "使用状态", value: usageCell, wrap: true}] : []),
    {title: "模型", value: (row) => row.model},
    ...(rollup ? [{title: "代表记录数", numeric: true, value: (row) => counts(row.request_count)}] : []),
    {title: "输入", numeric: true, value: (row) => counts(row.fresh_input_tokens)},
    {title: "输出", numeric: true, value: (row) => counts(row.output_tokens)},
    {title: "缓存读取", numeric: true, value: (row) => counts(row.cache_read_tokens)},
    {title: "缓存写入", numeric: true, value: (row) => counts(row.cache_creation_tokens)},
    {title: "参考成本 USD", numeric: true, value: costCell},
  ];
  $("preview-table").replaceChildren(table(columns, state.rows, true));
}
function renderSelection() {
  $("assignment-bar").hidden = !state.selected.size;
  $("selection-count").textContent = `已选 ${counts(state.selected.size)} 条${state.tab === "rollups" ? "完整日汇总" : "明细"}`;
  $("session-scope-label").hidden = state.tab !== "details";
  syncActions();
}
async function renderPreview() {
  $("assignment-bar").hidden = true; $("pagination").hidden = true;
  if (!state.analysis) return;
  const kind = {details: "detail", rollups: "rollup", daily: "daily", models: "models"}[state.tab];
  const params = new URLSearchParams({kind, size: "50"});
  if (state.cursor) params.set("cursor", state.cursor);
  const currentId = state.analysis.analysis_id;
  const tab = state.tab; const cursor = state.cursor; const generation = state.filterGeneration;
  const isCurrent = () => state.analysis?.analysis_id === currentId && state.tab === tab
    && state.cursor === cursor && state.filterGeneration === generation && !state.stopped;
  let result;
  try {
    result = await api(`/api/analysis/${encodeURIComponent(currentId)}/details?${params}`, undefined, isCurrent);
  } catch (error) { if (!isCurrent() && !error.invalidated) return; throw error; }
  if (!isCurrent()) return;
  state.rows = result.rows; state.total = result.total; state.nextCursor = result.next_cursor || null;
  if (!state.rows.length) empty($("preview-table"), state.analysis.time_coverage?.complete === false ? "当前时段没有可确定的用量" : "当前筛选没有用量",
    state.analysis.time_coverage?.complete === false ? "历史日汇总无法按此时段拆分，可在上方选择“改查整天”。" : "调整项目、时间或查看待核对依据。");
  else if (["daily", "models"].includes(state.tab)) $("preview-table").replaceChildren(table(aggregateColumns(state.tab), state.rows));
  else renderRowTable();
  $("page-label").textContent = result.total === null || result.total === undefined
    ? `本页 ${counts(state.rows.length)} 行 · 第 ${state.page} 页`
    : `共 ${counts(result.total)} 行 · 第 ${state.page} 页`;
  $("pagination").hidden = !state.rows.length;
  if (["details", "rollups"].includes(state.tab)) renderSelection();
  syncActions();
}
async function applyAssignment() {
  const selected = [...state.selected.values()];
  const sessionScope = state.tab === "details" && $("session-scope").checked;
  const body = {kind: state.tab === "rollups" ? "rollup" : "detail",
    project_id: $("assignment-project").value || null};
  if (sessionScope) body.session_ids = [...new Set(selected.map((row) => row.session_id))];
  else body.keys = selected.map((row) => row.record_key);
  await api("/api/assignments", body);
  await refreshProjects(); invalidate("人工归属已更新"); await analyze();
  notify("已更新项目归属。");
}
function claim(prefix = "claim") {
  return {purpose: $(`${prefix}-purpose`).value, amount: $(`${prefix}-amount`).value.trim(),
    currency: $(`${prefix}-currency`).value, amount_note: $(`${prefix}-note`).value};
}
function validateClaim(value) {
  if (value.amount.trim() && (!/^\d+(\.\d{1,2})?$/.test(value.amount.trim()) || !value.amount_note.trim())) {
    throw new Error("请填写非负报销金额，最多保留两位小数，并说明金额依据。");
  }
}
function ownerLink(owner, closeDialog = null) {
  const link = node("button", "batch-link", `${owner.number || "报销记录"} · v${owner.version}`);
  link.addEventListener("click", () => run("正在加载报销记录…", async () => {
    if (closeDialog) $(closeDialog).close();
    page("batches"); await showBatch(owner.batch_id);
    $("batch-detail").scrollIntoView({behavior: "smooth", block: "start"});
  }));
  return link;
}
function renderAvailability(result) {
  const availability = result.availability;
  const target = $("availability-groups"); target.replaceChildren();
  if (!availability) { $("availability-panel").hidden = true; return; }
  const matched = availability.matched_summary;
  const available = availability.available_summary;
  const excluded = availability.excluded_summary;
  $("availability-title").textContent = availability.mode === "all" ? "全部用量，仅供查看" : "可用用量";
  $("availability-summary").textContent = `${result.time_coverage?.complete === false ? "当前范围内已确定的" : "当前范围共"}${counts(matched.record_count)} 条用量，已排除 ${counts(excluded.record_count)} 条，剩余 ${counts(available.record_count)} 条可用。`;
  for (const group of availability.excluded_groups || []) {
    const item = node("div", "availability-group");
    const quantities = [];
    if (group.detail_count) quantities.push(`${counts(group.detail_count)} 条明细`);
    const rollupRows = group.row_count - group.detail_count;
    if (rollupRows > 0) quantities.push(`${counts(rollupRows)} 条历史汇总（代表 ${counts(group.rollup_record_count)} 条记录）`);
    const reason = String(group.message || "已排除").replace(/[。.!！：:]+$/u, "");
    item.append(node("p", "", `${reason}：${quantities.join("，") || `${counts(group.record_count)} 条用量`}。`));
    const owners = node("div", "availability-owners");
    for (const owner of group.owners || []) {
      owners.append(ownerLink(owner), node("span", `status ${owner.status}`, labels[owner.status] || owner.status));
    }
    if (group.owners?.length) item.append(owners);
    target.append(item);
  }
  if (availability.mode === "all") target.prepend(node("p", "field-help", "保存报销记录前，请切换到“可用用量”并更新预览。"));
  $("availability-panel").hidden = availability.mode === "available" && !excluded.record_count;
}
function usageCell(row) {
  const stateLabel = {available: "可用", claimed: "已占用", ambiguous: "待核对", pending: "待核对"};
  const content = node("span", "", "");
  content.append(node("span", `status ${row.usage_state || "available"}`, stateLabel[row.usage_state] || "可用"));
  for (const owner of row.usage_owners || []) {
    const line = node("span", "subline"); line.append(ownerLink(owner)); content.append(line);
  }
  return content;
}
async function prepareBatch(payload, batchId = null) {
  validateClaim(payload.claim);
  const signature = JSON.stringify({payload, batchId});
  const prior = state.pendingBatch;
  const key = prior?.signature === signature ? prior.request.idempotency_key : crypto.randomUUID();
  const request = {...payload, idempotency_key: key};
  const pending = {request, batchId, signature, previewed: prior?.signature === signature && prior.previewed};
  state.pendingBatch = pending;
  // A lost create response must retry the original request, not fail a newer preview.
  if (pending.previewed) return saveBatch();
  const previewRequest = {...request};
  if (batchId) previewRequest.batch_id = batchId;
  const result = await api("/api/batches/preview", previewRequest);
  if (result.blocking) {
    renderOverlaps(result.conflicts);
    if ($("revision-dialog").open) $("revision-dialog").close();
    $("overlap-dialog").showModal();
    return;
  }
  pending.previewed = true;
  await saveBatch();
}
function renderOverlaps(conflicts) {
  const target = $("overlap-list"); target.replaceChildren();
  for (const conflict of conflicts) {
    const item = node("article", "overlap-item");
    item.append(node("p", "", conflict.message));
    const owners = node("div", "availability-owners");
    for (const owner of conflict.owners || []) owners.append(ownerLink(owner, "overlap-dialog"));
    item.append(owners); target.append(item);
  }
}
async function saveBatch() {
  const pending = state.pendingBatch;
  if (!pending) throw new Error("请更新预览后重新保存。");
  const path = pending.batchId ? `/api/batches/${encodeURIComponent(pending.batchId)}/revisions` : "/api/batches";
  const saved = await api(path, pending.request);
  state.pendingBatch = null;
  $("overlap-dialog").close(); $("revision-dialog").close();
  state.revision = null;
  if (!pending.batchId) {
    for (const id of ["claim-purpose", "claim-amount", "claim-note"]) $(id).value = "";
    $("claim-explanation").textContent = "申请报销金额由你填写。";
  }
  invalidate("已保存，请更新预览");
  let refreshed = true;
  try { await refreshBatches(); if (state.ledger) await analyze(); }
  catch { refreshed = false; }
  try { await download(saved.batch_id || saved.id, saved.version); }
  catch { throw new Error("记录已保存，下载失败。请在“报销记录”中下载材料。"); }
  const message = saved.lifecycle === "voided" ? "已下载已作废记录的历史材料。"
    : !saved.is_effective ? "已下载该历史版本的材料。"
    : refreshed ? "已保存报销记录，材料已下载。" : "已保存报销记录，材料已下载。请更新预览后继续。";
  notify(message);
}
async function download(id, version) {
  const path = `/api/batches/${encodeURIComponent(id)}/revisions/${version}/download`;
  let response;
  try { response = await fetch(path, {method: "HEAD", credentials: "same-origin", cache: "no-store"}); }
  catch { throw new Error("下载失败，请确认程序仍在运行后重试。"); }
  if (!response.ok) throw new Error("材料无法下载，请在报销记录中核对后重试。");
  // Let the browser stream the authenticated response directly to its download manager.
  const anchor = node("a"); anchor.href = path; anchor.download = "";
  document.body.append(anchor); anchor.click(); anchor.remove();
}
async function refreshBatches() {
  const displayedBatchId = state.batch?.id || state.batch?.batch_id;
  state.batches = (await api("/api/batches")).batches;
  $("batch-nav-count").textContent = counts(state.batches.length);
  renderBatches();
  if (displayedBatchId) await showBatch(displayedBatchId);
}
function batchStatus(row) {
  return row.lifecycle === "voided" ? row.lifecycle : row.status;
}
function renderBatches() {
  if (!state.batches.length) {
    empty($("batch-list"), "暂无报销记录", "在“用量与费用”选择项目和日期后保存。"); return;
  }
  $("batch-list").replaceChildren(table([
    {title: "记录编号", value: (row) => {
      const link = node("button", "batch-link", row.number);
      link.addEventListener("click", () => run("正在加载报销记录…", () => showBatch(row.id || row.batch_id))); return link;
    }},
    {title: "项目 / 期间", wrap: true, value: (row) => {
      const text = node("span", "", row.project_name);
      text.append(node("span", "subline", `${rangeDescription(row)}（北京时间）`)); return text;
    }},
    {title: "当前版本", value: (row) => row.active_version ? `v${row.active_version}` : "—"},
    {title: "参考成本 USD", numeric: true, value: (row) => money(row.total_cost_usd)},
    {title: "申请金额", numeric: true, value: (row) => row.claim.amount === null ? "未填写" : `${money(row.claim.amount)} ${row.claim.currency}`},
    {title: "报销状态", value: (row) => node("span", `status ${batchStatus(row)}`, labels[batchStatus(row)])},
    {title: "创建时间", value: (row) => dateTime(row.created_at)},
  ], state.batches));
}
async function showBatch(id) {
  state.batch = await api(`/api/batches/${encodeURIComponent(id)}`);
  renderBatchDetail();
}
function actionButton(label, action, className = "button small") {
  const button = node("button", className, label);
  button.addEventListener("click", action);
  return button;
}
async function markStatus(batch, revision, status) {
  await api(`/api/batches/${encodeURIComponent(batch.id || batch.batch_id)}/revisions/${revision.version}/status`, {status, expected_generation: batch.generation});
  invalidate("记录已更新，请更新预览");
  await refreshBatches();
  if (state.ledger) {
    try { await analyze(); } catch { /* The saved status is retained; the next preview can retry. */ }
  }
  notify(`已标记为“${labels[status]}”。`);
}
function renderBatchDetail() {
  const batch = state.batch; const target = $("batch-detail"); target.replaceChildren();
  if (!batch) return;
  const panel = node("section", "panel"); const header = node("div", "batch-detail-header");
  const heading = node("div"); heading.append(node("h2", "", `${batch.number} · 修改历史`));
  if (batch.lifecycle === "voided") heading.append(node("p", "", "此记录已作废，历史材料可继续下载。"));
  if (batch.current_difference_count) heading.append(node("p", "warning", `${counts(batch.current_difference_count)} 条用量的当前来源值与保存依据不同，历史材料保持原值。`));
  const headerActions = node("div", "revision-actions");
  headerActions.append(actionButton("收起", () => { state.batch = null; target.replaceChildren(); }));
  header.append(heading, headerActions); panel.append(header);
  for (const revision of [...batch.revisions].sort((a, b) => b.version - a.version)) {
    const result = revision.analysis; const value = revision.claim;
    const item = node("article", "revision-card"); item.dataset.version = String(revision.version); item.dataset.batchId = batch.id || batch.batch_id;
    const title = node("div", "revision-title");
    title.append(node("strong", "", `v${revision.version}`));
    title.append(node("span", `status ${revision.is_effective ? "effective" : "historical"}`, revision.is_effective ? "当前记录" : "历史版本"));
    title.append(node("span", `status ${batchStatus(revision)}`, labels[batchStatus(revision)] || revision.status), node("span", "muted", dateTime(revision.created_at)));
    const meta = node("div", "revision-meta");
    meta.append(node("span", "", result.project_name), node("span", "", `${rangeDescription(result)}（北京时间）`),
      node("span", "", `参考成本 ${money(result.summary.total_cost_usd)} USD`),
      node("span", "", value.amount === null || value.amount === "" ? "申请金额未填写" : `申请 ${money(value.amount)} ${value.currency}`));
    item.append(title, meta);
    const coverage = node("div", "warning time-coverage-note"); renderTimeCoverage(coverage, result, null, true);
    if (!coverage.hidden) item.append(coverage);
    if (result.summary_complete == null && result.time_coverage == null) item.append(node("p", "field-help frozen-note", "沿用旧记录的冻结用量与说明，未重新判断历史资料完整性。"));
    if (value.purpose) item.append(node("p", "revision-purpose", value.purpose));
    if (value.amount_note) item.append(node("p", "revision-purpose", `金额依据：${value.amount_note}`));
    const actions = node("div", "revision-actions");
    actions.append(actionButton("下载材料", () => run("正在下载材料…", () => download(batch.id || batch.batch_id, revision.version)), "button small primary"));
    if (revision.can_edit) actions.append(actionButton("修改报销记录", () => openRevision(batch, revision)));
    if (revision.can_submit) actions.append(actionButton("标记已提交", () => run("正在更新状态…", () => markStatus(batch, revision, "submitted"))));
    if (revision.can_reimburse) actions.append(actionButton("标记已报销", () => run("正在更新状态…", () => markStatus(batch, revision, "reimbursed"))));
    if (revision.can_withdraw) actions.append(actionButton("撤回为草稿", () => openLifecycle("withdraw", batch, revision)));
    if (revision.can_void) actions.append(actionButton("作废记录", () => openLifecycle("void", batch, revision), "button small danger"));
    item.append(actions);
    if (revision.filename) item.append(node("div", "revision-file", revision.filename));
    panel.append(item);
  }
  if (batch.events?.length) {
    const details = node("details", "scope-details history-details"); details.append(node("summary", "", "操作记录"));
    const list = node("ol", "audit-list");
    const actionLabels = {create: "创建记录", revise: "修改记录", withdraw: "撤回为草稿", void: "作废记录", status: "更新状态"};
    for (const event of [...batch.events].reverse()) {
      const entry = node("li", "audit-item");
      const action = event.action === "status" ? `标记为“${labels[event.new_status] || event.new_status}”` : actionLabels[event.action] || "更新记录";
      entry.append(node("strong", "", action), node("p", "", dateTime(event.created_at)));
      if (event.reason) entry.append(node("p", "", event.reason));
      list.append(entry);
    }
    details.append(list); panel.append(details);
  }
  target.append(panel);
}
function openRevision(batch, revision) {
  if (state.busy) return;
  clearFeedback();
  state.revision = {batchId: batch.id || batch.batch_id, version: revision.version, generation: batch.generation,
    analysis: null, frozen: revision.analysis, filterGeneration: 0, request: 0};
  $("revision-caption").textContent = `${batch.number} · 修改当前记录`;
  $("revision-basis").value = "frozen";
  $("revision-basis").options[1].disabled = !state.ledger;
  $("revision-filters").hidden = true;
  for (const [target, source] of [["revision-project", "project-select"]]) {
    $(target).replaceChildren(...[...$(source).options].map((option) => option.cloneNode(true)));
    $(target).value = revision.analysis.project_id || $(source).value;
    if ($(target).selectedIndex < 0) $(target).value = "all";
  }
  revisionTimeRange.setIntent(AhaTimeRange.editableIntent(revision.analysis), AhaTimeRange.fromAnalysis(revision.analysis));
  $("revision-purpose").value = revision.claim.purpose || "";
  $("revision-amount").value = revision.claim.amount ?? "";
  $("revision-currency").value = revision.claim.currency;
  $("revision-note").value = revision.claim.amount_note || "";
  AhaForms.sync($("revision-dialog"));
  renderRevisionPreview(revision.analysis, true);
  $("revision-dialog").showModal(); syncActions();
}
function renderRevisionPreview(result, frozen = false) {
  const summary = result.summary;
  const omittedOnly = result.time_coverage?.complete === false && !hasUsage(summary);
  $("revision-preview").replaceChildren(
    node("strong", "", omittedOnly ? "当前时段没有可确定的用量" : `${counts(summary.record_count)} 条用量 · 参考成本 ${money(summary.total_cost_usd)} USD`),
    node("p", "field-help", `${result.project_name || "当前项目"} · ${rangeDescription(result)}（北京时间）`),
  );
  if (frozen) $("revision-preview").append(node("p", "field-help", result.summary_complete == null && result.time_coverage == null
    ? "沿用旧记录的冻结用量与说明，未重新判断历史资料完整性。" : "保留原记录的时间范围与冻结用量；保存时不会延长范围。"));
  const coverage = node("div", "warning time-coverage-note");
  renderTimeCoverage(coverage, result, frozen ? null : () => { void applyRevisionTimeRange(AhaTimeRange.wholeDays(result)).catch(() => {}); }, frozen);
  if (!coverage.hidden) $("revision-preview").append(coverage);
  if (result.pending_count) $("revision-preview").append(node("p", "field-help", `有 ${counts(result.pending_count)} 项用量待核对，合计仅含已核实部分。`));
  const excluded = result.availability?.excluded_summary?.record_count;
  if (excluded) $("revision-preview").append(node("p", "field-help", `已排除其他记录占用或待核对的 ${counts(excluded)} 条用量。`));
}
async function prepareRevisionPreview() {
  if (!state.revision) return;
  const revision = state.revision;
  state.pendingBatch = null;
  revision.analysis = null; revision.filterGeneration += 1;
  $("revision-filters").hidden = $("revision-basis").value === "frozen";
  if ($("revision-basis").value === "frozen") {
    renderRevisionPreview(revision.frozen, true); syncActions(); return;
  }
  revisionTimeRange.markPending();
  $("revision-preview").replaceChildren(node("p", "", "正在更新用量…"));
  const generation = revision.filterGeneration; const request = ++revision.request;
  const isCurrent = () => state.revision === revision && $("revision-dialog").open && $("revision-basis").value === "current"
    && generation === revision.filterGeneration && request === revision.request && !state.stopped;
  let result;
  try {
    result = await api(`/api/batches/${encodeURIComponent(revision.batchId)}/analysis`, {
      classification_revision: state.config.revision, time_range: revisionTimeRange.getIntent(),
      project_id: $("revision-project").value, base_version: revision.version, expected_generation: revision.generation,
    }, isCurrent);
  } catch (error) {
    if (!isCurrent() && !error.invalidated) return;
    if (isCurrent()) $("revision-preview").replaceChildren(node("p", "", "预览未完成，请调整条件后更新用量。"));
    throw error;
  }
  if (!isCurrent()) return;
  revision.analysis = result;
  if (result.time_range?.resolved_at) state.now = result.time_range.resolved_at;
  revisionTimeRange.setResolved(AhaTimeRange.fromAnalysis(result));
  renderRevisionPreview(result); syncActions();
}
function openLifecycle(action, batch, revision = null) {
  if (state.busy) return;
  clearFeedback();
  const settings = {
    withdraw: {title: "撤回为草稿", reason: "撤回原因", confirm: "确认撤回", description: "撤回后可修改，用量仍由此记录占用。"},
    void: {title: "作废记录", reason: "作废原因", confirm: "确认作废", description: "作废后用量可供其他报销记录使用，历史记录和材料仍保留。"},
  }[action];
  state.lifecycle = {action, batchId: batch.id || batch.batch_id, generation: batch.generation, signature: null, key: null};
  $("lifecycle-title").textContent = settings.title;
  $("lifecycle-description").textContent = settings.description;
  $("lifecycle-reason-label").textContent = settings.reason;
  $("lifecycle-submit").textContent = settings.confirm;
  $("lifecycle-submit").classList.toggle("danger", action === "void");
  $("lifecycle-reason").value = "";
  $("lifecycle-reason").placeholder = `请填写${settings.reason}`;
  $("lifecycle-summary").replaceChildren(node("strong", "", batch.number), node("span", "", `${batch.project_name} · ${labels[batchStatus(batch)] || "待核对"}`));
  $("lifecycle-dialog").showModal();
}
async function saveLifecycle() {
  const operation = state.lifecycle;
  if (!operation) throw new Error("请重新选择记录后操作。");
  const reason = $("lifecycle-reason").value.trim();
  if (!reason) throw new Error("请填写操作原因。");
  const body = {reason, expected_generation: operation.generation};
  const signature = JSON.stringify(body);
  if (signature !== operation.signature) { operation.key = crypto.randomUUID(); operation.signature = signature; }
  body.idempotency_key = operation.key;
  await api(`/api/batches/${encodeURIComponent(operation.batchId)}/${operation.action}`, body);
  $("lifecycle-dialog").close(); state.lifecycle = null;
  invalidate("记录已更新，请更新预览");
  await refreshBatches();
  if (state.ledger) await analyze();
  notify({withdraw: "已撤回为草稿，可以修改。", void: "已作废，用量已释放。"}[operation.action]);
}
async function scanMetadata() {
  await api("/api/session-metadata", {roots: lines($("metadata-roots").value)});
  await Promise.all([refreshLedger(), refreshProjects()]);
  invalidate("目录依据已更新，请重新预览");
  $("source-dialog").close(); notify("已更新目录识别。");
}
async function initialize() {
  const status = await api("/api/status");
  state.csrf = status.csrf_token; state.today = status.today; state.now = status.now; state.ledger = status.ledger;
  $("app-version").textContent = `v${status.version}`;
  renderSource();
  await Promise.all([refreshProjects(), refreshReconciliations(), refreshBatches()]);
  await analyze();
  const currentSync = status.sync || status.startup_sync;
  if (currentSync) {
    state.sync = currentSync; renderSource();
    if (currentSync.status === "running") void watchSync(currentSync).catch((error) => {
      state.syncBusy = false; state.sync = {status: "failed", message: error.message}; renderSource();
    });
  } else void loadSource("/api/sync", {trigger: "startup"});
}
async function openReconciliations() {
  await refreshReconciliations(); renderReconciliations(); $("reconciliation-dialog").showModal();
}
function renderReconciliations() {
  const target = $("reconciliation-list"); AhaForms.destroy(target); target.replaceChildren();
  if (!state.reconciliations.length) { empty(target, "暂无待核对用量", "已保存来源的核对结果可继续用于本地查询。"); return; }
  const choiceLabels = {detail: "采用已存明细", rollup: "采用完整日汇总", current: "保留当前值", candidate: "采用候选修订", same: "确认为同一消费", independent: "确认为独立消费"};
  for (const entry of state.reconciliations) {
    const card = node("article", "reconciliation-card");
    card.append(node("h3", "", entry.message || entry.title || "来源用量需要核对"));
    const facts = node("div", "reconciliation-facts");
    if (entry.date || entry.model) facts.append(node("p", "", [entry.date, entry.model].filter(Boolean).join(" · ")));
    if (entry.source_name) facts.append(node("p", "", `来源：${entry.source_name}`));
    if (entry.current_cost_usd !== undefined) facts.append(node("p", "", `当前参考成本：${money(entry.current_cost_usd)} USD`));
    if (entry.candidate_cost_usd !== undefined) facts.append(node("p", "", `候选参考成本：${money(entry.candidate_cost_usd)} USD`));
    if (entry.detail_count !== undefined) facts.append(node("p", "", `已存明细 ${counts(entry.detail_count)} 条；来源日汇总 ${counts(entry.rollup_count)} 条，代表 ${counts(entry.rollup_record_count)} 条记录。`));
    for (const [key, label] of [["previous", "此前来源"], ["observed", "本次来源"]]) {
      if (entry[key]) facts.append(node("p", "", `${label}：${counts(entry[key].detail ?? entry[key].detail_count)} 条明细，${counts(entry[key].rollup ?? entry[key].rollup_count)} 条汇总。`));
    }
    for (const [key, label] of [["current", "当前依据"], ["candidate", "候选依据"]]) {
      const value = entry[key] || entry[`${key}_summary`];
      if (value && typeof value === "object") {
        const summary = value.summary || value;
        const parts = [value.source_name || value.source?.name];
        if (summary.total_cost_usd !== undefined) parts.push(`参考成本 ${money(summary.total_cost_usd)} USD`);
        if (summary.request_count !== undefined || summary.record_count !== undefined) parts.push(`${counts(summary.request_count ?? summary.record_count)} 条记录`);
        if (summary.created_at !== undefined) parts.push(dateTime(Number(summary.created_at) * 1000));
        if (summary.session_id) parts.push(`会话 ${summary.session_id}`);
        if (summary.input_tokens !== undefined) parts.push(`输入 ${counts(summary.input_tokens)} · 输出 ${counts(summary.output_tokens)}`);
        facts.append(node("p", "", `${label}：${parts.filter(Boolean).join(" · ") || "保留原始来源依据"}`));
      }
    }
    card.append(facts);
    const form = node("form"); const selectLabel = node("label", "field", "采用依据"); const select = node("select");
    for (const choice of entry.choices || []) {
      const value = typeof choice === "string" ? choice : choice.value;
      const label = entry.type === "source" && value === "current" ? "确认此来源，保留本地历史" : choiceLabels[value] || choice.label || "确认来源关系";
      const option = node("option", "", label); option.value = value; select.append(option);
    }
    selectLabel.append(select);
    const reasonLabel = node("label", "field", "核对说明"); const reason = node("textarea"); reason.rows = 2; reason.maxLength = 4000; reason.required = true; reasonLabel.append(reason);
    const submit = node("button", "button primary", "确认依据"); submit.type = "submit"; submit.disabled = !select.options.length;
    form.append(selectLabel, reasonLabel, submit);
    form.addEventListener("submit", (event) => { event.preventDefault(); void run("正在保存核对结果…", async () => {
      await api(`/api/reconciliations/${encodeURIComponent(entry.id)}`, {choice: select.value, reason: reason.value,
        expected_generation: entry.generation, idempotency_key: crypto.randomUUID()});
      await Promise.all([refreshLedger(), refreshReconciliations()]); invalidate("核对结果已更新，请重新预览"); renderReconciliations();
    }); });
    card.append(form); target.append(card);
    AhaForms.mount(card);
  }
}
document.querySelectorAll("[data-page]").forEach((button) => button.addEventListener("click", () => page(button.dataset.page)));
document.querySelectorAll("[data-close]").forEach((button) => button.addEventListener("click", () => $(button.dataset.close).close()));
for (const id of ["project-select", "availability-mode"]) $(id).addEventListener("change", () => invalidate());
$("source-options").addEventListener("click", () => { clearFeedback(); $("source-dialog").showModal(); });
$("load-default").addEventListener("click", () => { void loadSource(); });
$("review-data").addEventListener("click", () => run("正在加载核对依据…", openReconciliations));
for (const id of ["import-sql", "dialog-import-sql"]) $(id).addEventListener("click", () => $("sql-file").click());
$("sql-file").addEventListener("change", (event) => {
  const file = event.target.files[0]; event.target.value = "";
  void importSQL(file).catch((error) => notify(error.message, "error"));
});
$("sqlite-form").addEventListener("submit", (event) => { event.preventDefault(); void loadSource("/api/sync", {path: $("sqlite-path").value}); });
$("metadata-form").addEventListener("submit", (event) => { event.preventDefault(); run("正在刷新目录识别…", scanMetadata); });
$("refresh-metadata").addEventListener("click", () => { clearFeedback(); $("source-dialog").showModal(); });
for (const id of ["analyze", "refresh-availability"]) $(id).addEventListener("click", () => run("正在更新预览…", analyze));
$("new-project").addEventListener("click", () => openProject());
$("project-form").addEventListener("submit", (event) => { event.preventDefault(); run("正在保存项目…", saveProject); });

async function selectPreviewTab(name) {
  state.tab = name; state.page = 1; state.cursor = null; state.nextCursor = null; state.cursors = [null]; state.selected.clear();
  document.querySelectorAll("[data-tab]").forEach((tab) => {
    const selected = tab.dataset.tab === name;
    tab.classList.toggle("active", selected); tab.setAttribute("aria-selected", String(selected));
  });
  await renderPreview();
}
document.querySelectorAll("[data-tab]").forEach((button) => button.addEventListener("click", () => run("正在切换预览…", () => selectPreviewTab(button.dataset.tab))));
$("view-details").addEventListener("click", () => run("正在加载明细…", async () => {
  if (!state.analysis) throw new Error("请先更新预览。");
  await selectPreviewTab("details");
  $("usage-preview").scrollIntoView({behavior: "smooth", block: "start"});
}));
$("prev-page").addEventListener("click", () => run("正在翻页…", async () => { state.page -= 1; state.cursor = state.cursors[state.page - 1] || null; await renderPreview(); }));
$("next-page").addEventListener("click", () => run("正在翻页…", async () => { if (!state.nextCursor) return; state.cursor = state.nextCursor; state.cursors[state.page] = state.cursor; state.page += 1; await renderPreview(); }));
$("clear-selection").addEventListener("click", () => { state.selected.clear(); renderRowTable(); renderSelection(); });
$("assign").addEventListener("click", () => run("正在分配项目…", applyAssignment));
$("create-batch").addEventListener("click", () => run("正在保存报销记录…", () => prepareBatch({analysis_id: state.analysis.analysis_id, claim: claim()})));
$("confirm-batch").addEventListener("click", () => run("正在更新预览…", async () => {
  const batchId = state.pendingBatch?.batchId;
  $("overlap-dialog").close(); state.pendingBatch = null;
  if (batchId) { await showBatch(batchId); notify("请重新打开当前报销记录进行修改。", "info"); }
  else await analyze();
}));
$("refresh-batches").addEventListener("click", () => run("正在刷新报销记录…", refreshBatches));
$("revision-basis").addEventListener("change", () => run("正在重新选择用量…", prepareRevisionPreview));
$("revision-analyze").addEventListener("click", () => run("正在更新用量…", prepareRevisionPreview));
$("revision-project").addEventListener("change", () => {
  invalidateRevision("条件已更改，请点击“更新用量”。");
  syncActions();
});
$("revision-dialog").addEventListener("close", () => { state.revision = null; syncActions(); });
$("revision-form").addEventListener("submit", (event) => {
  event.preventDefault(); run("正在保存修改…", () => {
    if (!state.revision) throw new Error("请重新打开报销记录。");
    const payload = {base_version: state.revision.version, expected_generation: state.revision.generation, claim: claim("revision")};
    if ($("revision-basis").value === "current") {
      if (!state.revision.analysis) throw new Error("请重新选择用量并确认预览。");
      payload.analysis_id = state.revision.analysis.analysis_id;
    }
    return prepareBatch(payload, state.revision.batchId);
  });
});
$("lifecycle-form").addEventListener("submit", (event) => { event.preventDefault(); run("正在更新报销记录…", saveLifecycle); });
const shutdown = () => run("正在退出…", async () => {
  await api("/api/shutdown", {});
  state.stopped = true;
  document.querySelectorAll("dialog[open]").forEach((dialog) => dialog.close());
  state.ledger = null; invalidate("程序正在退出");
  notify("正在退出程序，已保存资料会保留，可以关闭此页面。", "info");
});
$("shutdown").addEventListener("click", shutdown);
$("shutdown-compact").addEventListener("click", shutdown);
AhaForms.mount();
run("正在加载…", initialize);
