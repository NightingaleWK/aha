"use strict";

const $ = (id) => document.getElementById(id);
const state = {
  csrf: "", today: "", captures: [], capture: null, currentCaptureId: null,
  config: {revision: 0, projects: []}, analysis: null, tab: "daily", page: 1,
  rows: [], total: 0, selected: new Map(), batches: [], batch: null,
  busy: false, pendingBatch: null, revision: null, stopped: false,
};
const labels = {draft: "草稿", submitted: "已提交", reimbursed: "已报销"};
const origins = {manual: "人工指定", directory_rule: "目录规则", unassigned: "未归属"};
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
function notify(message, kind = "success") {
  const notice = $("notice");
  notice.replaceChildren(node("span", "", message));
  notice.className = `notice ${kind}`;
  notice.hidden = false;
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
    if (["analysis_expired", "classification_changed"].includes(error.code)) invalidate();
    throw error;
  }
  return result;
}
async function run(label, action) {
  if (state.busy) return;
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
  $("create-batch").disabled = state.busy || !state.analysis;
  $("refresh-metadata").disabled = state.busy || !state.capture;
  $("scan-metadata").disabled = state.busy || !state.capture;
  $("assign").disabled = state.busy || state.selected.size === 0;
  $("prev-page").disabled = state.busy || state.page <= 1;
  $("next-page").disabled = state.busy || state.page * 50 >= state.total;
}
function page(name) {
  const titles = {usage: "用量导出", projects: "项目管理", batches: "报销记录"};
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
  state.analysis = null;
  state.selected.clear();
  state.rows = [];
  state.page = 1;
  ["metric-cost", "metric-count", "metric-tokens", "metric-unassigned"].forEach((id) => { $(id).textContent = "—"; });
  $("token-strip").hidden = true;
  $("coverage-note").hidden = true;
  $("analysis-warnings").replaceChildren();
  $("pagination").hidden = true;
  $("assignment-bar").hidden = true;
  $("filter-status").textContent = message;
  $("preview-caption").textContent = "预览和下载使用同一份数据与筛选结果。";
  empty($("preview-table"), state.capture ? "按当前条件更新预览" : "从一份用量数据开始",
    state.capture ? "日期、项目或归属规则变化后，需要重新核对期间结果。" : "读取默认库或导入 SQL 后，即可按项目和日期核对。");
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
    const option = node("option", "", `${current ? "当前读取" : "历史留存"} · ${capture.source?.name || "用量数据"} · ${dateTime(capture.created_at)}`);
    option.value = capture.id;
    return option;
  });
  if (!options.length) {
    const option = node("option", "", "请先读取数据"); option.value = ""; options.push(option);
  }
  select.replaceChildren(...options);
  select.value = state.capture?.id || "";
  if (select.selectedIndex < 0) select.selectedIndex = 0;
}
function renderSource() {
  const capture = state.capture;
  if (!capture) {
    $("source-name").textContent = "尚未读取数据";
    $("source-mode").textContent = "待选择来源";
    $("source-description").textContent = "只读打开 CC Switch 数据库，或导入一份 SQL 备份。";
  } else {
    $("source-name").textContent = capture.source?.name || "用量留存";
    $("source-mode").textContent = capture.id === state.currentCaptureId ? "当前读取 · 已留存" : "历史留存";
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
  invalidate("正在读取所选留存");
  state.capture = null;
  try {
    state.capture = await api(`/api/captures/${encodeURIComponent(id)}`);
    renderSource(); invalidate("已选择留存，请更新预览");
  } catch (error) {
    renderSource(); invalidate("留存读取失败，请另选来源"); throw error;
  }
}
async function loadSource(path, body) {
  state.capture = null; state.currentCaptureId = null;
  renderSource(); invalidate("正在只读读取来源");
  try {
    const capture = await api(path, body);
    state.capture = capture; state.currentCaptureId = capture.id;
    await refreshCaptures(); renderSource();
    $("source-dialog").close();
    notify("读取成功，必要用量与目录依据已留存。原件保持原样。");
    await analyze();
  } catch (error) {
    state.capture = null; renderSource(); invalidate("来源读取失败，旧预览已清空"); throw error;
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
    empty(target, "先建立一个项目", "创建项目并绑定实际目录，已有明细和后续读取的数据都会按规则归类。");
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
    card.append(dirs, node("div", "project-card-footer", `${counts(project.directories.length)} 个目录绑定 · 包含子目录`));
    target.append(card);
  }
}
function renderDirectories() {
  const directories = state.capture?.directories || [];
  const coverage = state.capture?.metadata_coverage;
  $("directory-summary").textContent = coverage
    ? `${counts(coverage.matched_sessions)} / ${counts(coverage.total_sessions)} 个会话找到目录，发现 ${counts(directories.length)} 个不同目录。目录线索需要匹配你配置的项目规则。`
    : "读取一份数据后，这里会显示实际发现的目录。";
  const target = $("directory-list"); target.replaceChildren();
  for (const directory of directories) {
    const row = node("div", "directory-row");
    row.append(node("code", "", directory.path), node("span", "", `${counts(directory.session_count)} 个会话 · ${counts(directory.detail_count)} 条明细`));
    target.append(row);
  }
  const unresolved = state.capture?.unresolved_sessions || [];
  if (unresolved.length) {
    const conflicts = unresolved.filter((session) => session.status === "conflict").length;
    target.append(node("p", "field-help", `${counts(unresolved.length)} 个会话缺失或冲突（其中冲突 ${counts(conflicts)} 个），其用量仍会保留，可在明细页人工指定。`));
  }
}
function openProject(project = null) {
  $("edit-project-id").value = project?.id || "";
  $("project-dialog-title").textContent = project ? "编辑项目与目录" : "新建项目";
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
  $("project-dialog").close(); notify("项目与目录已保存，已有数据会使用新规则归类。");
}
async function analyze() {
  if (!state.capture) throw new Error("请先选择一份来源或历史留存。");
  const result = await api("/api/analysis", {
    capture_id: state.capture.id, classification_revision: state.config.revision,
    start_date: $("start-date").value, end_date: $("end-date").value,
    project_id: $("project-select").value,
  });
  state.analysis = result; state.page = 1; state.selected.clear();
  const summary = result.summary;
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
  $("coverage-note").textContent = `${counts(coverage.matched_sessions)} / ${counts(coverage.total_sessions)} 个会话找到目录。找到目录是归属线索；项目依据来自你配置的目录规则或人工指定。`;
  $("coverage-note").hidden = false;
  $("analysis-warnings").replaceChildren();
  for (const warning of result.warnings || []) {
    $("analysis-warnings").append(node("div", "warning", typeof warning === "string" ? warning : warning.message || warning.code));
  }
  $("filter-status").textContent = "预览已更新";
  $("preview-caption").textContent = `${result.project_name} · ${result.start_date} 至 ${result.end_date} · 全量导出不受分页限制`;
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
  if (row.pricing_status === "unpriced") text.append(node("span", "subline", "未定价，不能据此认定免费"));
  if (row.pricing_status === "missing_basis") text.append(node("span", "subline", "当前价格依据缺失"));
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
    {title: "新增输入", numeric: true, value: (row) => counts(row.fresh_input_tokens)},
    {title: "输出", numeric: true, value: (row) => counts(row.output_tokens)},
    {title: "总 Token", numeric: true, value: (row) => counts(row.total_tokens)},
    {title: "参考成本 USD", numeric: true, value: costCell}];
}
function renderRowTable() {
  const rollup = state.tab === "rollups";
  const columns = [
    {title: rollup ? "来源日期" : "北京时间", value: (row) => rollup ? row.date : row.time?.replace("T", " ").replace("+08:00", ""), wrap: false},
    {title: "项目 / 归属依据", value: projectCell, wrap: true},
    {title: "模型", value: (row) => row.model},
    ...(rollup ? [{title: "代表记录数", numeric: true, value: (row) => counts(row.request_count)}] : []),
    {title: "新增输入", numeric: true, value: (row) => counts(row.fresh_input_tokens)},
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
    if (!rows.length) empty($("preview-table"), "所选期间没有匹配记录", "空结果也可保存为如实标明的材料。没有记录的日期不据此认定为零消耗。");
    else $("preview-table").replaceChildren(table(aggregateColumns(state.tab), rows));
    return;
  }
  const kind = state.tab === "rollups" ? "rollup" : "detail";
  const result = await api(`/api/analysis/${encodeURIComponent(state.analysis.analysis_id)}/details?kind=${kind}&page=${state.page}&size=50`);
  state.rows = result.rows; state.total = result.total;
  if (!state.rows.length) {
    empty($("preview-table"), kind === "rollup" ? "当前筛选没有历史日汇总" : "当前筛选没有逐条明细",
      kind === "rollup" ? "旧数据若已汇总，将按来源完整记录显示，不能拆分或补造成逐条明细。" : "若来源只有历史日汇总，请切换到“历史日汇总”查看。所有匹配数据仍会完整导出。");
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
  notify(sessionScope ? "所选会话在本份留存中的全部明细已更新归属。" : "所选记录的人工归属已更新。");
}
function claim(prefix = "claim") {
  return {purpose: $(`${prefix}-purpose`).value, amount: $(`${prefix}-amount`).value,
    currency: $(`${prefix}-currency`).value, amount_note: $(`${prefix}-note`).value};
}
function validateClaim(value) {
  if (value.amount.trim() && (!/^\d+(\.\d{1,2})?$/.test(value.amount.trim()) || !value.amount_note.trim())) {
    throw new Error("申请金额应为非负数字、最多两位小数，并填写申请金额依据。金额可留空。");
  }
}
async function prepareBatch(payload, batchId = null) {
  validateClaim(payload.claim);
  const signature = JSON.stringify({payload, batchId});
  const key = state.pendingBatch?.signature === signature
    ? state.pendingBatch.request.idempotency_key : crypto.randomUUID();
  const request = {...payload, idempotency_key: key};
  const previewRequest = {...request};
  if (batchId) previewRequest.batch_id = batchId;
  const result = await api("/api/batches/preview", previewRequest);
  state.pendingBatch = {request, batchId, signature};
  if (result.overlaps.length) {
    renderOverlaps(result.overlaps);
    if ($("revision-dialog").open) $("revision-dialog").close();
    $("overlap-dialog").showModal();
  } else await saveBatch();
}
function renderOverlaps(warnings) {
  $("overlap-list").replaceChildren();
  for (const warning of warnings) {
    const item = node("article", "overlap-item");
    const heading = node("div");
    const link = node("button", "batch-link", `${warning.number || warning.batch_number} · v${warning.version}`);
    link.addEventListener("click", () => run("读取已有批次…", async () => {
      $("overlap-dialog").close(); page("batches"); await showBatch(warning.batch_id);
    }));
    heading.append(link, document.createTextNode("  "), node("span", `status ${warning.status}`, labels[warning.status] || warning.status));
    item.append(heading, node("p", "", warning.message));
    $("overlap-list").append(item);
  }
}
async function saveBatch() {
  const pending = state.pendingBatch;
  if (!pending) throw new Error("请重新发起创建操作。");
  const path = pending.batchId ? `/api/batches/${encodeURIComponent(pending.batchId)}/revisions` : "/api/batches";
  const batch = await api(path, pending.request);
  $("overlap-dialog").close(); $("revision-dialog").close();
  await refreshBatches();
  await download(batch.batch_id || batch.id, batch.version);
  notify(`${batch.number || "批次"} · v${batch.version} 已保存为草稿并下载。重复下载可在“报销记录”中完成。`);
  state.pendingBatch = null;
}
async function download(id, version) {
  let response;
  try { response = await fetch(`/api/batches/${encodeURIComponent(id)}/revisions/${version}/download`, {credentials: "same-origin", cache: "no-store"}); }
  catch { throw new Error("下载连接中断。批次已保存，可在报销记录中重新下载原包。"); }
  if (!response.ok) {
    const error = await response.json(); throw new Error(error.message || "原文件无法下载。");
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
function renderBatches() {
  if (!state.batches.length) {
    empty($("batch-list"), "还没有报销批次", "在用量导出页核对期间结果，创建批次后即可在这里查看版本与重下载材料。"); return;
  }
  $("batch-list").replaceChildren(table([
    {title: "批次编号", value: (row) => {
      const link = node("button", "batch-link", row.number);
      link.addEventListener("click", () => run("读取批次版本…", () => showBatch(row.id || row.batch_id))); return link;
    }},
    {title: "项目 / 期间", wrap: true, value: (row) => {
      const text = node("span", "", row.project_name || row.latest?.analysis?.project_name || "费用证据");
      text.append(node("span", "subline", `${row.start_date || row.latest?.analysis?.start_date || ""} 至 ${row.end_date || row.latest?.analysis?.end_date || ""}`)); return text;
    }},
    {title: "最新版本", value: (row) => `v${row.latest_version}`},
    {title: "参考成本 USD", numeric: true, value: (row) => money(row.total_cost_usd ?? row.latest?.analysis?.summary?.total_cost_usd)},
    {title: "人工状态", value: (row) => {
      const status = row.status || row.latest?.status || "draft";
      return node("span", `status ${status}`, labels[status] || status);
    }},
    {title: "创建时间", value: (row) => dateTime(row.created_at)},
  ], state.batches));
}
async function showBatch(id) {
  state.batch = await api(`/api/batches/${encodeURIComponent(id)}`);
  renderBatchDetail();
}
function renderBatchDetail() {
  const batch = state.batch; const target = $("batch-detail"); target.replaceChildren();
  if (!batch) return;
  const panel = node("section", "panel"); const header = node("div", "batch-detail-header");
  const heading = node("div"); heading.append(node("h2", "", `${batch.number} · 版本历史`), node("p", "", "每个版本独立保存材料与人工状态。"));
  const close = node("button", "button small", "收起"); close.addEventListener("click", () => { state.batch = null; target.replaceChildren(); });
  header.append(heading, close); panel.append(header);
  for (const revision of [...batch.revisions].sort((a, b) => b.version - a.version)) {
    const result = revision.analysis; const value = revision.claim;
    const item = node("article", "revision-card"); const title = node("div", "revision-title");
    title.append(node("strong", "", `v${revision.version}`), node("span", `status ${revision.status}`, labels[revision.status]), node("span", "muted", dateTime(revision.created_at)));
    const meta = node("div", "revision-meta");
    meta.append(node("span", "", result.project_name), node("span", "", `${result.start_date} 至 ${result.end_date}`),
      node("span", "", `参考成本 ${money(result.summary.total_cost_usd)} USD`),
      node("span", "", value.amount === null || value.amount === "" ? "申请金额未填写" : `申请 ${value.amount} ${value.currency}`));
    item.append(title, meta, node("p", "revision-purpose", value.purpose || "未填写项目用途说明"));
    if (value.amount_note) item.append(node("p", "revision-purpose", `金额依据：${value.amount_note}`));
    const actions = node("div", "revision-actions");
    const get = node("button", "button small primary", "重新下载原 ZIP");
    get.addEventListener("click", () => run("校验并下载原材料…", () => download(batch.id || batch.batch_id, revision.version)));
    const edit = node("button", "button small", "以此创建新版本"); edit.addEventListener("click", () => openRevision(batch, revision));
    const status = node("select"); status.setAttribute("aria-label", `版本 ${revision.version} 人工状态`);
    for (const [key, label] of Object.entries(labels)) { const option = node("option", "", label); option.value = key; status.append(option); }
    status.value = revision.status;
    const save = node("button", "button small", "更新状态");
    save.addEventListener("click", () => run("保存人工状态…", async () => {
      await api(`/api/batches/${encodeURIComponent(batch.id || batch.batch_id)}/revisions/${revision.version}/status`, {status: status.value});
      await refreshBatches(); notify("该版本的人工状态已更新，原证据包保持不变。");
    }));
    actions.append(get, edit, status, save); item.append(actions);
    if (revision.filename) item.append(node("div", "revision-file", revision.filename));
    panel.append(item);
  }
  target.append(panel);
}
function openRevision(batch, revision) {
  state.revision = {batchId: batch.id || batch.batch_id, version: revision.version};
  $("revision-caption").textContent = `${batch.number} · 以 v${revision.version} 为基础。新版本初始为草稿。`;
  $("revision-basis").value = "frozen";
  $("revision-basis").options[1].disabled = !state.analysis;
  $("revision-purpose").value = revision.claim.purpose || "";
  $("revision-amount").value = revision.claim.amount ?? "";
  $("revision-currency").value = revision.claim.currency;
  $("revision-note").value = revision.claim.amount_note || "";
  $("revision-dialog").showModal();
}
async function scanMetadata() {
  if (!state.capture) throw new Error("请先选择一份用量留存。");
  invalidate("目录依据正在刷新");
  state.capture = await api("/api/session-metadata", {capture_id: state.capture.id, roots: lines($("metadata-roots").value)});
  state.currentCaptureId = state.capture.id;
  await refreshCaptures(); renderSource(); $("source-dialog").close();
  notify("目录依据已刷新并形成新的留存，旧留存与旧批次保持原样。");
}
async function initialize() {
  const status = await api("/api/status");
  state.csrf = status.csrf_token; state.today = status.today;
  $("app-version").textContent = `v${status.version}`;
  range("today");
  await Promise.all([refreshProjects(), refreshCaptures(), refreshBatches()]);
  if (status.default_source.available) await loadSource("/api/source/sqlite", {});
  else if (state.captures.length) {
    await selectCapture(state.captures[0].id);
    notify("已打开一份历史留存。它代表此前读取的数据，可重新读取当前来源。", "info");
    await analyze();
  } else {
    notify("本机尚未找到默认 CCS 数据库。可以导入 SQL，或在“管理数据来源”中填写文件路径。", "info");
  }
}

document.querySelectorAll("[data-page]").forEach((button) => button.addEventListener("click", () => page(button.dataset.page)));
document.querySelectorAll("[data-close]").forEach((button) => button.addEventListener("click", () => $(button.dataset.close).close()));
document.querySelectorAll("[data-range]").forEach((button) => button.addEventListener("click", () => range(button.dataset.range)));
$("range-all").addEventListener("click", () => {
  const coverage = state.capture?.coverage;
  if (!coverage?.start_date) { notify("请先读取含有日期范围的用量数据。", "info"); return; }
  $("start-date").value = coverage.start_date; $("end-date").value = coverage.end_date;
  document.querySelectorAll("[data-range]").forEach((button) => button.classList.remove("active"));
  $("range-all").classList.add("active"); invalidate();
});
for (const id of ["start-date", "end-date", "project-select"]) $(id).addEventListener("change", () => {
  if (id !== "project-select") {
    document.querySelectorAll("[data-range]").forEach((button) => button.classList.remove("active"));
    $("range-all").classList.remove("active");
  }
  invalidate();
});
$("capture-select").addEventListener("change", (event) => run("打开所选历史留存…", () => selectCapture(event.target.value)));
$("source-options").addEventListener("click", () => $("source-dialog").showModal());
$("load-default").addEventListener("click", () => run("读取数据库并关联会话目录…", () => loadSource("/api/source/sqlite", {})));
for (const id of ["import-sql", "dialog-import-sql"]) $(id).addEventListener("click", () => $("sql-file").click());
$("sql-file").addEventListener("change", (event) => {
  const file = event.target.files[0]; event.target.value = "";
  run("读取 SQL 并关联会话目录…", () => importSQL(file));
});
$("sqlite-form").addEventListener("submit", (event) => { event.preventDefault(); run("只读加载数据库…", () => loadSource("/api/source/sqlite", {path: $("sqlite-path").value})); });
$("metadata-form").addEventListener("submit", (event) => { event.preventDefault(); run("刷新会话目录依据…", scanMetadata); });
$("refresh-metadata").addEventListener("click", () => $("source-dialog").showModal());
$("analyze").addEventListener("click", () => run("按当前条件汇总用量…", analyze));
$("new-project").addEventListener("click", () => openProject());
$("project-form").addEventListener("submit", (event) => { event.preventDefault(); run("保存项目与目录…", saveProject); });
document.querySelectorAll("[data-tab]").forEach((button) => button.addEventListener("click", () => run("切换预览…", async () => {
  state.tab = button.dataset.tab; state.page = 1; state.selected.clear();
  document.querySelectorAll("[data-tab]").forEach((tab) => {
    tab.classList.toggle("active", tab === button); tab.setAttribute("aria-selected", String(tab === button));
  });
  await renderPreview();
})));
$("prev-page").addEventListener("click", () => run("读取上一页…", async () => { state.page -= 1; await renderPreview(); }));
$("next-page").addEventListener("click", () => run("读取下一页…", async () => { state.page += 1; await renderPreview(); }));
$("clear-selection").addEventListener("click", () => { state.selected.clear(); renderRowTable(); renderSelection(); });
$("assign").addEventListener("click", () => run("保存人工归属并重新汇总…", applyAssignment));
$("create-batch").addEventListener("click", () => run("核对批次重叠范围…", () => prepareBatch({analysis_id: state.analysis.analysis_id, claim: claim()})));
$("confirm-batch").addEventListener("click", () => run("保存批次并下载…", saveBatch));
$("refresh-batches").addEventListener("click", () => run("刷新报销记录…", refreshBatches));
$("revision-form").addEventListener("submit", (event) => {
  event.preventDefault(); run("核对新版本…", () => {
    const payload = {base_version: state.revision.version, claim: claim("revision")};
    if ($("revision-basis").value === "current") {
      if (!state.analysis) throw new Error("当前预览已失效，请先到用量导出页更新预览。");
      payload.analysis_id = state.analysis.analysis_id;
    }
    return prepareBatch(payload, state.revision.batchId);
  });
});
const shutdown = () => run("退出程序…", async () => {
  await api("/api/shutdown", {});
  state.stopped = true;
  document.querySelectorAll("dialog[open]").forEach((dialog) => dialog.close());
  state.capture = null; invalidate("程序已退出");
  notify("程序已退出，端口将释放。已保存的项目、留存与批次会保留；可以关闭此页面。", "info");
  $("load-default").disabled = true; $("import-sql").disabled = true;
});
$("shutdown").addEventListener("click", shutdown);
$("shutdown-compact").addEventListener("click", shutdown);
run("正在准备本机工作台…", initialize);
