"use strict";

const $ = (id) => document.getElementById(id);
const state = {
  csrf: "", today: "", captures: [], capture: null, currentCaptureId: null,
  config: {revision: 0, projects: []}, analysis: null, tab: "daily", page: 1,
  rows: [], total: 0, selected: new Map(), batches: [], batch: null,
  busy: false, pendingBatch: null, revision: null, lifecycle: null, noticeTimer: null, stopped: false,
};
const labels = {draft: "草稿", submitted: "已提交", reimbursed: "已报销", voided: "已作废", legacy_review: "待核对"};
const origins = {manual: "手动分配", directory_rule: "目录匹配", unassigned: "未归属"};
const counts = (value) => new Intl.NumberFormat("zh-CN").format(value ?? 0);
const money = (value) => String(value ?? "0").replace(/(\.\d*?[1-9])0+$|\.0+$/, "$1");
const lines = (value) => value.split(/\r?\n/).map((part) => part.trim()).filter(Boolean);

function node(tag, className, text) {
  const item = document.createElement(tag);
  if (className) item.className = className;
  if (text !== undefined && text !== null) item.textContent = String(text);
  return item;
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
async function api(path, body) {
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
    if (["analysis_expired", "classification_changed", "availability_changed", "usage_claimed"].includes(error.code)) {
      invalidate("用量已变化，请更新预览");
      if (state.revision && $("revision-basis").value === "current") {
        state.revision.analysis = null;
        $("revision-preview").replaceChildren(node("p", "", "用量已变化，请点击“更新用量”。"));
        syncActions();
      }
    }
    throw error;
  }
  return result;
}
async function run(label, action) {
  if (state.busy) return;
  clearFeedback();
  state.busy = true;
  $("busy-label").textContent = label;
  $("busy").hidden = false;
  const controls = [...document.querySelectorAll("button,input,textarea,select")];
  const previous = controls.map((control) => control.disabled);
  controls.forEach((control) => { control.disabled = true; });
  try { await action(); }
  catch (error) { notify(error.message || "操作未完成，请重试。", "error"); }
  finally {
    controls.forEach((control, index) => { control.disabled = previous[index]; });
    state.busy = false;
    $("busy").hidden = true;
    syncActions();
  }
}
function syncActions() {
  if (state.stopped) {
    document.querySelectorAll("button,input,textarea,select").forEach((control) => { control.disabled = true; });
    return;
  }
  $("analyze").disabled = state.busy || !state.capture;
  $("view-details").disabled = state.busy || !state.analysis;
  $("create-batch").disabled = state.busy || !state.analysis || state.analysis.availability_mode !== "available" || Boolean(state.analysis.target_batch_id) || !state.analysis.summary.record_count;
  $("refresh-availability").disabled = state.busy || !state.capture;
  $("save-revision").disabled = state.busy || !state.revision || ($("revision-basis").value === "current" && (!state.revision.analysis || !state.revision.analysis.summary.record_count));
  $("refresh-metadata").disabled = state.busy || !state.capture;
  $("scan-metadata").disabled = state.busy || !state.capture;
  $("assign").disabled = state.busy || state.selected.size === 0;
  $("prev-page").disabled = state.busy || state.page <= 1;
  $("next-page").disabled = state.busy || state.page * 50 >= state.total;
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
  if (state.analysis && ["claim-purpose", "claim-amount", "claim-note"].some((id) => $(id).value.trim())) {
    $("claim-explanation").textContent = "用量范围已变化，请核对用途和金额后保存。";
  }
  state.analysis = null;
  state.pendingBatch = null;
  state.selected.clear();
  state.rows = [];
  state.page = 1;
  ["metric-cost", "metric-count", "metric-tokens", "metric-unassigned"].forEach((id) => { $(id).textContent = "—"; });
  $("availability-panel").hidden = true;
  $("token-strip").hidden = true;
  $("coverage-note").hidden = true;
  $("analysis-warnings").replaceChildren();
  $("pagination").hidden = true;
  $("assignment-bar").hidden = true;
  $("filter-status").textContent = message;
  $("preview-caption").textContent = "选择条件后更新预览。";
  empty($("preview-table"), state.capture ? "请更新预览" : "尚未加载用量",
    state.capture ? "按所选项目和日期查看用量。" : "读取 CC Switch 数据，或导入备份。");
  syncActions();
}
function range(name) {
  const today = state.today;
  if (!today) return;
  $("end-date").value = today;
  if (name === "today") $("start-date").value = today;
  if (name === "month") $("start-date").value = `${today.slice(0, 7)}-01`;
  if (name === "week") {
    const date = new Date(`${today}T12:00:00+08:00`);
    date.setUTCDate(date.getUTCDate() - 6);
    $("start-date").value = date.toISOString().slice(0, 10);
  }
  document.querySelectorAll("[data-range]").forEach((item) => { item.classList.toggle("active", item.dataset.range === name); });
  $("range-all").classList.remove("active");
  invalidate();
}
function renderCaptures() {
  const select = $("capture-select");
  const options = state.captures.map((capture) => {
    const current = capture.id === state.currentCaptureId;
    const option = node("option", "", `${current ? "本次读取" : "历史快照"} · ${capture.source?.name || "用量数据"} · ${dateTime(capture.created_at)}`);
    option.value = capture.id;
    return option;
  });
  if (!options.length) {
    const option = node("option", "", "请先加载用量"); option.value = ""; options.push(option);
  }
  select.replaceChildren(...options);
  select.value = state.capture?.id || "";
  if (select.selectedIndex < 0) select.selectedIndex = 0;
}
function renderSource() {
  const capture = state.capture;
  if (!capture) {
    $("source-name").textContent = "尚未加载用量";
    $("source-mode").textContent = "待选择来源";
    $("source-description").textContent = "读取 CC Switch 数据，或导入备份。";
  } else {
    $("source-name").textContent = capture.source?.name || "用量数据";
    $("source-mode").textContent = capture.id === state.currentCaptureId ? "本次读取" : "历史快照";
    const amount = capture.counts || {};
    const coverage = capture.coverage || {};
    const period = coverage.start_date ? ` · ${coverage.start_date} 至 ${coverage.end_date}` : "";
    $("source-description").textContent = `${dateTime(capture.created_at)} 读取 · ${counts(amount.detail_count)} 条明细 · ${counts(amount.rollup_count)} 条历史日汇总${period}`;
  }
  renderCaptures(); renderDirectories();
}
async function refreshCaptures() {
  state.captures = (await api("/api/captures")).captures;
  renderCaptures();
}
async function selectCapture(id) {
  invalidate("正在加载数据快照");
  state.capture = null;
  try {
    state.capture = await api(`/api/captures/${encodeURIComponent(id)}`);
    renderSource(); invalidate("已选择数据快照，请更新预览");
  } catch (error) {
    renderSource(); invalidate("数据快照加载失败，请选择其他来源"); throw error;
  }
}
async function loadSource(path, body) {
  state.capture = null; state.currentCaptureId = null;
  renderSource(); invalidate("正在加载用量");
  try {
    const capture = await api(path, body);
    state.capture = capture; state.currentCaptureId = capture.id;
    await refreshCaptures(); renderSource();
    $("source-dialog").close();
    notify("已加载用量。");
    await analyze();
  } catch (error) {
    state.capture = null; renderSource(); invalidate("加载失败，请检查文件或选择其他备份"); throw error;
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
  const directories = state.capture?.directories || [];
  const coverage = state.capture?.metadata_coverage;
  $("directory-summary").textContent = coverage
    ? `已识别 ${counts(coverage.matched_sessions)} / ${counts(coverage.total_sessions)} 个会话，共 ${counts(directories.length)} 个工作目录。`
    : "加载用量后显示工作目录。";
  const target = $("directory-list"); target.replaceChildren();
  for (const directory of directories) {
    const row = node("div", "directory-row");
    row.append(node("code", "", directory.path), node("span", "", `${counts(directory.session_count)} 个会话 · ${counts(directory.detail_count)} 条明细`));
    target.append(row);
  }
  const unresolved = state.capture?.unresolved_sessions || [];
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
  for (const candidate of state.capture?.directories || []) {
    known.add(candidate.path);
    const label = node("label", "candidate-item");
    const check = node("input"); check.type = "checkbox"; check.value = candidate.path;
    check.checked = selected.has(candidate.path);
    const text = node("span");
    text.append(node("code", "", candidate.path), node("small", "", `${counts(candidate.session_count)} 个会话 · ${counts(candidate.detail_count)} 条明细`));
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
  if (!state.capture) throw new Error("请先加载用量。");
  const result = await api("/api/analysis", {
    capture_id: state.capture.id, classification_revision: state.config.revision,
    start_date: $("start-date").value, end_date: $("end-date").value,
    project_id: $("project-select").value, availability_mode: $("availability-mode").value,
  });
  state.analysis = result; state.page = 1; state.selected.clear();
  renderAvailability(result);
  const summary = result.summary;
  const availableOnly = result.availability_mode === "available";
  $("metric-cost-label").textContent = availableOnly ? "可用参考成本" : "期间参考成本";
  $("metric-count-label").textContent = availableOnly ? "可用用量" : "用量记录数";
  $("metric-token-label").textContent = availableOnly ? "可用 Token" : "总 Token";
  $("metric-cost").textContent = money(summary.total_cost_usd);
  $("metric-count").textContent = counts(summary.record_count);
  $("metric-count-note").textContent = `${counts(summary.detail_count)} 条明细 + ${counts(summary.rollup_record_count)} 条历史代表记录`;
  $("metric-tokens").textContent = counts(summary.total_tokens);
  $("metric-unassigned").textContent = counts(result.unassigned_count);
  $("token-input").textContent = counts(summary.fresh_input_tokens);
  $("token-output").textContent = counts(summary.output_tokens);
  $("token-read").textContent = counts(summary.cache_read_tokens);
  $("token-write").textContent = counts(summary.cache_creation_tokens);
  $("token-strip").hidden = false;
  const coverage = result.metadata_coverage;
  $("coverage-note").textContent = `已识别 ${counts(coverage.matched_sessions)} / ${counts(coverage.total_sessions)} 个会话的工作目录。项目按目录设置或手动分配。`;
  $("coverage-note").hidden = false;
  $("analysis-warnings").replaceChildren();
  for (const warning of result.warnings || []) {
    $("analysis-warnings").append(node("div", "warning", typeof warning === "string" ? warning : warning.message || warning.code));
  }
  $("filter-status").textContent = "预览已更新";
  $("preview-caption").textContent = `${result.project_name} · ${result.start_date} 至 ${result.end_date}`;
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
  $("assignment-bar").hidden = true;
  $("pagination").hidden = true;
  if (!state.analysis) return;
  if (["daily", "models"].includes(state.tab)) {
    const rows = state.analysis[state.tab];
    if (!rows.length) empty($("preview-table"), state.analysis.availability_mode === "all" ? "所选条件没有用量" : "所选条件没有可用用量", "调整项目或日期，或查看已有报销记录。");
    else $("preview-table").replaceChildren(table(aggregateColumns(state.tab), rows));
    return;
  }
  const kind = state.tab === "rollups" ? "rollup" : "detail";
  const result = await api(`/api/analysis/${encodeURIComponent(state.analysis.analysis_id)}/details?kind=${kind}&page=${state.page}&size=50`);
  state.rows = result.rows; state.total = result.total;
  if (!state.rows.length) {
    empty($("preview-table"), kind === "rollup" ? "当前筛选没有历史日汇总" : "当前筛选没有逐条明细",
      kind === "rollup" ? "当前范围没有历史日汇总。" : "可切换到“历史日汇总”，或调整项目和日期。");
  } else renderRowTable();
  $("page-label").textContent = `共 ${counts(result.total)} 条 · 第 ${state.page} / ${Math.max(1, Math.ceil(result.total / 50))} 页`;
  $("pagination").hidden = !result.total;
  renderSelection(); syncActions();
}
async function applyAssignment() {
  const selected = [...state.selected.values()];
  const sessionScope = state.tab === "details" && $("session-scope").checked;
  const body = {capture_id: state.capture.id, kind: state.tab === "rollups" ? "rollup" : "detail",
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
  const link = node("button", "batch-link", `${owner.number} · v${owner.version}`);
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
  $("availability-summary").textContent = `当前范围共 ${counts(matched.record_count)} 条用量，已排除 ${counts(excluded.record_count)} 条，剩余 ${counts(available.record_count)} 条可用。`;
  for (const group of availability.excluded_groups) {
    const item = node("div", "availability-group");
    const quantities = [];
    if (group.detail_count) quantities.push(`${counts(group.detail_count)} 条明细`);
    const rollupRows = group.row_count - group.detail_count;
    if (rollupRows > 0) quantities.push(`${counts(rollupRows)} 条历史汇总（代表 ${counts(group.rollup_record_count)} 条记录）`);
    const reason = String(group.message || "已排除").replace(/[。.!！：:]+$/u, "");
    item.append(node("p", "", `${reason}：${quantities.join("，") || `${counts(group.record_count)} 条用量`}。`));
    const owners = node("div", "availability-owners");
    for (const owner of group.owners) {
      owners.append(ownerLink(owner), node("span", `status ${owner.lifecycle === "legacy_review" ? "legacy_review" : owner.status}`, labels[owner.lifecycle === "legacy_review" ? "legacy_review" : owner.status] || owner.status));
    }
    if (group.owners.length) item.append(owners);
    target.append(item);
  }
  if (availability.mode === "all") target.prepend(node("p", "field-help", "保存报销记录前，请切换到“可用用量”并更新预览。"));
  $("availability-panel").hidden = availability.mode === "available" && !excluded.record_count;
}
function usageCell(row) {
  const stateLabel = {available: "可用", claimed: "已占用", ambiguous: "待核对"};
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
  try { await refreshBatches(); if (state.capture) await analyze(); }
  catch { refreshed = false; }
  try { await download(saved.batch_id || saved.id, saved.version); }
  catch { throw new Error("记录已保存，下载失败。请在“报销记录”中下载材料。"); }
  const message = saved.lifecycle === "voided" ? "已下载已作废记录的历史材料。"
    : !saved.is_effective ? "已下载该历史版本的材料。"
    : refreshed ? "已保存报销记录，材料已下载。" : "已保存报销记录，材料已下载。请更新预览后继续。";
  notify(message);
}
async function download(id, version) {
  let response;
  try { response = await fetch(`/api/batches/${encodeURIComponent(id)}/revisions/${version}/download`, {credentials: "same-origin", cache: "no-store"}); }
  catch { throw new Error("下载失败，请确认程序仍在运行后重试。"); }
  if (!response.ok) {
    const error = await response.json(); throw new Error(error.message || "材料无法下载，请重试。");
  }
  const disposition = response.headers.get("Content-Disposition") || "";
  const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i);
  const filename = encoded ? decodeURIComponent(encoded[1]) : "aha-费用证据.zip";
  const url = URL.createObjectURL(await response.blob());
  const anchor = node("a"); anchor.href = url; anchor.download = filename;
  document.body.append(anchor); anchor.click(); anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30000);
}
async function refreshBatches() {
  const displayedBatchId = state.batch?.id || state.batch?.batch_id;
  state.batches = (await api("/api/batches")).batches;
  $("batch-nav-count").textContent = counts(state.batches.length);
  renderBatches();
  if (displayedBatchId) await showBatch(displayedBatchId);
}
function batchStatus(row) {
  return row.lifecycle === "voided" || row.lifecycle === "legacy_review" ? row.lifecycle : row.status;
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
      text.append(node("span", "subline", `${row.start_date} 至 ${row.end_date}`)); return text;
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
  if (state.capture) {
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
  else if (batch.lifecycle === "legacy_review") heading.append(node("p", "", "这条旧记录存在重复或版本冲突，请核对后确认保留版本或作废。"));
  const headerActions = node("div", "revision-actions");
  if (batch.lifecycle === "legacy_review" && batch.can_void) headerActions.append(actionButton("作废记录", () => openLifecycle("void", batch), "button small danger"));
  headerActions.append(actionButton("收起", () => { state.batch = null; target.replaceChildren(); }));
  header.append(heading, headerActions); panel.append(header);
  for (const revision of [...batch.revisions].sort((a, b) => b.version - a.version)) {
    const result = revision.analysis; const value = revision.claim;
    const item = node("article", "revision-card"); item.dataset.version = String(revision.version); item.dataset.batchId = batch.id || batch.batch_id;
    const title = node("div", "revision-title");
    title.append(node("strong", "", `v${revision.version}`));
    title.append(node("span", `status ${revision.is_effective ? "effective" : "historical"}`, revision.is_effective ? "当前记录" : batch.lifecycle === "legacy_review" ? "待核对版本" : "历史版本"));
    title.append(node("span", `status ${batchStatus(revision)}`, labels[batchStatus(revision)] || revision.status), node("span", "muted", dateTime(revision.created_at)));
    const meta = node("div", "revision-meta");
    meta.append(node("span", "", result.project_name), node("span", "", `${result.start_date} 至 ${result.end_date}`),
      node("span", "", `参考成本 ${money(result.summary.total_cost_usd)} USD`),
      node("span", "", value.amount === null || value.amount === "" ? "申请金额未填写" : `申请 ${money(value.amount)} ${value.currency}`));
    item.append(title, meta);
    if (value.purpose) item.append(node("p", "revision-purpose", value.purpose));
    if (value.amount_note) item.append(node("p", "revision-purpose", `金额依据：${value.amount_note}`));
    const actions = node("div", "revision-actions");
    actions.append(actionButton("下载材料", () => run("正在下载材料…", () => download(batch.id || batch.batch_id, revision.version)), "button small primary"));
    if (revision.can_edit) actions.append(actionButton("修改报销记录", () => openRevision(batch, revision)));
    if (revision.can_submit) actions.append(actionButton("标记已提交", () => run("正在更新状态…", () => markStatus(batch, revision, "submitted"))));
    if (revision.can_reimburse) actions.append(actionButton("标记已报销", () => run("正在更新状态…", () => markStatus(batch, revision, "reimbursed"))));
    if (revision.can_withdraw) actions.append(actionButton("撤回为草稿", () => openLifecycle("withdraw", batch, revision)));
    if (revision.can_void && batch.lifecycle !== "legacy_review") actions.append(actionButton("作废记录", () => openLifecycle("void", batch, revision), "button small danger"));
    if (revision.can_resolve) actions.append(actionButton("确认保留此版本", () => openLifecycle("resolve", batch, revision)));
    item.append(actions);
    if (revision.filename) item.append(node("div", "revision-file", revision.filename));
    panel.append(item);
  }
  if (batch.claim_history?.length) {
    const details = node("details", "scope-details history-details"); details.append(node("summary", "", "操作记录"));
    const list = node("ol", "audit-list");
    const actionLabels = {create: "创建记录", revise: "修改记录", withdraw: "撤回为草稿", void: "作废记录", resolve: "确认保留版本", status: "更新状态", migrate: "升级检查"};
    for (const event of [...batch.claim_history].reverse()) {
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
  state.revision = {batchId: batch.id || batch.batch_id, version: revision.version, generation: batch.generation, analysis: null, summary: revision.analysis.summary};
  $("revision-caption").textContent = `${batch.number} · 修改当前记录`;
  $("revision-basis").value = "frozen";
  $("revision-basis").options[1].disabled = !state.captures.length;
  $("revision-filters").hidden = true;
  for (const [target, source] of [["revision-capture", "capture-select"], ["revision-project", "project-select"]]) {
    $(target).replaceChildren(...[...$(source).options].map((option) => option.cloneNode(true)));
    $(target).value = $(source).value;
  }
  $("revision-start-date").value = $("start-date").value;
  $("revision-end-date").value = $("end-date").value;
  $("revision-purpose").value = revision.claim.purpose || "";
  $("revision-amount").value = revision.claim.amount ?? "";
  $("revision-currency").value = revision.claim.currency;
  $("revision-note").value = revision.claim.amount_note || "";
  renderRevisionPreview(revision.analysis);
  $("revision-dialog").showModal(); syncActions();
}
function renderRevisionPreview(result) {
  const summary = result.summary;
  $("revision-preview").replaceChildren(
    node("strong", "", `${counts(summary.record_count)} 条用量 · 参考成本 ${money(summary.total_cost_usd)} USD`),
    node("p", "field-help", `${result.project_name || "当前项目"} · ${result.start_date || ""} 至 ${result.end_date || ""}`),
  );
  const excluded = result.availability?.excluded_summary?.record_count;
  if (excluded) $("revision-preview").append(node("p", "field-help", `已排除其他记录占用或待核对的 ${counts(excluded)} 条用量。`));
}
async function prepareRevisionPreview() {
  if (!state.revision) return;
  state.revision.analysis = null;
  $("revision-filters").hidden = $("revision-basis").value === "frozen";
  if ($("revision-basis").value === "frozen") {
    const revision = state.batch.revisions.find((entry) => entry.version === state.revision.version);
    renderRevisionPreview(revision.analysis); syncActions(); return;
  }
  if (!$("revision-capture").value) throw new Error("请先选择数据快照。");
  const result = await api(`/api/batches/${encodeURIComponent(state.revision.batchId)}/analysis`, {
    capture_id: $("revision-capture").value, classification_revision: state.config.revision,
    start_date: $("revision-start-date").value, end_date: $("revision-end-date").value,
    project_id: $("revision-project").value, base_version: state.revision.version,
    expected_generation: state.revision.generation,
  });
  state.revision.analysis = result;
  renderRevisionPreview(result); syncActions();
}
function openLifecycle(action, batch, revision = null) {
  if (state.busy) return;
  clearFeedback();
  const settings = {
    withdraw: {title: "撤回为草稿", reason: "撤回原因", confirm: "确认撤回", description: "撤回后可修改，用量仍由此记录占用。"},
    void: {title: "作废记录", reason: "作废原因", confirm: "确认作废", description: "作废后用量可供其他报销记录使用，历史记录和材料仍保留。"},
    resolve: {title: "确认保留版本", reason: "保留原因", confirm: "确认保留", description: "请先核对其他冲突记录，再确认保留的有效版本。"},
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
  $("resolve-version-field").hidden = action !== "resolve";
  const select = $("resolve-version"); select.replaceChildren();
  if (action === "resolve") {
    for (const candidate of batch.revisions.filter((item) => item.can_resolve)) {
      const option = node("option", "", `v${candidate.version} · ${labels[candidate.status]} · ${money(candidate.total_cost_usd)} USD`);
      option.value = candidate.version; select.append(option);
    }
    select.value = String(revision?.version || "");
  }
  $("lifecycle-dialog").showModal();
}
async function saveLifecycle() {
  const operation = state.lifecycle;
  if (!operation) throw new Error("请重新选择记录后操作。");
  const reason = $("lifecycle-reason").value.trim();
  if (!reason) throw new Error("请填写操作原因。");
  const body = {reason, expected_generation: operation.generation};
  if (operation.action === "resolve") body.selected_version = Number($("resolve-version").value);
  const signature = JSON.stringify(body);
  if (signature !== operation.signature) { operation.key = crypto.randomUUID(); operation.signature = signature; }
  body.idempotency_key = operation.key;
  await api(`/api/batches/${encodeURIComponent(operation.batchId)}/${operation.action}`, body);
  $("lifecycle-dialog").close(); state.lifecycle = null;
  invalidate("记录已更新，请更新预览");
  await refreshBatches();
  if (state.capture) await analyze();
  notify({withdraw: "已撤回为草稿，可以修改。", void: "已作废，用量已释放。", resolve: "已确认保留版本。"}[operation.action]);
}
async function scanMetadata() {
  if (!state.capture) throw new Error("请先加载用量。");
  invalidate("正在刷新目录识别");
  state.capture = await api("/api/session-metadata", {capture_id: state.capture.id, roots: lines($("metadata-roots").value)});
  state.currentCaptureId = state.capture.id;
  await refreshCaptures(); renderSource(); $("source-dialog").close();
  notify("已更新目录识别。");
}
async function initialize() {
  const status = await api("/api/status");
  state.csrf = status.csrf_token; state.today = status.today;
  $("app-version").textContent = `v${status.version}`;
  range("today");
  await Promise.all([refreshProjects(), refreshCaptures(), refreshBatches()]);
  if (status.default_source.available) await loadSource("/api/source/sqlite", {});
  else if (state.captures.length) { await selectCapture(state.captures[0].id); await analyze(); }
  else notify("请读取 CC Switch 数据，或导入备份。", "info");
}

document.querySelectorAll("[data-page]").forEach((button) => button.addEventListener("click", () => page(button.dataset.page)));
document.querySelectorAll("[data-close]").forEach((button) => button.addEventListener("click", () => $(button.dataset.close).close()));
document.querySelectorAll("[data-range]").forEach((button) => button.addEventListener("click", () => range(button.dataset.range)));
$("range-all").addEventListener("click", () => {
  const coverage = state.capture?.coverage;
  if (!coverage?.start_date) { notify("请先加载有日期记录的用量。", "info"); return; }
  $("start-date").value = coverage.start_date; $("end-date").value = coverage.end_date;
  document.querySelectorAll("[data-range]").forEach((button) => button.classList.remove("active"));
  $("range-all").classList.add("active"); invalidate();
});
for (const id of ["start-date", "end-date", "project-select", "availability-mode"]) $(id).addEventListener("change", () => {
  if (id === "start-date" || id === "end-date") {
    document.querySelectorAll("[data-range]").forEach((button) => button.classList.remove("active"));
    $("range-all").classList.remove("active");
  }
  invalidate();
});
$("capture-select").addEventListener("change", (event) => run("正在加载历史快照…", () => selectCapture(event.target.value)));
$("source-options").addEventListener("click", () => { clearFeedback(); $("source-dialog").showModal(); });
$("load-default").addEventListener("click", () => run("正在加载用量…", () => loadSource("/api/source/sqlite", {})));
for (const id of ["import-sql", "dialog-import-sql"]) $(id).addEventListener("click", () => $("sql-file").click());
$("sql-file").addEventListener("change", (event) => {
  const file = event.target.files[0]; event.target.value = "";
  run("正在导入备份…", () => importSQL(file));
});
$("sqlite-form").addEventListener("submit", (event) => { event.preventDefault(); run("正在加载用量…", () => loadSource("/api/source/sqlite", {path: $("sqlite-path").value})); });
$("metadata-form").addEventListener("submit", (event) => { event.preventDefault(); run("正在刷新目录识别…", scanMetadata); });
$("refresh-metadata").addEventListener("click", () => { clearFeedback(); $("source-dialog").showModal(); });
for (const id of ["analyze", "refresh-availability"]) $(id).addEventListener("click", () => run("正在更新预览…", analyze));
$("new-project").addEventListener("click", () => openProject());
$("project-form").addEventListener("submit", (event) => { event.preventDefault(); run("正在保存项目…", saveProject); });
async function selectPreviewTab(name) {
  state.tab = name; state.page = 1; state.selected.clear();
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
$("prev-page").addEventListener("click", () => run("正在翻页…", async () => { state.page -= 1; await renderPreview(); }));
$("next-page").addEventListener("click", () => run("正在翻页…", async () => { state.page += 1; await renderPreview(); }));
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
for (const id of ["revision-capture", "revision-project", "revision-start-date", "revision-end-date"]) $(id).addEventListener("change", () => {
  if (state.revision) state.revision.analysis = null;
  $("revision-preview").replaceChildren(node("p", "", "条件已更改，请点击“更新用量”。"));
  syncActions();
});
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
  state.capture = null; invalidate("程序已退出");
  notify("程序已退出，可以关闭此页面。", "info");
});
$("shutdown").addEventListener("click", shutdown);
$("shutdown-compact").addEventListener("click", shutdown);
run("正在加载…", initialize);
