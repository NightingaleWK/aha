"use strict";

const $ = (id) => document.getElementById(id);
const state = {
  csrf: "", today: "", now: "", ledger: null, sync: null, syncBusy: false, syncGeneration: 0, syncPreviewPending: false, reconciliations: [],
  ledgerRequest: 0, projectsRequest: 0, reconciliationsRequest: 0,
  config: {revision: 0, projects: []}, analysis: null, tab: "daily", page: 1,
  rows: [], total: 0, cursor: null, nextCursor: null, cursors: [null], selected: new Map(), batches: [], batch: null,
  busy: false, pendingBatch: null, revision: null, lifecycle: null, noticeTimer: null, stopped: false,
  filterGeneration: 0, analysisRequest: 0,
  sourceBinding: null, bindingSelection: null, bindingRequest: 0, dataDirectory: "",
  backupBusy: false, backupGeneration: 0, backupJob: null, backupUpload: null, backupController: null,
  pendingBackupUploads: [],
  backupLimits: {archive_bytes: 4 * 1024 ** 3, chunk_bytes: 4 * 1024 ** 2},
  activePage: "usage", associations: null, associationGeneration: 0,
  associationSummaryRequest: 0, associationRecordsRequest: 0, associationPreviewRequest: 0,
  associationRows: [], associationPage: 1, associationCursor: null, associationNextCursor: null,
  associationCursors: [null], associationSelected: new Map(), associationAllFiltered: false,
  associationPreview: null, projectEditor: null, projectGeneration: 0,
};
const labels = {draft: "草稿", submitted: "已提交", reimbursed: "已报销", voided: "已作废"};
const origins = {directory_binding: "目录整体关联", manual: "手动分配", directory_rule: "目录匹配", session_binding: "会话默认归属", history_restore: "历史依据恢复", identity_confirmation: "身份核对归属", retained: "已保存归属", unassigned: "未归属"};
const associationReasons = {recoverable: "历史依据可恢复", directory_unbound: "有目录，待确认归属", missing: "缺少目录依据", conflict: "目录依据存在冲突"};
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
  const controls = [...document.querySelectorAll("button:not([data-sync-control]):not([data-backup-cancel]),input,textarea,select")];
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
    refreshPendingSyncPreview();
  }
}
function refreshPendingSyncPreview() {
  if (!state.syncPreviewPending || state.syncBusy || state.busy || state.stopped) return;
  state.syncPreviewPending = false;
  void run("正在更新本地预览…", analyze);
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
  $("view-all-history").disabled = state.busy || !state.ledger?.coverage?.start_date;
  $("bind-default-source").disabled = state.busy || state.syncBusy;
  $("create-full-backup").disabled = state.busy || state.backupBusy;
  $("restore-backup").disabled = state.busy || state.backupBusy;
  $("restore-file").disabled = state.busy || state.backupBusy;
  $("restore-destination").disabled = state.busy || state.backupBusy;
  $("cancel-backup").disabled = !state.backupBusy;
  $("clear-unfinished-uploads").disabled = state.busy || state.backupBusy;
  document.querySelectorAll("[data-usage-select]").forEach((control) => { control.disabled = state.busy || control.getAttribute("data-unselectable") === "true"; });
  syncAssociationActions();
  syncProjectActions();
  timeRange.setDisabled(state.busy || !state.now);
  revisionTimeRange.setDisabled(state.busy || !state.now || !state.revision || $("revision-basis").value !== "current");
  AhaForms.sync();
}
function page(name) {
  state.activePage = name;
  if (name !== "projects") {
    state.associationSummaryRequest += 1;
    state.associationRecordsRequest += 1;
  }
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
  $("empty-range-note").hidden = true;
  $("assignment-coverage-note").hidden = true;
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
function refreshRequest(requestKey, isCurrent) {
  const request = ++state[requestKey];
  return () => request === state[requestKey] && isCurrent() && !state.stopped;
}
async function currentResult(path, isCurrent) {
  try { return await api(path, undefined, isCurrent); }
  catch (error) { if (isCurrent()) throw error; return null; }
}
async function refreshLedger(isCurrent = () => true) {
  const active = refreshRequest("ledgerRequest", isCurrent);
  const ledger = await currentResult("/api/ledger", active);
  if (!active()) return;
  state.ledger = ledger;
  renderSource();
}
function syncStatus(attempt) {
  const status = attempt?.status || attempt?.state;
  const result = attempt?.result?.status || attempt?.result?.state;
  return status === "completed" && result === "needs_review" ? result : status || result;
}
function renderSource() {
  const ledger = state.ledger;
  const amount = ledger?.counts || {};
  const coverage = ledger?.coverage || {};
  const attempt = state.sync || ledger?.last_attempt;
  const status = syncStatus(attempt);
  const running = state.syncBusy || status === "running";
  const failed = !running && ["failed", "cancelled"].includes(status);
  const needsReview = !running && !failed && status === "needs_review";
  const last = ledger?.last_successful_sync_at ||
    (["completed", "succeeded", "success"].includes(syncStatus(ledger?.last_sync)) ? ledger.last_sync.finished_at || ledger.last_sync.completed_at : null);
  $("source-name").textContent = "本地用量台账";
  const bindingRequired = state.sourceBinding?.required;
  $("source-mode").textContent = running ? "同步中" : bindingRequired ? "待确认本机来源" : failed ? "同步失败" : needsReview ? "需要核对" : last ? "已同步" : "本地资料";
  const period = coverage.start_date ? ` · ${coverage.start_date} 至 ${coverage.end_date}` : "";
  $("source-description").textContent = ledger
    ? `${counts(amount.detail_count)} 条明细 · ${counts(amount.rollup_count)} 条来源日汇总${period} · ${last ? `上次成功 ${dateTime(last)}` : "尚无成功同步"}${needsReview ? " · 本次来源需要核对" : ""}`
    : "正在读取本地资料。";
  $("load-default").textContent = state.syncBusy ? "正在同步…" : bindingRequired ? "接续本机来源" : "立即同步";
  $("source-binding-note").hidden = !bindingRequired;
  $("sync-error").hidden = !failed;
  const reason = attempt?.result?.error_message || attempt?.message || attempt?.error_message || "同步未完成，请稍后重试。";
  const saved = last || amount.detail_count > 0 || amount.rollup_count > 0;
  $("sync-error").textContent = failed ? `${reason} ${saved ? "当前显示已保存的本地数据。" : ""}${last ? "" : "尚未成功同步，当前统计不代表实际用量。"}` : "";
  $("reconciliation-count").textContent = counts(amount.pending_count || state.reconciliations.length);
  renderDirectories(); syncActions();
}
async function refreshReconciliations(isCurrent = () => true) {
  const active = refreshRequest("reconciliationsRequest", isCurrent);
  const result = await currentResult("/api/reconciliations", active);
  if (!active()) return;
  state.reconciliations = result.cases;
  $("reconciliation-count").textContent = counts(state.reconciliations.length);
}
function handleSyncError(error) {
  const message = error.message || "同步未完成，原本地数据仍可查询。";
  const status = syncStatus(state.sync);
  if (["completed", "needs_review"].includes(status)) state.syncPreviewPending = false;
  if (!["completed", "failed", "needs_review"].includes(status)) {
    state.sync = {status: "failed", message};
  }
  notify(message, "error");
}
async function watchSync(job, generation = state.syncGeneration) {
  const isCurrent = () => generation === state.syncGeneration && !state.stopped;
  if (!isCurrent()) return;
  state.sync = job; state.syncBusy = job.status === "running";
  renderSource();
  while (isCurrent() && state.sync.status === "running") {
    await new Promise((resolve) => setTimeout(resolve, 450));
    if (!isCurrent()) return;
    const latest = await api(`/api/sync/${encodeURIComponent(job.id)}`, undefined, isCurrent);
    if (!isCurrent()) return;
    state.sync = latest;
    renderSource();
  }
  if (!isCurrent()) return;
  state.syncBusy = false;
  renderSource();
  const failed = ["failed", "cancelled"].includes(syncStatus(state.sync));
  if (!failed) {
    invalidate("同步已完成，请更新预览");
    invalidateAssociations("用量已更新，请刷新项目费用与归属记录。");
    state.syncPreviewPending = true;
  }
  await Promise.all([refreshLedger(isCurrent), refreshProjects(isCurrent), refreshReconciliations(isCurrent)]);
  if (!isCurrent()) return;
  if (failed) { renderSource(); refreshPendingSyncPreview(); return; }
  if (!state.busy) await run("正在更新本地预览…", analyze);
  if (!isCurrent()) return;
  renderSource();
  const needsReview = syncStatus(state.sync) === "needs_review";
  notify(needsReview
    ? "本次来源需要核对，已保留本地用量。请查看“数据核对”。"
    : "同步已完成。后续查询使用本地台账。", needsReview ? "info" : "success");
}
async function loadSource(path = "/api/sync", body = {}) {
  if (state.syncBusy || state.stopped) return;
  if (path !== "/api/source/sql" && (body.path || state.sourceBinding?.required)) {
    try {
      if (await openSourceBinding(body.path || "", {path, body})) return;
    } catch (error) { notify(error.message, "error"); return; }
  }
  const generation = ++state.syncGeneration;
  const isCurrent = () => generation === state.syncGeneration && !state.stopped;
  state.syncBusy = true; state.sync = {status: "running"}; renderSource();
  try {
    const job = await api(path, {...body, idempotency_key: crypto.randomUUID()}, isCurrent);
    if (!isCurrent()) return;
    $("source-dialog").close();
    await watchSync(job, generation);
    if (isCurrent() && state.sync?.code === "source_binding_required") {
      await openSourceBinding(body.path || "", {path, body});
    }
  } catch (error) {
    if (isCurrent()) handleSyncError(error);
  } finally {
    if (isCurrent()) { state.syncBusy = false; renderSource(); refreshPendingSyncPreview(); }
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
async function refreshProjects(isCurrent = () => true) {
  const active = refreshRequest("projectsRequest", isCurrent);
  const config = await currentResult("/api/projects", active);
  if (!active()) return;
  if (state.config.revision !== config.revision) expireProjectBinding("项目配置已更新，请重新查看关联影响。");
  state.config = config;
  const previous = $("project-select").value;
  const select = $("project-select");
  const all = node("option", "", "全部项目（含未归属）"); all.value = "all";
  const unassigned = node("option", "", "未归属"); unassigned.value = "unassigned";
  select.replaceChildren(all, unassigned);
  const assignment = $("assignment-project");
  const previousAssignment = assignment.value;
  const clear = node("option", "", "取消逐条人工例外"); clear.value = "";
  assignment.replaceChildren(clear);
  for (const project of state.config.projects) {
    const option = node("option", "", project.name); option.value = project.id;
    select.append(option);
    assignment.append(option.cloneNode(true));
  }
  assignment.value = state.config.projects.some((project) => project.id === previousAssignment) ? previousAssignment : "";
  select.value = previous;
  if (select.selectedIndex < 0) select.value = "all";
  if (state.revision && $("revision-dialog").open) {
    const revisionProject = $("revision-project"); const selectedProject = revisionProject.value;
    revisionProject.replaceChildren(...[...select.options].map((option) => option.cloneNode(true)));
    revisionProject.value = selectedProject;
    if (revisionProject.selectedIndex < 0) revisionProject.value = "all";
  }
  for (const [id, options, fallback] of [
    ["association-filter-project", [["unassigned", "待归属记录"], ["all", "全部项目（含未归属）"]], "unassigned"],
    ["association-target-project", [["", "请选择项目"]], ""],
  ]) {
    const target = $(id); const selected = target.value;
    target.replaceChildren();
    for (const [value, label] of options) {
      const option = node("option", "", label); option.value = value; target.append(option);
    }
    for (const project of state.config.projects) {
      const option = node("option", "", project.name); option.value = project.id; target.append(option);
    }
    target.value = options.some(([value]) => value === selected) || state.config.projects.some((project) => project.id === selected) ? selected : fallback;
  }
  AhaForms.sync();
  renderAssignmentMode();
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
    const edit = node("button", "button small", "管理目录");
    edit.addEventListener("click", () => openProject(project));
    heading.append(node("h2", "", project.name), edit);
    card.append(heading, node("p", "", project.description || "未填写项目说明"));
    const directoryStatus = node("p", "project-binding-status", project.directory_managed
      ? "已按目录整体关联 · 新增用量随同步自动归入" : project.directories.length ? "目录尚未确认整体关联" : "添加工作目录后自动关联用量");
    card.append(directoryStatus);
    if (!project.directory_managed && project.directories.length) {
      card.append(actionButton("确认目录关联", () => {
        openProject(project); void run("正在检查目录关联影响…", saveProject);
      }, "button small project-confirm-directories"));
    }
    const usage = state.associations?.projects?.find((item) => item.id === project.id);
    const metrics = node("div", "project-usage");
    if (usage) {
      metrics.append(node("span", "field-help", "已核实台账参考成本"), node("strong", "", `${money(usage.total_cost_usd)} USD`),
        node("p", "", `${counts(usage.detail_count)} 条明细 · ${counts(usage.rollup_count)} 行历史日汇总`),
        node("p", "field-help", usage.start_date ? `${usage.start_date} 至 ${usage.end_date}（北京时间）` : "尚无已归属用量"));
      if (usage.pending_count) metrics.append(node("p", "field-help", `另有 ${counts(usage.pending_count)} 条用量待核对，未计入上述成本。`));
    } else metrics.append(node("p", "field-help", "读取项目费用后显示已归属记录与成本。"));
    card.append(metrics, actionButton("查看项目全部费用", () => run("正在查询项目费用…", async () => {
      $("project-select").value = project.id; $("availability-mode").value = "all";
      timeRange.setIntent({kind: "preset", preset: "all", follow_now: false});
      AhaForms.sync(); page("usage"); await analyze();
    }), "button small"));
    const dirs = node("ul");
    for (const directory of project.directories) dirs.append(node("li", "", directory));
    const details = node("details", "project-directories");
    details.append(node("summary", "", `${counts(project.directories.length)} 个工作目录（包含子目录）`), dirs);
    card.append(details);
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
    target.append(node("p", "field-help", `${counts(unresolved.length)} 个会话的目录待确认，其中 ${counts(conflicts)} 个存在冲突。可刷新目录识别，或在“高级：处理无目录与历史资料”中检查依据。`));
  }
}
function projectDraft() {
  const selected = [...$("project-candidates").querySelectorAll("input:checked")].map((input) => input.value);
  const id = $("edit-project-id").value;
  return {
    ...(id ? {project_id: id} : {}), name: $("edit-project-name").value,
    description: $("edit-project-description").value,
    directories: [...new Set([...selected, ...lines($("edit-project-directories").value)])],
  };
}
function syncProjectActions() {
  const editor = state.projectEditor;
  $("preview-project-binding").disabled = state.busy || !editor || Boolean(editor.applied || editor.submitting);
  $("apply-project-binding").disabled = state.busy || !editor?.preview || Boolean(editor.submitting);
  $("apply-project-binding").textContent = editor?.applied ? "刷新已保存结果" : editor?.uncertain ? "重试确认保存结果" : "确认保存并关联";
  $("back-project-editor").disabled = state.busy || !editor || Boolean(editor.applied || editor.submitting || editor.uncertain);
}
function showProjectEditor(message = "") {
  $("project-editor").hidden = false;
  $("project-binding-impact").hidden = true;
  $("project-edit-status").textContent = message;
  $("project-dialog-title").textContent = $("edit-project-id").value ? "管理项目目录" : "新建项目";
  syncProjectActions();
}
function expireProjectBinding(message = "设置已更改，请重新查看关联影响。") {
  const editor = state.projectEditor;
  if (!editor || editor.applied) return;
  editor.request += 1;
  if (editor.submitting || editor.uncertain) {
    editor.stale = true;
    return;
  }
  editor.preview = null; editor.signature = null; editor.key = null; editor.stale = false;
  showProjectEditor(message);
}
function openProject(project = null) {
  clearFeedback();
  state.projectEditor = {generation: ++state.projectGeneration, request: 0, preview: null,
    signature: null, key: null, applied: false, submitting: false, trigger: document.activeElement};
  $("edit-project-id").value = project?.id || "";
  $("edit-project-name").value = project?.name || "";
  $("edit-project-description").value = project?.description || "";
  const selected = new Set(project?.directories || []);
  const candidates = new Map((state.ledger?.directories || []).map((candidate) => [candidate.path, candidate]));
  for (const saved of state.config.projects) {
    for (const path of saved.directories) if (!candidates.has(path)) candidates.set(path, {path});
  }
  const known = new Set();
  const target = $("project-candidates"); target.replaceChildren();
  for (const candidate of candidates.values()) {
    known.add(candidate.path);
    const label = node("label", "candidate-item");
    const check = node("input"); check.type = "checkbox"; check.value = candidate.path;
    check.checked = selected.has(candidate.path);
    const owner = state.config.projects.find((saved) => saved.directories.includes(candidate.path));
    const text = node("span");
    text.append(node("code", "", candidate.path));
    const detail = candidate.session_count === undefined ? "尚无本机识别记录" : `${counts(candidate.session_count)} 个会话${candidate.detail_count === undefined ? "" : ` · ${counts(candidate.detail_count)} 条明细`}`;
    text.append(node("small", "", `${detail}${owner ? ` · 当前属于 ${owner.name}${owner.id === project?.id ? "" : "，选中后整体转入"}` : " · 尚未绑定项目"}`));
    label.append(check, text); target.append(label);
  }
  $("edit-project-directories").value = [...selected].filter((directory) => !known.has(directory)).join("\n");
  showProjectEditor();
  $("project-dialog").showModal();
}
function renderProjectBindingImpact(result) {
  const summary = result.summary || {};
  $("project-editor").hidden = true;
  $("project-binding-impact").hidden = false;
  $("project-dialog-title").textContent = "确认目录关联";
  $("project-binding-caption").textContent = result.project.directories.length
    ? `以下目录将整体关联到“${result.project.name}”。请核对已有记录和费用变化。`
    : `将保存“${result.project.name}”。当前未选择目录，暂不关联用量。`;
  const target = $("project-binding-summary");
  target.replaceChildren(
    node("p", "", `${counts(result.project.directories.length)} 个目录 · ${counts(summary.detail_count)} 条已有明细 · ${counts(summary.session_count)} 个会话`),
    node("p", "project-binding-cost", `参考成本 ${money(summary.total_cost_usd)} USD`),
    node("p", "", `已有 ${counts(summary.already_assigned_count)} 条属于此项目；本次将更新 ${counts(summary.changed_count)} 条记录的归属或关联依据。`));
  if (!summary.detail_count && result.project.directories.length) target.append(node("p", "field-help", "这些目录目前没有可确定的已有记录，确认后识别到的新用量会自动归入。"));
  if (summary.claimed_count) target.append(node("p", "field-help", `其中 ${counts(summary.claimed_count)} 条已有报销占用；占用及已保存材料保持不变。`));
  if (summary.pending_count) target.append(node("p", "field-help", `其中 ${counts(summary.pending_count)} 条用量待核对，参考金额以核对结果为准。`));
  if (summary.recovered_sessions) target.append(node("p", "field-help", `将采用已保存的唯一有效历史目录，恢复 ${counts(summary.recovered_sessions)} 个会话的目录依据。`));
  const directories = $("project-binding-directories"); directories.replaceChildren();
  for (const directory of result.directories || []) {
    const item = node("div", "project-binding-directory");
    item.append(node("code", "", directory.path), node("span", "field-help", `${counts(directory.detail_count)} 条明细 · ${counts(directory.session_count)} 个会话 · ${money(directory.total_cost_usd)} USD`));
    directories.append(item);
  }
  const changes = $("project-binding-changes"); changes.replaceChildren();
  if (result.changes?.length) changes.append(node("h3", "", "已有记录归属对照"), table([
    {title: "原项目", value: (row) => row.from_project_name || "未归属", wrap: true},
    {title: "归入项目", value: (row) => row.to_project_name || result.project.name, wrap: true},
    {title: "明细", value: (row) => counts(row.detail_count), numeric: true},
    {title: "参考成本 USD", value: (row) => money(row.total_cost_usd), numeric: true},
  ], result.changes));
  const transfers = $("project-binding-transfers"); transfers.replaceChildren();
  for (const transfer of result.transfers || []) transfers.append(node("p", "warning", `目录 ${transfer.path} 将从“${transfer.from_project_name}”整体转入“${result.project.name}”，原项目不再绑定这个目录。`));
  const warnings = $("project-binding-warnings"); warnings.replaceChildren();
  for (const warning of result.warnings || []) warnings.append(node("p", "warning", typeof warning === "string" ? warning : warning.message || warning.code));
  syncProjectActions();
}
async function saveProject() {
  const editor = state.projectEditor;
  if (!editor) throw new Error("请重新打开项目设置。");
  if (editor.applied || editor.uncertain) return applyProjectBinding();
  const draft = projectDraft();
  const request = ++editor.request;
  const active = () => state.projectEditor === editor && editor.request === request && !state.stopped;
  editor.preview = null; editor.signature = null; editor.key = null; editor.stale = false;
  $("project-edit-status").textContent = "正在核对这些目录的全部已有记录与费用…";
  syncProjectActions();
  let result;
  try { result = await api("/api/projects/preview", draft, active); }
  catch (error) { if (!active()) return; $("project-edit-status").textContent = "未能完成影响检查，项目与目录尚未保存。可重试。"; throw error; }
  if (!active()) return;
  editor.preview = result;
  editor.signature = JSON.stringify(draft);
  editor.key = crypto.randomUUID();
  renderProjectBindingImpact(result);
}
async function applyProjectBinding() {
  const editor = state.projectEditor;
  if (!editor?.preview?.preview_id) throw new Error("请重新查看目录关联影响后再确认。");
  const active = () => state.projectEditor === editor && !state.stopped;
  if (!editor.applied) {
    if (editor.signature !== JSON.stringify(projectDraft())) {
      expireProjectBinding();
      throw new Error("项目设置已更改，请重新查看关联影响。");
    }
    editor.submitting = true;
    syncProjectActions();
    let result;
    try { result = await api("/api/projects/apply", {preview_id: editor.preview.preview_id, idempotency_key: editor.key}, active); }
    catch (error) {
      if (!active()) return;
      editor.submitting = false;
      editor.uncertain = !error.code;
      if (editor.uncertain) $("project-binding-caption").textContent = "保存结果尚未确认，请重试确认结果。重试会沿用同一次操作，不会重复创建项目。";
      if (["project_binding_preview_required", "project_binding_preview_expired"].includes(error.code) || editor.stale && !editor.uncertain) expireProjectBinding("台账或目录依据已变化，请重新查看关联影响。");
      syncProjectActions();
      throw error;
    }
    if (!active()) return;
    editor.submitting = false; editor.uncertain = false; editor.applied = true; editor.result = result;
    $("edit-project-id").value = result.project.id;
    invalidate("项目目录已关联，请重新预览");
    invalidateAssociations("目录关联已保存，请刷新项目费用。");
    syncProjectActions();
  }
  try {
    await refreshProjects(active);
    await refreshLedger(active);
    if (state.activePage === "projects") await refreshAssociations(active);
  } catch (error) {
    if (!active()) return;
    $("project-binding-caption").textContent = "项目与目录关联已保存。刷新结果未完成，点击下方按钮重试刷新。";
    syncProjectActions();
    throw new Error(`项目与目录关联已保存，但刷新未完成。${error.message || ""}`);
  }
  if (!active()) return;
  $("project-dialog").close();
  notify("项目与目录已保存，已有记录已整体关联；以后新增用量随同步自动归入。");
}

function associationFilters() {
  const filters = {project_id: $("association-filter-project").value || "unassigned"};
  for (const [field, id] of [["reason", "reason"], ["directory", "directory"], ["session_id", "session"], ["start_date", "start"], ["end_date", "end"]]) {
    const value = $(`association-filter-${id}`).value.trim();
    if (value && value !== "all") filters[field] = value;
  }
  if (filters.start_date && filters.end_date && filters.start_date > filters.end_date) throw new Error("开始日期不能晚于结束日期。");
  return filters;
}
function clearAssociationPreview(close = true) {
  state.associationPreviewRequest += 1;
  state.associationPreview = null;
  if (close && $("association-dialog").open) $("association-dialog").close();
  syncAssociationActions();
}
function clearAssociationSelection() {
  state.associationGeneration += 1;
  state.associationSelected.clear(); state.associationAllFiltered = false;
  $("association-all-filtered").checked = false;
  clearAssociationPreview();
  renderAssociationSelection();
}
function invalidateAssociations(message) {
  expireProjectBinding("台账或目录依据已更新，请重新查看关联影响。");
  clearAssociationSelection();
  state.associationSummaryRequest += 1; state.associationRecordsRequest += 1;
  state.associations = null; state.associationRows = [];
  state.associationPage = 1; state.associationCursor = null; state.associationNextCursor = null; state.associationCursors = [null];
  $("association-overview").hidden = true;
  renderAssociationRecords(); renderProjects();
  $("association-status").textContent = message || "归属依据已更新，请重新查询记录。";
}
function syncAssociationActions() {
  const selected = state.associationAllFiltered || state.associationSelected.size > 0;
  for (const id of ["refresh-associations", "search-associations", "recover-associations"]) $(id).disabled = state.busy || !state.ledger;
  $("preview-assignment").disabled = state.busy || !selected || !$("association-target-project").value;
  $("preview-reclassification").disabled = state.busy || !selected;
  $("clear-association-selection").disabled = state.busy || !selected;
  $("association-prev-page").disabled = state.busy || state.associationPage <= 1;
  $("association-next-page").disabled = state.busy || !state.associationNextCursor;
  const filter = $("association-filter-project").value;
  const includesManaged = state.config.projects.some((project) => project.directory_managed && (filter === "all" || filter === project.id));
  $("association-all-filtered").disabled = state.busy || includesManaged;
  const operation = state.associationPreview;
  const summary = operation?.result?.summary;
  const actionable = operation?.applied || summary && (summary.changed_count > 0 || summary.recovered_sessions > 0 || operation.request.bind_sessions && summary.session_count > 0);
  $("apply-associations").disabled = state.busy || !operation || !actionable;
  $("apply-associations").textContent = operation?.applied ? "刷新已保存结果" : "确认保存归属";
  $("association-reason").readOnly = Boolean(operation?.applied);
  document.querySelectorAll("[data-association-select]").forEach((control) => { control.disabled = state.busy || state.associationAllFiltered || control.getAttribute("data-directory-managed") === "true"; });
  document.querySelectorAll("[data-association-group]").forEach((control) => { control.disabled = state.busy; });
}
function renderAssociationSelection() {
  $("association-selection-description").textContent = state.associationAllFiltered
    ? "已选择当前全部筛选结果，包含其他分页。确切数量和费用以预览为准；取消全选后可逐条选择。"
    : state.associationSelected.size ? `已选择 ${counts(state.associationSelected.size)} 条记录（可跨页），将按完整选择预览。`
      : "选择记录后，先预览影响，再确认归属。";
  syncAssociationActions();
}
async function refreshAssociationOverview(isCurrent = () => true) {
  const active = refreshRequest("associationSummaryRequest", isCurrent);
  const result = await currentResult("/api/project-associations", active);
  if (!active()) return;
  state.associations = result;
  renderAssociationOverview(); renderProjects();
}
function renderAssociationOverview() {
  const result = state.associations;
  const overview = $("association-overview");
  overview.hidden = !result;
  if (!result) return;
  const summary = result.summary || {};
  overview.replaceChildren();
  for (const [label, value, help] of [
    ["已归属明细", counts(summary.assigned_detail_count), "消费与项目关系已保存"],
    ["待归属明细", counts(summary.unassigned_detail_count), `${counts(summary.unassigned_rollup_count)} 行历史日汇总也待分配`],
    ["待归属参考成本", `${money(summary.unassigned_cost_usd)} USD`, "已核实部分，按原消费金额"],
    ["历史依据可恢复", counts(summary.recoverable_detail_count), `${counts(summary.recoverable_sessions)} 个会话可重新关联项目${result.metadata_scan_truncated ? "（已检查部分）" : ""}`],
  ]) {
    const card = node("section", "association-metric");
    card.append(node("span", "field-help", label), node("strong", "", value), node("p", "field-help", help));
    overview.append(card);
  }
  const groups = $("association-groups"); groups.replaceChildren();
  if (!result.groups?.length) {
    groups.append(node("p", "field-help", "当前没有可分组的待归属记录。可查询全部项目，单独调整已确认的历史归属。"));
  }
  for (const group of result.groups || []) {
    const button = node("button", "association-group"); button.type = "button";
    button.setAttribute("data-association-group", ""); button.disabled = state.busy;
    button.append(node("strong", "", associationReasons[group.reason] || "待归属"),
      node("span", "association-group-directory", group.directory || "没有可用的工作目录"),
      node("span", "field-help", `${counts(group.detail_count)} 条明细 · ${counts(group.rollup_count)} 行汇总 · ${money(group.total_cost_usd)} USD`));
    button.addEventListener("click", () => { void run("正在查询待归属记录…", async () => {
      $("association-filter-project").value = "unassigned";
      $("association-filter-reason").value = group.reason;
      $("association-filter-directory").value = group.directory || "";
      $("association-filter-session").value = "";
      AhaForms.sync();
      await refreshAssociations();
    }); });
    groups.append(button);
  }
  if (result.metadata_scan_truncated) groups.append(node("p", "field-help", "目录依据仅检查了部分会话，分组及可恢复数量只包含已检查部分；待归属总量仍为完整台账，可按具体会话继续检查。"));
  else if (result.groups_truncated) groups.append(node("p", "field-help", "原因分组仅展示前 1,000 组；可继续按目录、会话或日期查询完整记录。"));
}
async function refreshAssociationRecords(isCurrent = () => true) {
  const generation = state.associationGeneration;
  const active = refreshRequest("associationRecordsRequest", () => generation === state.associationGeneration && isCurrent());
  const params = new URLSearchParams({...associationFilters(), size: "50"});
  if (state.associationCursor) params.set("cursor", state.associationCursor);
  $("association-status").textContent = "正在读取符合条件的本地记录…";
  let result;
  try { result = await currentResult(`/api/project-associations/records?${params}`, active); }
  catch (error) {
    if (!active()) return;
    $("association-status").textContent = "本次读取未完成，请重新查询；已保存的消费和归属继续保留。";
    throw error;
  }
  if (!active()) return;
  state.associationRows = result.rows || [];
  state.associationNextCursor = result.next_cursor || null;
  renderAssociationRecords();
  $("association-status").textContent = "记录已更新。修改筛选后请重新查询；项目合计与材料按实际保存的归属计算。";
}
async function refreshAssociations(isCurrent = () => true) {
  if (!isCurrent()) return;
  associationFilters();
  clearAssociationSelection();
  state.associationPage = 1; state.associationCursor = null;
  state.associationNextCursor = null; state.associationCursors = [null];
  const generation = state.associationGeneration;
  const active = () => generation === state.associationGeneration && isCurrent() && !state.stopped;
  await Promise.all([refreshAssociationOverview(active), refreshAssociationRecords(active)]);
}
function renderAssociationRecords(focus = null) {
  const rows = state.associationRows;
  const target = $("association-records");
  let focusTarget = null;
  target.replaceChildren();
  if (!rows.length) empty(target, "当前筛选没有记录", "可调整项目、原因、目录或时间，再查询待归属或已确认的历史消费。");
  else {
    const item = node("table"); const head = node("thead"); const header = node("tr");
    const selectCell = node("th", "table-check"); const select = node("input"); select.type = "checkbox";
    select.setAttribute("data-association-select", "");
    const selectableRows = rows.filter((row) => row.assignment_origin !== "directory_binding");
    select.setAttribute("data-directory-managed", String(!selectableRows.length));
    select.checked = state.associationAllFiltered || selectableRows.length > 0 && selectableRows.every((row) => state.associationSelected.has(row.record_key));
    select.disabled = state.busy || state.associationAllFiltered || !selectableRows.length;
    select.setAttribute("aria-label", "选择当前页全部归属记录");
    select.addEventListener("change", () => {
      selectableRows.forEach((row) => select.checked ? state.associationSelected.set(row.record_key, row) : state.associationSelected.delete(row.record_key));
      clearAssociationPreview(); renderAssociationRecords({page: true});
    });
    if (focus?.page) focusTarget = select;
    selectCell.append(select); header.append(selectCell);
    for (const label of ["日期 / 粒度", "当前项目", "目录 / 会话", "待处理原因", "参考成本 USD"]) header.append(node("th", "", label));
    head.append(header); item.append(head); const body = node("tbody");
    for (const row of rows) {
      const selected = state.associationAllFiltered || state.associationSelected.has(row.record_key);
      const line = node("tr", selected ? "selected-row" : "");
      const cell = node("td", "table-check"); const check = node("input"); check.type = "checkbox"; check.checked = selected;
      check.setAttribute("data-association-select", "");
      const managed = row.assignment_origin === "directory_binding";
      check.setAttribute("data-directory-managed", String(managed));
      check.disabled = state.busy || state.associationAllFiltered || managed;
      check.setAttribute("aria-label", `选择 ${row.date || ""} ${row.model || ""} ${row.kind === "rollup" ? "历史日汇总" : "消费明细"}`);
      check.addEventListener("change", () => {
        if (managed) return;
        check.checked ? state.associationSelected.set(row.record_key, row) : state.associationSelected.delete(row.record_key);
        clearAssociationPreview(); renderAssociationRecords({key: row.record_key});
      });
      if (focus?.key === row.record_key) focusTarget = check;
      cell.append(check); line.append(cell);
      const date = node("td", "wrap", row.date || "—");
      date.append(node("span", "subline", row.kind === "rollup" ? `历史日汇总 · 代表 ${counts(row.record_count)} 次消费` : `消费明细 · ${row.model || ""}`));
      const project = node("td", "wrap"); project.append(projectCell(row));
      const basis = node("td", "wrap", row.cwd || "尚无目录依据");
      if (row.session_id) basis.append(node("span", "subline association-session", row.session_id));
      const reason = node("td", "wrap", associationReasons[row.reason] || (row.project_id ? "已确认归属" : "待分配项目"));
      const cost = node("td", "numeric", money(row.total_cost_usd));
      line.append(date, project, basis, reason, cost); body.append(line);
    }
    item.append(body); target.append(item);
  }
  $("association-pagination").hidden = !rows.length && state.associationPage <= 1;
  $("association-page-label").textContent = `第 ${counts(state.associationPage)} 页 · 本页 ${counts(rows.length)} 条。筛选全选包含所有分页。`;
  renderAssociationSelection();
  focusTarget?.focus({preventScroll: true});
}
function associationPreviewRequest(action) {
  const request = {action, filters: associationFilters()};
  if (action !== "recover") {
    if (!state.associationAllFiltered && !state.associationSelected.size) throw new Error("请勾选记录，或选择全部筛选结果。");
    if (!state.associationAllFiltered) request.keys = [...state.associationSelected.keys()];
  }
  if (action === "assign") {
    request.project_id = $("association-target-project").value;
    if (!request.project_id) throw new Error("请选择这些消费所属的项目。");
    request.bind_sessions = $("association-bind-sessions").checked;
  }
  return request;
}
async function previewAssociations(action) {
  const request = associationPreviewRequest(action);
  const generation = state.associationGeneration;
  const sequence = ++state.associationPreviewRequest;
  const active = () => sequence === state.associationPreviewRequest && generation === state.associationGeneration && !state.stopped;
  state.associationPreview = null;
  $("association-dialog-title").textContent = {assign: "预览项目分配", recover: "恢复历史项目关联", reclassify: "重新归属历史消费"}[action];
  $("association-preview-caption").textContent = "正在核对所选记录、项目和费用影响…";
  $("association-preview-summary").replaceChildren(); $("association-preview-projects").replaceChildren(); $("association-preview-warnings").replaceChildren();
  $("association-reason").value = action === "recover" ? "根据 aha 已保存的唯一有效历史目录，恢复消费与项目关联。" : "";
  if (!$("association-dialog").open) $("association-dialog").showModal();
  syncAssociationActions();
  let result;
  try { result = await api("/api/project-associations/preview", request, active); }
  catch (error) { if (!active()) return; $("association-preview-caption").textContent = "预览未完成，可返回调整范围后重试。"; throw error; }
  if (!active()) return;
  state.associationPreview = {result, request, key: null, signature: null, applied: false};
  const summary = result.summary || {};
  $("association-preview-caption").textContent = action === "recover"
    ? "根据已保存的历史依据与当前项目规则重建关联。不能确定项目的记录仍保留待归属。"
    : action === "reclassify" ? "将按当前目录规则追溯调整所选记录。请核对项目和费用影响后确认。"
      : "以下预览包含所选的全部记录，包含跨页选择；确认后保存到项目台账。";
  $("association-preview-summary").append(
    node("p", "", `${counts(summary.selected_detail_count)} 条明细 · ${counts(summary.selected_rollup_count)} 行历史日汇总 · 参考成本 ${money(summary.total_cost_usd)} USD`),
    node("p", "", `预计调整 ${counts(summary.changed_count)} 条记录${summary.recovered_sessions ? `，恢复 ${counts(summary.recovered_sessions)} 个会话目录` : ""}。`));
  if (summary.directory_only_sessions) $("association-preview-summary").append(node("p", "field-help", `${counts(summary.directory_only_sessions)} 个会话仅能恢复目录，项目仍需分配。`));
  if (request.bind_sessions) $("association-preview-summary").append(node("p", "field-help", `已展开到所选 ${counts(summary.session_count)} 个会话的全部现存明细，包含当前筛选以外的成员；后续新增明细也沿用目标项目，已有逐条人工例外保持优先。`));
  if (result.projects?.length) $("association-preview-projects").append(table([
    {title: "目标项目", value: (row) => row.name || row.project_name || "未归属", wrap: true},
    {title: "明细", value: (row) => counts(row.detail_count ?? row.record_count), numeric: true},
    {title: "参考成本 USD", value: (row) => money(row.total_cost_usd), numeric: true},
  ], result.projects));
  for (const warning of result.warnings || []) $("association-preview-warnings").append(node("p", "warning", warning));
  syncAssociationActions();
}
async function applyAssociations() {
  const operation = state.associationPreview;
  if (!operation?.result?.preview_id) throw new Error("请重新预览项目归属后再保存。");
  const reason = $("association-reason").value.trim();
  if (!reason) throw new Error("请说明消费归属或调整的依据。");
  const generation = state.associationGeneration;
  const active = () => state.associationPreview === operation && generation === state.associationGeneration && !state.stopped;
  if (!operation.applied) {
    const body = {preview_id: operation.result.preview_id, reason};
    const signature = JSON.stringify(body);
    if (operation.signature !== signature) { operation.signature = signature; operation.key = crypto.randomUUID(); }
    body.idempotency_key = operation.key;
    invalidate("正在保存项目归属，完成后重新预览");
    operation.analysisGeneration = state.filterGeneration;
    let result;
    try { result = await api("/api/project-associations/apply", body, active); }
    catch (error) {
      if (!active()) return;
      if (["association_preview_expired", "association_preview_required"].includes(error.code)) {
        clearAssociationPreview(false);
        $("association-preview-caption").textContent = "记录或归属依据已变化，请返回重新预览；本次未部分应用。";
      }
      throw error;
    }
    if (!active()) return;
    operation.applied = result.applied === true;
    if (!operation.applied) throw new Error("归属未确认保存，请刷新并重新预览。");
  }
  $("association-preview-caption").textContent = "归属已保存，正在更新项目费用和当前预览…";
  state.associationPage = 1; state.associationCursor = null; state.associationCursors = [null];
  try {
    await Promise.all([refreshLedger(active), refreshProjects(active), refreshAssociationOverview(active), refreshAssociationRecords(active)]);
    if (!active()) return;
    if (operation.analysisGeneration === state.filterGeneration && state.ledger) await analyze();
    if (!active()) return;
  } catch (error) {
    if (!active()) return;
    syncAssociationActions();
    throw new Error(`归属已保存，但刷新未完成。可点击“刷新已保存结果”重试。${error.message || ""}`);
  }
  clearAssociationSelection(); renderAssociationRecords();
  notify("已保存项目归属，并更新项目费用与当前预览。");
}

function renderAssignmentCoverage(result) {
  const coverage = result.assignment_coverage;
  $("assignment-coverage-note").hidden = !coverage || coverage.status !== "incomplete";
  if (coverage?.status !== "incomplete") return;
  $("assignment-coverage-description").textContent = `同期间还有 ${counts(coverage.unassigned_detail_count)} 条明细、${counts(coverage.unassigned_rollup_count)} 行历史日汇总待归属，已核实参考成本 ${money(coverage.unassigned_cost_usd)} USD。当前项目仅统计已确认归属的消费，可继续处理待归属记录。`;
}
async function analyze() {
  if (!state.ledger) throw new Error("请先加载本地资料。");
  state.syncPreviewPending = false;
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
  renderEmptyRange(result);
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
  renderAssignmentCoverage(result);
  $("token-input").textContent = counts(summary.fresh_input_tokens);
  $("token-output").textContent = counts(summary.output_tokens);
  $("token-read").textContent = counts(summary.cache_read_tokens);
  $("token-write").textContent = counts(summary.cache_creation_tokens);
  $("token-strip").hidden = omittedOnly;
  const coverage = result.metadata_coverage || state.ledger.metadata_coverage || {matched_sessions: 0, total_sessions: 0};
  $("coverage-note").textContent = `已识别 ${counts(coverage.matched_sessions)} / ${counts(coverage.total_sessions)} 个会话的工作目录。项目按已确认的工作目录整体关联。`;
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
  const canSelect = (row) => !row.cwd && row.assignment_origin !== "directory_binding";
  const selectableRows = selectable ? rows.filter(canSelect) : [];
  const item = node("table"); const head = node("thead"); const tr = node("tr");
  if (selectable) {
    const cell = node("th", "table-check"); const check = node("input");
    check.type = "checkbox"; check.setAttribute("aria-label", "选择当前页全部无目录记录");
    check.setAttribute("data-usage-select", ""); check.setAttribute("data-unselectable", String(!selectableRows.length));
    check.disabled = state.busy || !selectableRows.length;
    check.checked = selectableRows.length > 0 && selectableRows.every((row) => state.selected.has(row.record_key));
    check.addEventListener("change", () => {
      selectableRows.forEach((row) => check.checked ? state.selected.set(row.record_key, row) : state.selected.delete(row.record_key));
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
      check.setAttribute("data-usage-select", ""); check.setAttribute("data-unselectable", String(!canSelect(row)));
      check.disabled = state.busy || !canSelect(row);
      check.setAttribute("aria-label", `选择 ${row.time || row.date} ${row.model} 记录`);
      check.addEventListener("change", () => {
        if (!canSelect(row)) return;
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
  $("preview-table").replaceChildren(table(columns, state.rows, $("usage-legacy-tools").open));
}
function renderSelection() {
  $("assignment-bar").hidden = !$("usage-legacy-tools").open || !state.selected.size;
  $("selection-count").textContent = `已选 ${counts(state.selected.size)} 条${state.tab === "rollups" ? "完整日汇总" : "明细"}`;
  $("session-scope-label").hidden = state.tab !== "details";
  renderAssignmentMode();
  syncActions();
}
function renderAssignmentMode() {
  const sessionScope = state.tab === "details" && $("session-scope").checked;
  const hasTarget = Boolean($("assignment-project").value);
  const empty = [...$("assignment-project").options].find((option) => option.value === "");
  if (empty) empty.textContent = sessionScope ? "解除会话默认（历史归属保留）" : "取消逐条人工例外";
  $("assign").textContent = hasTarget ? "分配项目" : sessionScope ? "解除会话默认" : "取消逐条例外";
  $("assignment-mode-description").textContent = hasTarget
    ? sessionScope ? "分配所选会话的全部现存明细及后续新增明细；有效的逐条人工例外保留。" : "仅对已选记录设置人工项目例外；后续新增消费沿用其会话默认或目录规则。"
    : sessionScope ? "只解除会话的后续默认，已确认的历史归属保留。需要追溯调整时，请到项目管理中单独预览。" : "取消所选记录的逐条人工例外，返回已保存的项目归属依据。";
  AhaForms.sync();
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
  invalidateAssociations("人工归属已更新，请刷新项目费用。");
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
  invalidateAssociations("目录依据已更新，请重新检查待归属记录。");
  await Promise.all([refreshLedger(), refreshProjects()]);
  invalidate("目录依据已更新，请重新预览");
  $("source-dialog").close(); notify("已更新目录识别。");
}
function renderEmptyRange(result) {
  const coverage = state.ledger?.coverage;
  const show = !hasUsage(result.summary) && result.time_coverage?.complete !== false && coverage?.start_date;
  $("empty-range-note").hidden = !show;
  if (show) $("empty-range-description").textContent = `当前筛选没有可计入的用量。历史数据仍保留，覆盖 ${coverage.start_date} 至 ${coverage.end_date}；同步失败也不会清空这些历史。`;
}
async function viewAllHistory() {
  $("project-select").value = "all";
  $("availability-mode").value = "all";
  AhaForms.sync();
  timeRange.setIntent({kind: "preset", preset: "all", follow_now: false});
  await analyze();
  notify("已显示全部历史。需要申请报销时，请切换到“可用用量”。", "info");
}
async function openSourceBinding(location = "", continuation = {path: "/api/sync", body: {}}) {
  const request = ++state.bindingRequest;
  const isCurrent = () => request === state.bindingRequest && !state.stopped;
  const binding = await api(`/api/source/binding${location ? `?path=${encodeURIComponent(location)}` : ""}`, undefined, isCurrent);
  if (!isCurrent()) return true;
  if (!location) state.sourceBinding = binding;
  if (!binding.required) return false;
  state.bindingSelection = {location, continuation, request};
  $("source-binding-description").textContent = binding.message || "原台账及项目完整保留。将当前 CC Switch 作为新来源接续，相同消费不重复计入，不同历史值保留供核对。";
  $("source-binding-reason").value = "将当前 CC Switch 作为新来源接续，保留已保存的历史资料。";
  $("source-dialog").close();
  if (!$("source-binding-dialog").open) $("source-binding-dialog").showModal();
  renderSource();
  return true;
}
async function saveSourceBinding() {
  const selection = state.bindingSelection;
  if (!selection) throw new Error("请重新选择本机来源。");
  const reason = $("source-binding-reason").value.trim();
  if (!reason) throw new Error("请填写接续说明。");
  const result = await api("/api/source/binding", {path: selection.location, reason});
  if (selection !== state.bindingSelection || state.stopped) return;
  if (!selection.location) state.sourceBinding = {...result, required: false};
  state.bindingSelection = null;
  $("source-binding-dialog").close();
  invalidate("已确认本机来源，正在接续用量");
  renderSource();
  await loadSource(selection.continuation.path, selection.continuation.body);
}
function backupActive(generation) { return generation === state.backupGeneration && !state.stopped; }
function backupProgress(message, percentage = null) {
  $("backup-progress").hidden = false;
  $("backup-progress-text").textContent = message;
  if (percentage === null) $("backup-progress-bar").removeAttribute("value");
  else $("backup-progress-bar").value = percentage;
}
function renderBackupResult(job) {
  const target = $("backup-result"); target.replaceChildren(); target.hidden = false;
  if (job.status === "cancelled") {
    target.append(node("p", "", "此次操作已取消，当前台账保持不变。")); return;
  }
  if (job.kind === "backup") {
    target.append(node("strong", "", "完整备份已生成，请下载保存"),
      node("p", "", "下载后请保存到你的备份位置。退出程序前完成下载。"),
      actionButton("下载完整备份", () => { void downloadBackup(job.id).catch((error) => notify(error.message, "error")); }, "button primary"));
  } else {
    target.append(node("strong", "", "已还原到新目录，当前台账未被替换"),
      node("p", "path-output", job.result.destination),
      actionButton("打开还原台账", () => run("正在打开还原台账…", async () => {
        const result = await api(`/api/backups/${encodeURIComponent(job.id)}/open`, {});
        notify(result.message, "info");
      }), "button primary"),
      node("p", "field-help", "请在新打开的页面确认本机来源，再接续当前电脑的用量。默认双击程序仍打开原资料目录；下次继续使用还原台账，可运行以下打开命令。"));
    if (job.result.open_command) target.append(node("code", "path-output", job.result.open_command),
      actionButton("复制打开命令", () => {
        if (!navigator.clipboard?.writeText) { notify("请选择上方打开命令，手动复制后使用。", "info"); return; }
        void navigator.clipboard.writeText(job.result.open_command).then(() => notify("打开命令已复制。"))
          .catch(() => notify("请选中打开命令，手动复制后使用。", "info"));
      }));
  }
}
async function downloadBackup(id) {
  const path = `/api/backups/${encodeURIComponent(id)}/download`;
  let response;
  try { response = await fetch(path, {method: "HEAD", credentials: "same-origin", cache: "no-store"}); }
  catch { throw new Error("连接中断，完整备份尚未下载，请重试。"); }
  if (!response.ok) throw new Error("此完整备份暂时无法下载，请重新生成或重试。");
  const anchor = node("a"); anchor.href = path; anchor.download = "";
  document.body.append(anchor); anchor.click(); anchor.remove();
}
async function watchBackup(job, generation) {
  if (!backupActive(generation)) return;
  state.backupJob = job;
  while (backupActive(generation) && job.status === "running") {
    backupProgress(job.kind === "backup" ? "正在生成并校验完整备份…" : "正在校验备份并还原到新目录…");
    await new Promise((resolve) => setTimeout(resolve, 450));
    if (!backupActive(generation)) return;
    job = await api(`/api/backups/${encodeURIComponent(job.id)}`, undefined, () => backupActive(generation));
    if (!backupActive(generation)) return;
    state.backupJob = job;
  }
  if (!backupActive(generation)) return;
  if (job.status === "failed") throw new Error(job.message || "备份或还原未完成，当前台账保持不变。");
  renderBackupResult(job);
  notify(job.status === "cancelled" ? "此次备份或还原已取消。" : job.kind === "backup" ? "完整备份已生成，请下载保存。" : "已还原到独立新目录。", "info");
}
function finishBackupOperation(generation) {
  if (!backupActive(generation)) return;
  state.backupBusy = false; state.backupController = null;
  $("backup-progress").hidden = true; syncActions();
}
async function createFullBackup() {
  if (state.backupBusy || state.stopped) return;
  const generation = ++state.backupGeneration;
  state.backupBusy = true; state.backupJob = null; state.backupUpload = null;
  clearFeedback(); $("backup-result").hidden = true;
  backupProgress("正在准备完整备份…"); syncActions();
  try {
    const job = await api("/api/backups", {});
    if (!backupActive(generation)) { void api(`/api/backups/${encodeURIComponent(job.id)}/cancel`, {}).catch(() => {}); return; }
    await watchBackup(job, generation);
  } catch (error) { if (backupActive(generation)) notify(error.message, "error"); }
  finally { finishBackupOperation(generation); }
}
async function uploadBackupChunk(id, offset, chunk, signal) {
  let response;
  try {
    response = await fetch(`/api/restore-uploads/${encodeURIComponent(id)}/chunks`, {
      method: "POST", credentials: "same-origin", cache: "no-store", signal,
      headers: {"Content-Type": "application/octet-stream", "X-AHA-CSRF": state.csrf, "X-AHA-Upload-Offset": String(offset)},
      body: chunk,
    });
  } catch (error) {
    if (error.name === "AbortError") throw error;
    throw new Error("备份上传中断，当前台账未被修改，请重试。");
  }
  let result;
  try { result = await response.json(); }
  catch { throw new Error("无法读取备份上传结果，请重新上传。"); }
  if (!response.ok) throw new Error(result.message || "备份上传未完成，请重试。");
  return result;
}
async function restoreFullBackup() {
  if (state.backupBusy || state.stopped) return;
  const file = $("restore-file").files?.[0];
  if (!file) { notify("请选择完整 aha 备份文件。", "error"); return; }
  if (!file.size || file.size > state.backupLimits.archive_bytes) { notify("完整备份包大小无效或超过 4 GiB。", "error"); return; }
  const destination = $("restore-destination").value.trim();
  const generation = ++state.backupGeneration;
  state.backupBusy = true; state.backupJob = null; state.backupUpload = null;
  const controller = new AbortController(); state.backupController = controller;
  clearFeedback(); $("backup-result").hidden = true;
  backupProgress("正在准备上传完整备份…", 0); syncActions();
  let upload;
  try {
    upload = await api("/api/restore-uploads", {size: file.size});
    if (!backupActive(generation)) { void api(`/api/restore-uploads/${encodeURIComponent(upload.id)}/cancel`, {}).catch(() => {}); return; }
    state.backupUpload = upload.id;
    const chunkBytes = Math.min(upload.chunk_bytes, state.backupLimits.chunk_bytes);
    for (let offset = 0; offset < file.size;) {
      const chunk = file.slice(offset, Math.min(file.size, offset + chunkBytes));
      const result = await uploadBackupChunk(upload.id, offset, chunk, controller.signal);
      if (!backupActive(generation)) return;
      const expected = offset + chunk.size;
      if (result.received !== expected) throw new Error("备份上传进度不一致，请重新上传。");
      offset = result.received;
      backupProgress(`正在上传完整备份：${Math.floor(offset / file.size * 100)}%`, offset / file.size * 100);
    }
    const job = await api(`/api/restore-uploads/${encodeURIComponent(upload.id)}/restore`, {destination});
    if (!backupActive(generation)) { void api(`/api/backups/${encodeURIComponent(job.id)}/cancel`, {}).catch(() => {}); return; }
    state.backupUpload = null;
    await watchBackup(job, generation);
  } catch (error) {
    if (upload && !state.backupJob) void api(`/api/restore-uploads/${encodeURIComponent(upload.id)}/cancel`, {}).catch(() => {});
    if (backupActive(generation) && error.name !== "AbortError") notify(error.message, "error");
  } finally { finishBackupOperation(generation); }
}
async function cancelBackupOperation() {
  if (!state.backupBusy || state.stopped) return;
  const job = state.backupJob, upload = state.backupUpload;
  const generation = ++state.backupGeneration;
  state.backupController?.abort(); state.backupUpload = null;
  backupProgress("正在取消此次操作…");
  try {
    const result = job ? await api(`/api/backups/${encodeURIComponent(job.id)}/cancel`, {})
      : upload ? await api(`/api/restore-uploads/${encodeURIComponent(upload)}/cancel`, {}) : {status: "cancelled"};
    if (!backupActive(generation)) return;
    if (result.kind) await watchBackup(result, generation);
    else renderBackupResult({status: "cancelled"});
  } catch (error) { if (backupActive(generation)) notify(error.message, "error"); }
  finally { finishBackupOperation(generation); }
}
function renderUnfinishedUploads() {
  $("unfinished-uploads").hidden = !state.pendingBackupUploads.length;
}
async function clearUnfinishedUploads() {
  for (const upload of state.pendingBackupUploads) await api(`/api/restore-uploads/${encodeURIComponent(upload.id)}/cancel`, {});
  state.pendingBackupUploads = []; renderUnfinishedUploads();
  notify("未完成的上传已清理，当前台账保持不变。");
}
async function openBackupDialog() {
  clearFeedback(); $("backup-dialog").showModal();
  $("backup-data-directory").textContent = state.dataDirectory;
  if (state.backupJob?.status === "completed") renderBackupResult(state.backupJob);
  syncActions();
  const generation = state.backupGeneration;
  const isCurrent = () => generation === state.backupGeneration && $("backup-dialog").open && !state.stopped;
  try {
    const status = await api("/api/status", undefined, isCurrent);
    if (!isCurrent()) return;
    state.pendingBackupUploads = (status.restore_uploads || []).filter((item) => item.id !== state.backupUpload);
    renderUnfinishedUploads();
    if (!state.backupBusy && status.backup) {
      state.backupJob = status.backup;
      if (status.backup.status === "running") {
        state.backupBusy = true; const resumed = ++state.backupGeneration;
        void watchBackup(status.backup, resumed).catch((error) => {
          if (backupActive(resumed)) notify(error.message, "error");
        }).finally(() => finishBackupOperation(resumed));
      } else if (status.backup.status === "completed") renderBackupResult(status.backup);
    }
    syncActions();
  } catch (error) { if (isCurrent()) notify(error.message, "error"); }
}
async function initialize() {
  const status = await api("/api/status");
  state.csrf = status.csrf_token; state.today = status.today; state.now = status.now; state.ledger = status.ledger;
  state.sourceBinding = status.default_source?.binding || null;
  state.dataDirectory = status.data_directory || "";
  state.backupLimits = status.backup_limits || state.backupLimits;
  $("source-data-directory").textContent = state.dataDirectory;
  $("backup-data-directory").textContent = state.dataDirectory;
  state.backupJob = status.backup || null;
  state.pendingBackupUploads = status.restore_uploads || []; renderUnfinishedUploads();
  if (state.backupJob?.status === "running") {
    state.backupBusy = true;
    const generation = ++state.backupGeneration;
    void watchBackup(state.backupJob, generation).catch((error) => {
      if (backupActive(generation)) notify(error.message, "error");
    }).finally(() => finishBackupOperation(generation));
  }
  const currentSync = status.sync || status.startup_sync;
  const initialSyncGeneration = state.syncGeneration;
  state.sync = currentSync || null; state.syncBusy = syncStatus(currentSync) === "running";
  $("app-version").textContent = `v${status.version}`;
  renderSource();
  if (currentSync?.status === "running") {
    const generation = ++state.syncGeneration;
    void watchSync(currentSync, generation).catch((error) => {
      if (generation !== state.syncGeneration || state.stopped) return;
      state.syncBusy = false; handleSyncError(error); renderSource(); refreshPendingSyncPreview();
    });
  }
  await Promise.all([refreshProjects(), refreshReconciliations(), refreshBatches()]);
  await analyze();
  if (!currentSync && !state.sourceBinding?.required && initialSyncGeneration === state.syncGeneration) {
    void loadSource("/api/sync", {trigger: "startup"});
  }
}
async function openReconciliations() {
  await refreshReconciliations(); renderReconciliations(); $("reconciliation-dialog").showModal();
}
async function resolveReconciliation(entry, choice, reason) {
  invalidate("正在保存核对依据，完成后重新预览");
  const generation = state.filterGeneration;
  const isCurrent = () => generation === state.filterGeneration && !state.stopped;
  let previewStarted = false;
  try {
    await api(`/api/reconciliations/${encodeURIComponent(entry.id)}`, {choice, reason,
      expected_generation: entry.generation, idempotency_key: crypto.randomUUID()}, isCurrent);
    if (isCurrent()) invalidateAssociations("核对结果已保存，请重新检查记录归属。");
    await Promise.all([refreshLedger(isCurrent), refreshProjects(isCurrent), refreshReconciliations(isCurrent)]);
    if (!isCurrent()) return;
    renderReconciliations();
    previewStarted = true;
    await analyze();
    const focus = $("reconciliation-list").querySelector?.('[role="combobox"]:not([disabled]),select:not([hidden]):not([disabled]),button:not([disabled])')
      || $("reconciliation-dialog").querySelector?.("[data-close]");
    if ($("reconciliation-dialog").open && !state.stopped) focus?.focus?.();
  } catch (error) { if (previewStarted || isCurrent() || error.invalidated) throw error; }
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
    if (entry.type === "directory") {
      facts.append(node("p", "", `已保存目录：${entry.current_cwd || "未提供"}`),
        node("p", "", `本次目录：${entry.candidate_cwd || (entry.candidate_status === "conflict" ? "存在多个不同目录，尚无法确定" : "当前电脑未找到唯一目录")}`));
    }
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
      const label = entry.type === "source" && value === "current" ? "确认此来源，保留本地历史"
        : entry.type === "rollup_origin" && value === "current" ? "确认重叠，保留历史汇总"
        : entry.type === "directory" ? (value === "candidate" ? "采用当前电脑目录" : "保留已保存目录")
        : choiceLabels[value] || choice.label || "确认来源关系";
      const option = node("option", "", label); option.value = value; select.append(option);
    }
    selectLabel.append(select);
    const reasonLabel = node("label", "field", "核对说明"); const reason = node("textarea"); reason.rows = 2; reason.maxLength = 4000; reason.required = true; reasonLabel.append(reason);
    const submit = node("button", "button primary", "确认依据"); submit.type = "submit"; submit.disabled = !select.options.length;
    form.append(selectLabel, reasonLabel, submit);
    form.addEventListener("submit", (event) => { event.preventDefault(); void run("正在保存核对结果…", () => resolveReconciliation(entry, select.value, reason.value)); });
    card.append(form); target.append(card);
    AhaForms.mount(card);
  }
}
document.querySelectorAll("[data-page]").forEach((button) => button.addEventListener("click", () => {
  page(button.dataset.page);
  if (button.dataset.page === "projects") void run("正在读取项目费用与归属…", refreshAssociations);
}));
document.querySelectorAll("[data-close]").forEach((button) => button.addEventListener("click", () => $(button.dataset.close).close()));
for (const id of ["project-select", "availability-mode"]) $(id).addEventListener("change", () => invalidate());
$("source-options").addEventListener("click", () => { clearFeedback(); $("source-dialog").showModal(); });
$("backup-options").addEventListener("click", openBackupDialog);
$("create-full-backup").addEventListener("click", () => { void createFullBackup(); });
$("restore-form").addEventListener("submit", (event) => { event.preventDefault(); void restoreFullBackup(); });
$("cancel-backup").addEventListener("click", () => { void cancelBackupOperation(); });
$("clear-unfinished-uploads").addEventListener("click", () => run("正在清理未完成上传…", clearUnfinishedUploads));
$("source-binding-form").addEventListener("submit", (event) => { event.preventDefault(); void run("正在确认本机来源…", saveSourceBinding); });
$("source-binding-dialog").addEventListener("close", () => { state.bindingSelection = null; state.bindingRequest += 1; });
$("bind-default-source").addEventListener("click", () => run("正在读取本机来源…", () => openSourceBinding()));
$("view-all-history").addEventListener("click", () => run("正在查询全部历史…", viewAllHistory));
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
$("project-form").addEventListener("submit", (event) => { event.preventDefault(); if (!$("project-editor").hidden) void run("正在检查目录关联影响…", saveProject); });
for (const id of ["edit-project-name", "edit-project-description", "edit-project-directories", "project-candidates"]) $(id).addEventListener("input", () => expireProjectBinding());
$("project-candidates").addEventListener("change", () => expireProjectBinding());
$("back-project-editor").addEventListener("click", () => { expireProjectBinding(); $("preview-project-binding").focus({preventScroll: true}); });
$("apply-project-binding").addEventListener("click", () => { void run("正在保存目录关联…", applyProjectBinding); });
$("project-dialog").addEventListener("close", () => {
  const trigger = state.projectEditor?.trigger;
  state.projectEditor = null; state.projectGeneration += 1; syncProjectActions();
  if (trigger?.isConnected && !trigger.disabled) trigger.focus({preventScroll: true});
});
$("usage-legacy-tools").addEventListener("toggle", () => {
  state.selected.clear();
  if (["details", "rollups"].includes(state.tab) && state.rows.length) renderRowTable();
  renderSelection();
});
$("refresh-associations").addEventListener("click", () => run("正在读取项目费用与归属…", refreshAssociations));
$("association-filter-form").addEventListener("submit", (event) => { event.preventDefault(); void run("正在查询消费记录…", refreshAssociations); });
for (const id of ["project", "reason", "directory", "session", "start", "end"]) $("association-filter-" + id).addEventListener("change", () => {
  clearAssociationSelection();
  state.associationRows = []; state.associationPage = 1; state.associationCursor = null; state.associationNextCursor = null;
  renderAssociationRecords();
  $("association-status").textContent = "筛选已更改，请查询记录。全选和预览将使用新的筛选条件。";
});
for (const id of ["association-target-project", "association-bind-sessions"]) $(id).addEventListener("change", () => clearAssociationPreview());
$("association-all-filtered").addEventListener("change", () => {
  state.associationAllFiltered = $("association-all-filtered").checked;
  state.associationSelected.clear(); clearAssociationPreview(); renderAssociationRecords();
});
$("clear-association-selection").addEventListener("click", () => { clearAssociationSelection(); renderAssociationRecords(); });
$("preview-assignment").addEventListener("click", () => run("正在预览项目分配…", () => previewAssociations("assign")));
$("preview-reclassification").addEventListener("click", () => run("正在核对历史归属影响…", () => previewAssociations("reclassify")));
$("recover-associations").addEventListener("click", () => run("正在检查历史依据…", () => previewAssociations("recover")));
$("association-dialog").addEventListener("close", () => clearAssociationPreview(false));
$("association-apply-form").addEventListener("submit", (event) => { event.preventDefault(); void run("正在保存项目归属…", applyAssociations); });
$("association-prev-page").addEventListener("click", () => run("正在读取上一页…", async () => {
  if (state.associationPage <= 1) return;
  state.associationPage -= 1; state.associationCursor = state.associationCursors[state.associationPage - 1] || null;
  await refreshAssociationRecords();
}));
$("association-next-page").addEventListener("click", () => run("正在读取下一页…", async () => {
  if (!state.associationNextCursor) return;
  state.associationCursor = state.associationNextCursor;
  state.associationCursors[state.associationPage] = state.associationCursor; state.associationPage += 1;
  await refreshAssociationRecords();
}));
$("manage-unassigned").addEventListener("click", () => run("正在查询待归属记录…", async () => {
  $("association-filter-project").value = "unassigned"; $("association-filter-reason").value = "all";
  $("association-filter-directory").value = ""; $("association-filter-session").value = "";
  $("association-filter-start").value = state.analysis?.start_date || "";
  $("association-filter-end").value = state.analysis?.end_date || "";
  AhaForms.sync(); page("projects"); $("association-advanced").open = true; await refreshAssociations();
  $("association-heading").focus?.({preventScroll: true});
  $("association-panel").scrollIntoView?.({behavior: "smooth", block: "start"});
}));

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
$("session-scope").addEventListener("change", renderAssignmentMode);
$("assignment-project").addEventListener("change", renderAssignmentMode);
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
