"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

// Run the real page state and request handlers with a minimal DOM. Deferred
// fetches let a newer filter own the page before an older response arrives.
function page() {
  class Element {
    constructor() {
      this.value = ""; this.disabled = false; this.hidden = false;
      this.children = []; this.dataset = {}; this.isConnected = true;
      this.listeners = new Map();
      this.attributes = new Map();
      this.classList = {toggle() {}, add() {}, remove() {}};
    }
    addEventListener(name, listener) {
      if (!this.listeners.has(name)) this.listeners.set(name, []);
      this.listeners.get(name).push(listener);
    }
    emit(name) { for (const listener of this.listeners.get(name) || []) listener({target: this, preventDefault() {}}); }
    get options() { return this.children; }
    setAttribute(name, value) { this.attributes.set(name, value); }
    removeAttribute(name) { this.attributes.delete(name); }
    querySelectorAll() { return []; }
    append(...items) { this.children.push(...items); }
    replaceChildren(...items) { this.children = items; }
    close() { if (this.open) { this.open = false; this.emit("close"); } }
    showModal() { this.open = true; }
    cloneNode(deep = false) {
      const item = new Element(); item.value = this.value; item.textContent = this.textContent;
      if (deep) item.children = this.children.map((child) => child.cloneNode(true));
      return item;
    }
    focus() { this.focused = true; }
    getClientRects() { return []; }
  }
  const elements = new Map();
  const body = new Element();
  const pending = [];
  let keySequence = 0;
  let statusReply;
  const context = vm.createContext({
    document: {
      body, activeElement: body,
      getElementById(id) {
        if (!elements.has(id)) elements.set(id, new Element());
        return elements.get(id);
      },
      createElement() { return new Element(); },
      querySelector() { return null; },
      querySelectorAll(selector) {
        if (selector === "[data-sync-control]") return [this.getElementById("sync-control")];
        if (["[data-association-select]", "[data-association-group]"].includes(selector)) {
          const matches = new Set(); const attribute = selector.slice(1, -1);
          function visit(element) {
            if (element.attributes.has(attribute)) matches.add(element);
            element.children.forEach(visit);
          }
          [...elements.values()].forEach(visit);
          return [...matches];
        }
        return [];
      },
    },
    Node: Element, URLSearchParams, Intl, clearTimeout, setTimeout, AbortController,
    crypto: {randomUUID: () => `test-sync-key-${++keySequence}`},
    AhaForms: {mount() {}, sync() {}, closeAll() {}, destroy() {}},
    fetch(url, options = {}) {
      if (url === "/api/status") return new Promise((resolve) => { statusReply = resolve; });
      return new Promise((resolve, reject) => pending.push({url, options, resolve, reject}));
    },
  });
  context.window = context;
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../src/aha/web/time-range-picker.js"), "utf8"), context);
  context.AhaTimeRange.create = () => {
    let intent = {kind: "preset", preset: "today", follow_now: true};
    return {setDisabled() {}, markPending() {}, setResolved() {},
      getIntent() { return intent; }, setIntent(value) { intent = value; }};
  };
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../src/aha/web/app.js"), "utf8"), context);
  const evaluate = (code) => vm.runInContext(code, context);
  evaluate(`state.busy = false; state.ledger = {};
    state.analysis = {analysis_id: "old", availability_mode: "available"};`);
  return {
    evaluate,
    statusReply(result) { statusReply({ok: true, json: async () => result}); },
    reply(ok, result) { pending.shift().resolve({ok, json: async () => result}); },
    replyTo(url, ok, result) {
      const index = pending.findIndex((request) => request.url === url);
      assert.notEqual(index, -1, `missing request: ${url}`);
      pending.splice(index, 1)[0].resolve({ok, json: async () => result});
    },
    replyLatest(url, ok, result) {
      const index = pending.findLastIndex((request) => request.url === url);
      assert.notEqual(index, -1, `missing request: ${url}`);
      pending.splice(index, 1)[0].resolve({ok, json: async () => result});
    },
    pendingUrls() { return pending.map((request) => request.url); },
    pendingRequests() { return pending; },
    disconnect() { pending.shift().reject(new Error("disconnected")); },
    disconnectTo(url) {
      const index = pending.findIndex((request) => request.url === url);
      assert.notEqual(index, -1, `missing request: ${url}`);
      pending.splice(index, 1)[0].reject(new Error("disconnected"));
    },
  };
}

test("source card prioritizes failure, running, review and recovery with historical data", () => {
  const app = page();
  app.evaluate(`state.ledger = {
    counts: {detail_count: 2, rollup_count: 1}, coverage: {start_date: "2026-10-01", end_date: "2026-10-02"},
    last_successful_sync_at: "2026-10-02T02:47:00Z",
    last_attempt: {state: "failed", error_message: "来源读取超过时限。"}
  }; state.sync = null; renderSource();`);
  assert.equal(app.evaluate('$("source-mode").textContent'), "同步失败");
  assert.match(app.evaluate('$("sync-error").textContent'), /来源读取超过时限/);
  assert.match(app.evaluate('$("sync-error").textContent'), /当前显示已保存的本地数据/);
  assert.match(app.evaluate('$("source-description").textContent'), /上次成功/);
  assert.match(app.evaluate('$("source-description").textContent'), /2026-10-01 至 2026-10-02/);

  app.evaluate('state.syncBusy = true; renderSource();');
  assert.equal(app.evaluate('$("source-mode").textContent'), "同步中");
  assert.equal(app.evaluate('$("sync-error").hidden'), true);
  assert.equal(app.evaluate('$("sync-control").disabled'), true);

  app.evaluate('state.syncBusy = false; state.sync = {status: "needs_review"}; renderSource();');
  assert.equal(app.evaluate('$("source-mode").textContent'), "需要核对");
  assert.equal(app.evaluate('$("sync-error").hidden'), true);

  app.evaluate('state.sync = {status: "completed"}; renderSource();');
  assert.equal(app.evaluate('$("source-mode").textContent'), "已同步");
  assert.equal(app.evaluate('$("sync-control").disabled'), false);
  assert.equal(app.evaluate('$("sync-error").hidden'), true);
});

test("a restored failed job keeps the detailed reason in its persisted result", () => {
  const app = page();
  app.evaluate(`state.ledger = {counts: {}, coverage: {}, last_successful_sync_at: "2026-10-02T02:47:00Z"};
    state.sync = {status: "failed", message: "同步未完成。",
      result: {state: "failed", error_message: "来源结构版本不受支持。"}}; renderSource();`);
  assert.equal(app.evaluate('$("source-mode").textContent'), "同步失败");
  assert.match(app.evaluate('$("sync-error").textContent'), /来源结构版本不受支持/);
});

test("a failed first attempt never presents an empty local ledger as actual usage", () => {
  const app = page();
  app.evaluate(`state.ledger = {counts: {}, coverage: {},
    last_attempt: {state: "failed", error_message: "找不到所选数据库。"}};
    state.sync = null; renderSource();`);
  assert.equal(app.evaluate('$("source-mode").textContent'), "同步失败");
  assert.match(app.evaluate('$("sync-error").textContent'), /找不到所选数据库/);
  assert.match(app.evaluate('$("sync-error").textContent'), /尚未成功同步，当前统计不代表实际用量/);
  assert.match(app.evaluate('$("source-description").textContent'), /尚无成功同步/);
});

test("saved review data can exist before the first successful sync", () => {
  const app = page();
  app.evaluate(`state.ledger = {counts: {detail_count: 2}, coverage: {},
    last_attempt: {state: "failed", error_message: "来源读取失败。"}};
    state.sync = null; renderSource();`);
  assert.match(app.evaluate('$("sync-error").textContent'), /当前显示已保存的本地数据/);
  assert.match(app.evaluate('$("sync-error").textContent'), /尚未成功同步，当前统计不代表实际用量/);
});

test("a retry immediately hides failure and restores the card after success", async () => {
  const app = page();
  app.evaluate(`state.ledger = {counts: {}, coverage: {}, last_successful_sync_at: "2026-10-02T02:47:00Z"};
    state.sync = {status: "failed", message: "来源读取失败。"}; renderSource();
    refreshLedger = async () => { state.ledger.last_successful_sync_at = "2026-10-03T02:47:00Z"; };
    refreshProjects = async () => {}; refreshReconciliations = async () => {};
    invalidate = () => {}; run = async () => {};`);
  const retry = app.evaluate("loadSource()");
  assert.equal(app.evaluate('$("source-mode").textContent'), "同步中");
  assert.equal(app.evaluate('$("sync-error").hidden'), true);
  assert.equal(app.evaluate('$("sync-control").disabled'), true);
  app.reply(true, {id: "retry", status: "completed"});
  await retry;
  assert.equal(app.evaluate('$("source-mode").textContent'), "已同步");
  assert.equal(app.evaluate('$("sync-error").hidden'), true);
  assert.equal(app.evaluate('$("sync-control").disabled'), false);
});

test("a completed job carrying a review result uses review status and feedback", async () => {
  const app = page();
  app.evaluate(`state.ledger = {counts: {}, coverage: {}, last_successful_sync_at: "2026-10-02T02:47:00Z"};
    refreshLedger = async () => {}; refreshProjects = async () => {};
    refreshReconciliations = async () => {}; run = async () => {};`);
  const retry = app.evaluate("loadSource()");
  app.reply(true, {id: "review", status: "completed", result: {state: "needs_review"}});
  await retry;
  assert.equal(app.evaluate('$("source-mode").textContent'), "需要核对");
  assert.equal(app.evaluate('$("notice").className'), "notice info");
  assert.match(app.evaluate('$("notice").children[0].textContent'), /需要核对/);
});

test("a failed job retains its reason when the later status refresh disconnects", async () => {
  const app = page();
  app.evaluate(`state.ledger = {counts: {}, coverage: {}, last_successful_sync_at: "2026-10-02T02:47:00Z"};
    state.sync = {status: "completed"};
    refreshLedger = async () => { throw new Error("刷新连接中断。"); };
    refreshProjects = async () => {}; refreshReconciliations = async () => {};`);
  const retry = app.evaluate("loadSource()");
  app.reply(true, {id: "failed", status: "failed", message: "来源读取超过时限。"});
  await retry;
  assert.equal(app.evaluate('$("source-mode").textContent'), "同步失败");
  assert.match(app.evaluate('$("sync-error").textContent'), /来源读取超过时限/);
  assert.doesNotMatch(app.evaluate('$("sync-error").textContent'), /刷新连接中断/);
  assert.equal(app.evaluate('$("notice").children[0].textContent'), "刷新连接中断。");
});

test("a completed or review job is not misreported as failed when refresh disconnects", async () => {
  for (const [status, label] of [["completed", "已同步"], ["needs_review", "需要核对"]]) {
    const app = page();
    app.evaluate(`state.ledger = {counts: {}, coverage: {}, last_successful_sync_at: "2026-10-02T02:47:00Z"};
      refreshLedger = async () => { throw new Error("刷新连接中断。"); };
      refreshProjects = async () => {}; refreshReconciliations = async () => {};`);
    const retry = app.evaluate("loadSource()");
    app.reply(true, {id: "finished", status});
    await retry;
    assert.equal(app.evaluate('$("source-mode").textContent'), label);
    assert.equal(app.evaluate('$("sync-error").hidden'), true);
    assert.equal(app.evaluate('$("notice").children[0].textContent'), "刷新连接中断。");
  }
});

test("terminal success or review invalidates old previews even when refresh fails", async () => {
  for (const status of ["completed", "needs_review", "failed"]) {
    const app = page();
    app.evaluate(`state.busy = true;
      state.ledger = {counts: {}, coverage: {}, last_successful_sync_at: "2026-10-02T02:47:00Z"};
      state.analysis = {analysis_id: "old"}; state.pendingBatch = {signature: "old"};
      refreshLedger = async () => { throw new Error("刷新连接中断。"); };
      refreshProjects = async () => {}; refreshReconciliations = async () => {};`);
    const retry = app.evaluate("loadSource()");
    app.reply(true, {id: "finished", status, message: "来源失败。"});
    await retry;
    if (status === "failed") {
      assert.equal(app.evaluate("state.analysis.analysis_id"), "old");
      assert.equal(app.evaluate("state.pendingBatch.signature"), "old");
    } else {
      assert.equal(app.evaluate("state.analysis"), null);
      assert.equal(app.evaluate("state.pendingBatch"), null);
    }
    assert.equal(app.evaluate('$("notice").children[0].textContent'), "刷新连接中断。");
  }
});

test("a terminal polling response updates the card before slow refresh requests finish", async () => {
  const app = page();
  app.evaluate(`state.ledger = {counts: {}, coverage: {}, last_successful_sync_at: "2026-10-02T02:47:00Z"};
    refreshLedger = () => new Promise(() => {});
    refreshProjects = async () => {}; refreshReconciliations = async () => {};`);
  app.evaluate('watchSync({id: "running", status: "running"})');
  await new Promise((resolve) => setTimeout(resolve, 500));
  app.reply(true, {id: "running", status: "failed", message: "来源读取失败。"});
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(app.evaluate('$("source-mode").textContent'), "同步失败");
  assert.match(app.evaluate('$("sync-error").textContent'), /来源读取失败/);
  assert.equal(app.evaluate('$("sync-control").disabled'), false);
});

test("late refresh success or failure from an older job cannot affect a retry", async () => {
  for (const staleFails of [false, true]) {
    const app = page();
    app.evaluate(`state.ledger = {counts: {detail_count: 2}, coverage: {},
      last_successful_sync_at: "2026-10-02T02:47:00Z"};
      state.analysis = {analysis_id: "current"}; $("notice").hidden = true;`);
    const old = app.evaluate("loadSource()");
    app.reply(true, {id: "old", status: "failed", message: "旧来源失败。"});
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(app.evaluate('$("source-mode").textContent'), "同步失败");
    const retry = app.evaluate("loadSource()");
    if (staleFails) app.reply(false, {code: "data_changed", message: "过时刷新失败。"});
    else app.reply(true, {counts: {detail_count: 999}, coverage: {}});
    app.reply(true, {projects: [{id: "old"}]});
    app.reply(true, {cases: [{id: "old"}]});
    await old;
    assert.equal(app.evaluate('$("source-mode").textContent'), "同步中");
    assert.equal(app.evaluate('$("sync-control").disabled'), true);
    assert.equal(app.evaluate("state.ledger.counts.detail_count"), 2);
    assert.equal(app.evaluate("state.config.projects.length"), 0);
    assert.equal(app.evaluate("state.reconciliations.length"), 0);
    assert.equal(app.evaluate("state.analysis.analysis_id"), "current");
    assert.equal(app.evaluate('$("notice").hidden'), true);

    app.evaluate('refreshProjects = async () => {}; refreshReconciliations = async () => {};');
    app.reply(true, {id: "new", status: "failed", message: "新来源失败。"});
    await new Promise((resolve) => setImmediate(resolve));
    app.reply(true, {counts: {detail_count: 2}, coverage: {},
      last_successful_sync_at: "2026-10-02T02:47:00Z"});
    await retry;
    assert.equal(app.evaluate('$("source-mode").textContent'), "同步失败");
    assert.match(app.evaluate('$("sync-error").textContent'), /新来源失败/);
    assert.equal(app.evaluate('$("sync-control").disabled'), false);
  }
});

test("initial rendering uses the current job before an older successful ledger", async () => {
  const app = page();
  app.evaluate('refreshProjects = () => new Promise(() => {});');
  app.statusReply({csrf_token: "token", today: "2026-10-03", version: "test", ledger: {
    counts: {}, coverage: {}, last_successful_sync_at: "2026-10-02T02:47:00Z",
    last_attempt: {state: "completed"}
  }, sync: {id: "latest", status: "failed", message: "本次来源失败。"}});
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(app.evaluate('$("source-mode").textContent'), "同步失败");
  assert.match(app.evaluate('$("sync-error").textContent'), /本次来源失败/);
});

test("initial rendering restores a persisted failed attempt when no job exists", async () => {
  const app = page();
  app.evaluate('refreshProjects = () => new Promise(() => {});');
  app.statusReply({csrf_token: "token", today: "2026-10-03", version: "test", ledger: {
    counts: {}, coverage: {}, last_successful_sync_at: "2026-10-02T02:47:00Z",
    last_attempt: {state: "failed", error_message: "上次同步未完成。"}
  }});
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(app.evaluate('$("source-mode").textContent'), "同步失败");
  assert.match(app.evaluate('$("sync-error").textContent'), /上次同步未完成/);
});

test("initialization failure cannot abandon a running job or leave sync disabled", async () => {
  const app = page();
  app.evaluate(`refreshProjects = async () => { throw new Error("项目加载失败。"); };
    refreshReconciliations = async () => {}; refreshBatches = async () => {};
    refreshLedger = async () => {};`);
  app.statusReply({csrf_token: "token", today: "2026-10-03", version: "test", ledger: {
    counts: {}, coverage: {}, last_successful_sync_at: "2026-10-02T02:47:00Z"
  }, sync: {id: "startup", status: "running"}});
  await new Promise((resolve) => setTimeout(resolve, 500));
  assert.equal(app.evaluate('$("source-mode").textContent'), "同步中");
  app.reply(true, {id: "startup", status: "completed"});
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(app.evaluate('$("source-mode").textContent'), "已同步");
  assert.equal(app.evaluate('$("sync-control").disabled'), false);
  assert.equal(app.evaluate('$("sync-error").hidden'), true);
});

test("sync completion during initial analysis schedules a fresh preview", async () => {
  const app = page();
  app.evaluate(`state.busy = true;
    refreshProjects = async () => {}; refreshReconciliations = async () => {};
    refreshBatches = async () => {}; refreshLedger = async () => {};
    timeRange.getIntent = () => ({}); timeRange.setResolved = () => {};
    AhaTimeRange.fromAnalysis = () => null; AhaTimeRange.describe = () => "";
    renderAvailability = () => {}; renderTimeCoverage = () => {}; renderPreview = async () => {};`);
  app.statusReply({csrf_token: "token", today: "2026-10-03", version: "test", ledger: {
    counts: {}, coverage: {}, last_successful_sync_at: "2026-10-02T02:47:00Z"
  }, sync: {id: "startup", status: "running"}});
  await new Promise((resolve) => setTimeout(resolve, 500));
  app.replyTo("/api/sync/startup", true, {id: "startup", status: "completed"});
  await new Promise((resolve) => setImmediate(resolve));
  app.replyTo("/api/analysis", true, {analysis_id: "obsolete"});
  await new Promise((resolve) => setImmediate(resolve));
  app.replyTo("/api/analysis", true, {analysis_id: "fresh", availability_mode: "available",
    project_name: "全部项目", start_date: "2026-10-01", end_date: "2026-10-03",
    summary: {record_count: 1, total_cost_usd: "1"}});
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(app.evaluate("state.analysis?.analysis_id"), "fresh");
  assert.equal(app.evaluate("state.syncPreviewPending"), false);
});

test("manual sync during slow initialization does not start another startup sync", async () => {
  const app = page();
  app.evaluate(`state.busy = true; let projectCalls = 0;
    refreshProjects = () => ++projectCalls === 1
      ? new Promise((resolve) => { globalThis.unblockInitialization = resolve; }) : Promise.resolve();
    refreshReconciliations = async () => {}; refreshBatches = async () => {};
    refreshLedger = async () => {}; analyze = async () => { state.syncPreviewPending = false; };`);
  app.statusReply({csrf_token: "token", today: "2026-10-03", version: "test", ledger: {
    counts: {}, coverage: {}, last_successful_sync_at: "2026-10-02T02:47:00Z"
  }});
  await new Promise((resolve) => setImmediate(resolve));
  const manual = app.evaluate("loadSource()");
  app.replyTo("/api/sync", true, {id: "manual", status: "completed"});
  await manual;
  app.evaluate("unblockInitialization()");
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(app.evaluate("state.syncGeneration"), 1);
  assert.equal(app.pendingUrls().includes("/api/sync"), false);
});

test("late initialization refreshes cannot replace newer sync results or report stale errors", async () => {
  for (const staleFails of [false, true]) {
    const app = page();
    app.evaluate(`state.busy = true; $("notice").hidden = true;
      refreshBatches = async () => {}; analyze = async () => {
        state.syncPreviewPending = false; state.analysis = {analysis_id: "fresh"};
      };`);
    app.statusReply({csrf_token: "token", today: "2026-10-03", version: "test", ledger: {
      counts: {}, coverage: {}, last_successful_sync_at: "2026-10-02T02:47:00Z"
    }, sync: {id: "startup", status: "running"}});
    await new Promise((resolve) => setTimeout(resolve, 500));
    app.replyTo("/api/sync/startup", true, {id: "startup", status: "needs_review"});
    await new Promise((resolve) => setImmediate(resolve));
    app.replyTo("/api/ledger", true, {counts: {}, coverage: {},
      last_successful_sync_at: "2026-10-02T02:47:00Z"});
    app.replyLatest("/api/projects", true, {revision: 8, projects: []});
    app.replyLatest("/api/reconciliations", true, {cases: [{id: "latest"}]});
    await new Promise((resolve) => setImmediate(resolve));
    if (staleFails) {
      app.replyTo("/api/projects", false, {code: "data_changed", message: "旧项目请求失败。"});
      app.replyTo("/api/reconciliations", false, {code: "data_changed", message: "旧核对请求失败。"});
    } else {
      app.replyTo("/api/projects", true, {revision: 2, projects: []});
      app.replyTo("/api/reconciliations", true, {cases: []});
    }
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(app.evaluate("state.config.revision"), 8);
    assert.equal(app.evaluate("state.reconciliations[0]?.id"), "latest");
    assert.equal(app.evaluate("state.analysis?.analysis_id"), "fresh");
    assert.equal(app.evaluate('$("source-mode").textContent'), "需要核对");
    assert.equal(app.evaluate('$("notice").className'), "notice info");
  }
});

test("a late ledger refresh cannot replace newer data or invalidate its preview", async () => {
  for (const staleFails of [false, true]) {
    const app = page();
    const old = app.evaluate("refreshLedger()");
    const latest = app.evaluate("refreshLedger()");
    app.replyLatest("/api/ledger", true, {counts: {detail_count: 7}, coverage: {}});
    await latest;
    if (staleFails) app.replyTo("/api/ledger", false, {code: "data_changed", message: "旧资料请求失败。"});
    else app.replyTo("/api/ledger", true, {counts: {detail_count: 1}, coverage: {}});
    await old;
    assert.equal(app.evaluate("state.ledger.counts.detail_count"), 7);
    assert.equal(app.evaluate("state.analysis.analysis_id"), "old");
  }
});

function replacePreview(app) {
  app.evaluate(`invalidate();
    state.analysis = {analysis_id: "new", availability_mode: "available"};
    state.pendingBatch = {signature: "new-save"};
    state.rows = [{record_key: "new-member"}];`);
}

function assertNewPreview(app) {
  assert.equal(app.evaluate("state.analysis?.analysis_id"), "new");
  assert.equal(app.evaluate("state.pendingBatch?.signature"), "new-save");
  assert.equal(app.evaluate("state.rows[0]?.record_key"), "new-member");
}

test("a stale detail failure cannot invalidate a newer preview or save identity", async () => {
  const app = page();
  const response = app.evaluate("renderPreview()");
  replacePreview(app);
  app.reply(false, {code: "availability_changed", message: "obsolete selection"});
  await response;
  assertNewPreview(app);
});

test("a stale successful detail response cannot replace newer rows", async () => {
  const app = page();
  const response = app.evaluate("renderPreview()");
  replacePreview(app);
  app.reply(true, {rows: [{record_key: "old-member"}], total: 1});
  await response;
  assertNewPreview(app);
});

test("a stale connection error does not surface after a filter change", async () => {
  const app = page();
  const response = app.evaluate("renderPreview()");
  replacePreview(app);
  app.disconnect();
  await response;
  assertNewPreview(app);
});

test("a current detail 409 still clears analysis, revision and save identity", async () => {
  const app = page();
  app.evaluate(`state.pendingBatch = {signature: "old-save"};
    state.revision = {analysis: {analysis_id: "revision"}, filterGeneration: 0};
    $("revision-basis").value = "current";`);
  const response = app.evaluate("renderPreview()");
  app.reply(false, {code: "availability_changed", message: "current selection changed"});
  await assert.rejects(response, (error) => error.code === "availability_changed" && error.invalidated);
  assert.equal(app.evaluate("state.analysis"), null);
  assert.equal(app.evaluate("state.revision.analysis"), null);
  assert.equal(app.evaluate("state.pendingBatch"), null);
  assert.equal(app.evaluate('$("save-revision").disabled'), true);
});

test("batch rows show precise saved ranges and retain legacy date precision", () => {
  const app = page();
  app.evaluate(`state.batches = [
    {id: "precise", number: "AHA-000001", project_name: "项目", active_version: 1,
      total_cost_usd: "0", claim: {amount: null}, status: "draft",
      start_date: "2026-10-26", end_date: "2026-10-26",
      time_range: {start_at: "2026-10-26T08:00:00+08:00",
        end_before: "2026-10-26T09:01:00+08:00", precision: "minute"}},
    {id: "legacy", number: "AHA-000002", project_name: "旧项目", active_version: 1,
      total_cost_usd: "0", claim: {amount: null}, status: "draft",
      start_date: "2024-02-28", end_date: "2024-02-29"}
  ]; renderBatches();`);
  const text = app.evaluate(`(function text(item) {
    return (item.textContent || "") + item.children.map(text).join(" ");
  })($("batch-list"))`);
  assert.match(text, /2026-10-26 08:00 至 2026-10-26 09:00（北京时间）/);
  assert.match(text, /2024-02-28 至 2024-02-29（北京时间）/);
  assert.doesNotMatch(text, /2024-02-28 00:00/);
});

test("an omitted-only revision preview does not present unknown usage as zero cost", () => {
  const app = page();
  app.evaluate(`const omitted = {
    project_name: "项目", start_date: "2026-10-26", end_date: "2026-10-26",
    time_range: {start_at: "2026-10-26T08:00:00+08:00",
      end_before: "2026-10-26T09:01:00+08:00", precision: "minute"},
    summary: {record_count: 0, total_cost_usd: "0"},
    time_coverage: {complete: false, omitted_rollup_count: 1, omitted_days: ["2026-10-26"]}
  }; state.revision = {analysis: omitted}; $("revision-basis").value = "current";
  renderRevisionPreview(omitted); syncActions();`);
  const text = app.evaluate(`(function text(item) {
    return (item.textContent || "") + item.children.map(text).join(" ");
  })($("revision-preview"))`);
  assert.match(text, /当前时段没有可确定的用量/);
  assert.match(text, /统计不完整/);
  assert.doesNotMatch(text, /参考成本 0 USD/);
  assert.equal(app.evaluate('$("save-revision").disabled'), true);
});

test("empty current filters explain retained history without changing the chosen range", () => {
  const app = page();
  const before = app.evaluate("JSON.stringify(timeRange.getIntent())");
  app.evaluate(`state.ledger = {coverage: {start_date: "2026-06-17", end_date: "2026-11-10"}};
    renderEmptyRange({summary: {record_count: "0"}, time_coverage: {complete: true}});`);
  assert.equal(app.evaluate('$("empty-range-note").hidden'), false);
  assert.match(app.evaluate('$("empty-range-description").textContent'), /历史数据仍保留/);
  assert.match(app.evaluate('$("empty-range-description").textContent'), /2026-06-17 至 2026-11-10/);
  assert.equal(app.evaluate("JSON.stringify(timeRange.getIntent())"), before);
  app.evaluate('renderEmptyRange({summary: {record_count: "0"}, time_coverage: {complete: false}});');
  assert.equal(app.evaluate('$("empty-range-note").hidden'), true);
});

test("an unbound copied ledger opens source confirmation while retaining the local preview", async () => {
  const app = page();
  app.evaluate('state.sourceBinding = {required: true}; renderSource();');
  assert.equal(app.evaluate('$("source-mode").textContent'), "待确认本机来源");
  const operation = app.evaluate("loadSource()");
  app.reply(true, {required: true, has_history: true, source_name: "cc-switch.db"});
  await operation;
  assert.equal(app.evaluate('$("source-binding-dialog").open'), true);
  assert.equal(app.evaluate("state.analysis.analysis_id"), "old");
  assert.equal(app.evaluate("state.syncBusy"), false);
  assert.equal(app.pendingUrls().includes("/api/sync"), false);
});

test("source confirmation records the explicit reason before starting continuation", async () => {
  const app = page();
  app.evaluate(`state.sourceBinding = {required: true};
    state.bindingSelection = {location: "", continuation: {path: "/api/sync", body: {}}};
    $("source-binding-reason").value = "新电脑接续，保留历史";
    loadSource = async (path, body) => { state.continuation = {path, body}; };`);
  const operation = app.evaluate("saveSourceBinding()");
  const payload = JSON.parse(app.pendingRequests()[0].options.body);
  assert.equal(payload.reason, "新电脑接续，保留历史");
  assert.equal(app.evaluate("state.continuation"), undefined);
  app.reply(true, {bound: true, required: false});
  await operation;
  assert.equal(app.evaluate("state.sourceBinding.required"), false);
  assert.equal(app.evaluate("state.analysis"), null);
  assert.equal(app.evaluate("state.continuation.path"), "/api/sync");
});

test("reconciliation immediately expires saving and automatically previews the same filters", async () => {
  const app = page();
  app.evaluate(`$("project-select").value = "original-project";
    timeRange.setIntent({kind: "preset", preset: "last_7d", follow_now: true});
    state.pendingBatch = {signature: "old"};
    refreshLedger = async () => {}; refreshProjects = async () => {};
    refreshReconciliations = async () => {}; renderReconciliations = () => {};
    analyze = async () => { state.repreview = {project: $("project-select").value, intent: timeRange.getIntent()}; };`);
  const operation = app.evaluate('resolveReconciliation({id: "case-1", generation: 2}, "current", "已核对")');
  assert.equal(app.evaluate("state.analysis"), null);
  assert.equal(app.evaluate("state.pendingBatch"), null);
  assert.equal(app.evaluate('$("create-batch").disabled'), true);
  app.reply(true, {state: "resolved"});
  await operation;
  assert.equal(app.evaluate("state.repreview.project"), "original-project");
  assert.equal(app.evaluate("state.repreview.intent.preset"), "last_7d");
});

test("a reconciliation refresh failure leaves the old save identity expired", async () => {
  const app = page();
  app.evaluate(`state.pendingBatch = {signature: "old"};
    refreshProjects = async () => {}; refreshReconciliations = async () => {};`);
  const operation = app.evaluate('resolveReconciliation({id: "case-1", generation: 2}, "current", "已核对")');
  app.reply(true, {state: "resolved"});
  await new Promise((resolve) => setImmediate(resolve));
  app.disconnectTo("/api/ledger");
  await assert.rejects(operation, /连接中断/);
  assert.equal(app.evaluate("state.analysis"), null);
  assert.equal(app.evaluate("state.pendingBatch"), null);
  assert.equal(app.evaluate('$("create-batch").disabled'), true);
});

test("late reconciliation refreshes cannot overwrite a newer filter preview", async () => {
  for (const fail of [false, true]) {
    const app = page();
    app.evaluate(`refreshProjects = async () => {}; refreshReconciliations = async () => {};
      analyze = async () => { throw new Error("stale reconciliation must not requery"); };`);
    const operation = app.evaluate('resolveReconciliation({id: "case-1", generation: 2}, "current", "已核对")');
    app.reply(true, {state: "resolved"});
    await new Promise((resolve) => setImmediate(resolve));
    app.evaluate('state.filterGeneration += 1; state.analysis = {analysis_id: "newer"}; state.ledger = {newer: true};');
    if (fail) app.disconnectTo("/api/ledger");
    else app.replyTo("/api/ledger", true, {older: true});
    await operation;
    assert.equal(app.evaluate("state.analysis.analysis_id"), "newer");
    assert.equal(app.evaluate("state.ledger.newer"), true);
  }
});

test("full backup completion retains the current query and exposes a streamed download", async () => {
  const app = page();
  const operation = app.evaluate("createFullBackup()");
  app.reply(true, {id: "backup-1", kind: "backup", status: "completed", result: {size: 100}});
  await operation;
  assert.equal(app.evaluate("state.analysis.analysis_id"), "old");
  assert.equal(app.evaluate("state.backupBusy"), false);
  assert.equal(app.evaluate('$("backup-result").hidden'), false);
  assert.match(app.evaluate('$("backup-result").children[0].textContent'), /请下载保存/);
});

test("cancelled late backup creation cannot replace a newer operation", async () => {
  const app = page();
  const first = app.evaluate("createFullBackup()");
  await app.evaluate("cancelBackupOperation()");
  const second = app.evaluate("createFullBackup()");
  app.replyTo("/api/backups", true, {id: "old-backup", kind: "backup", status: "running"});
  await first;
  app.replyLatest("/api/backups", true, {id: "new-backup", kind: "backup", status: "completed", result: {}});
  await second;
  app.replyTo("/api/backups/old-backup/cancel", true, {status: "cancelled"});
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(app.evaluate("state.backupJob.id"), "new-backup");
  assert.equal(app.evaluate("state.backupBusy"), false);
  assert.match(app.evaluate('$("backup-result").children[0].textContent'), /完整备份已生成/);
});

test("restore uploads binary chunks and ignores late chunk success after cancellation", async () => {
  const app = page();
  app.evaluate(`state.backupLimits = {archive_bytes: 1024, chunk_bytes: 4};
    $("restore-file").files = [{size: 8, slice(start, end) { return {size: end - start}; }}];`);
  const operation = app.evaluate("restoreFullBackup()");
  app.reply(true, {id: "upload-1", chunk_bytes: 4});
  await new Promise((resolve) => setImmediate(resolve));
  const chunk = app.pendingRequests()[0];
  assert.equal(chunk.options.headers["Content-Type"], "application/octet-stream");
  assert.equal(chunk.options.headers["X-AHA-Upload-Offset"], "0");
  assert.equal(chunk.options.body.size, 4);
  const cancelled = app.evaluate("cancelBackupOperation()");
  app.replyTo("/api/restore-uploads/upload-1/cancel", true, {status: "cancelled"});
  await cancelled;
  app.replyTo("/api/restore-uploads/upload-1/chunks", true, {received: 4});
  await operation;
  assert.equal(app.pendingUrls().some((url) => url.endsWith("/restore")), false);
  assert.equal(app.evaluate("state.analysis.analysis_id"), "old");
  assert.equal(app.evaluate("state.backupBusy"), false);
});

test("directory and rollup-origin reconciliation display their real choices", () => {
  const app = page();
  app.evaluate(`state.reconciliations = [
    {id: "directory", type: "directory", current_cwd: "C:/old-project", candidate_cwd: "D:/new-project", choices: ["current", "candidate"]},
    {id: "rollup", type: "rollup_origin", choices: ["current"]}
  ]; renderReconciliations();`);
  const text = app.evaluate(`JSON.stringify((function collect(element) {
    return [element.textContent || "", ...element.children.flatMap(collect)];
  })($("reconciliation-list")))`);
  assert.match(text, /C:\/old-project/);
  assert.match(text, /D:\/new-project/);
  assert.match(text, /采用当前电脑目录/);
  assert.match(text, /保留已保存目录/);
  assert.match(text, /确认重叠，保留历史汇总/);
});

test("project creation retains its saved identity before a failed follow-up refresh", async () => {
  for (const failedRefresh of ["projects", "associations"]) {
    const app = page();
    app.evaluate(`state.activePage = "projects"; $("edit-project-id").value = "";
      $("edit-project-name").value = "合成新项目"; $("edit-project-description").value = "";
      $("edit-project-directories").value = ""; $("project-dialog").showModal();
      state.pendingBatch = {signature: "old"};
      state.associationPreview = {result: {preview_id: "old"}, request: {}};
      refreshProjects = async () => { ${failedRefresh === "projects" ? 'throw new Error("项目刷新断线");' : ""} };
      refreshAssociations = async () => { ${failedRefresh === "associations" ? 'throw new Error("归属刷新断线");' : ""} };`);
    const saved = app.evaluate("saveProject()");
    app.replyTo("/api/projects", true, {project: {id: "saved-project"}});
    await assert.rejects(saved, /项目已保存，但刷新未完成/);
    assert.equal(app.evaluate('$("edit-project-id").value'), "saved-project");
    assert.equal(app.evaluate("state.analysis"), null);
    assert.equal(app.evaluate("state.pendingBatch"), null);
    assert.equal(app.evaluate("state.associationPreview"), null);
    assert.equal(app.evaluate('$("create-batch").disabled'), true);
    assert.equal(app.evaluate('$("project-dialog").open'), true);

    app.evaluate("refreshProjects = async () => {}; refreshAssociations = async () => {};");
    const retried = app.evaluate("saveProject()");
    assert.deepEqual(app.pendingUrls(), ["/api/projects/saved-project"]);
    app.replyTo("/api/projects/saved-project", true, {project: {id: "saved-project"}});
    await retried;
    assert.equal(app.evaluate('$("project-dialog").open'), false);
  }
});

test("association all-filtered selection sends the filter, not only the visible page", () => {
  const app = page();
  app.evaluate(`$("association-filter-project").value = "unassigned";
    $("association-filter-directory").value = "/old/work";
    $("association-filter-start").value = "2026-10-01";
    $("association-filter-end").value = "2026-10-31";
    $("association-target-project").value = "project-1";
    $("association-bind-sessions").checked = true;
    state.associationRows = [{record_key: "visible"}];
    state.associationSelected.set("visible", state.associationRows[0]);
    state.associationAllFiltered = true;`);
  const request = JSON.parse(app.evaluate('JSON.stringify(associationPreviewRequest("assign"))'));
  assert.equal(request.project_id, "project-1");
  assert.equal(request.bind_sessions, true);
  assert.equal(request.keys, undefined);
  assert.deepEqual(request.filters, {project_id: "unassigned", directory: "/old/work", start_date: "2026-10-01", end_date: "2026-10-31"});
  app.evaluate("renderAssociationSelection()");
  assert.match(app.evaluate('$("association-selection-description").textContent'), /包含其他分页/);
});

test("association explicit selection retains records from earlier pages", () => {
  const app = page();
  app.evaluate(`$("association-target-project").value = "project-2";
    state.associationRows = [{record_key: "second-page"}];
    state.associationSelected.set("first-page", {record_key: "first-page"});
    state.associationSelected.set("second-page", {record_key: "second-page"});`);
  const request = JSON.parse(app.evaluate('JSON.stringify(associationPreviewRequest("assign"))'));
  assert.deepEqual(request.keys, ["first-page", "second-page"]);
  assert.equal(request.filters.project_id, "unassigned");
  app.evaluate('state.associationSelected.clear()');
  assert.throws(() => app.evaluate('associationPreviewRequest("reclassify")'), /请勾选记录/);
});

test("closing or replacing an association preview rejects stale success, 409 and disconnect", async () => {
  for (const outcome of ["success", "expired", "disconnect"]) {
    const app = page();
    app.evaluate(`$("association-target-project").value = "project-1"; state.associationAllFiltered = true;`);
    const operation = app.evaluate('previewAssociations("assign")');
    assert.equal(app.evaluate('$("association-dialog").open'), true);
    app.evaluate(`$("association-dialog").close();
      state.associationPreview = {result: {preview_id: "newer", summary: {changed_count: 1}}, request: {}};
      state.analysis = {analysis_id: "newer-analysis"}; state.pendingBatch = {signature: "newer-save"};`);
    if (outcome === "disconnect") app.disconnectTo("/api/project-associations/preview");
    else app.replyTo("/api/project-associations/preview", outcome === "success", outcome === "success"
      ? {preview_id: "older", summary: {changed_count: 3}}
      : {code: "analysis_expired", message: "旧预览失效"});
    await operation;
    assert.equal(app.evaluate("state.associationPreview.result.preview_id"), "newer");
    assert.equal(app.evaluate("state.analysis.analysis_id"), "newer-analysis");
    assert.equal(app.evaluate("state.pendingBatch.signature"), "newer-save");
  }
});

test("an association target change invalidates an in-flight preview", async () => {
  const app = page();
  app.evaluate(`$("association-target-project").value = "first"; state.associationAllFiltered = true;`);
  const operation = app.evaluate('previewAssociations("assign")');
  app.evaluate('$("association-target-project").value = "second"; $("association-target-project").emit("change");');
  app.replyTo("/api/project-associations/preview", true, {preview_id: "first", summary: {changed_count: 5}});
  await operation;
  assert.equal(app.evaluate("state.associationPreview"), null);
  assert.equal(app.evaluate('$("apply-associations").disabled'), true);
});

test("a newer association overview owns project costs after old success or failure", async () => {
  for (const fail of [false, true]) {
    const app = page();
    const old = app.evaluate("refreshAssociationOverview()");
    const current = app.evaluate("refreshAssociationOverview()");
    app.replyLatest("/api/project-associations", true, {newer: true, summary: {}, projects: [], groups: []});
    await current;
    if (fail) app.disconnectTo("/api/project-associations");
    else app.replyTo("/api/project-associations", true, {older: true, summary: {}, projects: [], groups: []});
    await old;
    assert.equal(app.evaluate("state.associations.newer"), true);
  }
});

test("association record requests ignore stale data and failures after filters change", async () => {
  for (const outcome of ["success", "expired", "disconnect"]) {
    const app = page();
    const operation = app.evaluate("refreshAssociationRecords()");
    const url = app.pendingUrls()[0];
    app.evaluate(`state.associationGeneration += 1; state.associationRows = [{record_key: "newer"}];
      state.analysis = {analysis_id: "newer"};`);
    if (outcome === "disconnect") app.disconnectTo(url);
    else app.replyTo(url, outcome === "success", outcome === "success" ? {rows: [{record_key: "older"}]}
      : {code: "classification_changed", message: "旧游标失效"});
    await operation;
    assert.equal(app.evaluate("state.associationRows[0].record_key"), "newer");
    assert.equal(app.evaluate("state.analysis.analysis_id"), "newer");
  }
});

test("association apply expires saving immediately and retries the same request idempotently", async () => {
  const app = page();
  app.evaluate(`state.associationPreview = {result: {preview_id: "preview-1", summary: {changed_count: 3}}, request: {action: "assign"}, applied: false};
    $("association-reason").value = "项目开发支出"; $("project-select").value = "original-project";
    state.pendingBatch = {signature: "old"};
    timeRange.setIntent({kind: "preset", preset: "last_7d", follow_now: true});
    refreshLedger = async () => {}; refreshProjects = async () => {};
    refreshAssociationOverview = async () => {}; refreshAssociationRecords = async () => {};
    analyze = async () => { state.repreview = {project: $("project-select").value, intent: timeRange.getIntent()}; };`);
  const first = app.evaluate("applyAssociations()");
  const initial = JSON.parse(app.pendingRequests()[0].options.body);
  assert.equal(app.evaluate("state.analysis"), null);
  assert.equal(app.evaluate("state.pendingBatch"), null);
  assert.equal(app.evaluate('$("create-batch").disabled'), true);
  app.disconnectTo("/api/project-associations/apply");
  await assert.rejects(first, /连接中断/);
  const retry = app.evaluate("applyAssociations()");
  const repeated = JSON.parse(app.pendingRequests()[0].options.body);
  assert.deepEqual(repeated, initial);
  app.replyTo("/api/project-associations/apply", true, {applied: true, changed_count: 3});
  await retry;
  assert.equal(app.evaluate("state.repreview.project"), "original-project");
  assert.equal(app.evaluate("state.repreview.intent.preset"), "last_7d");
  assert.equal(app.evaluate("state.associationPreview"), null);
});

test("a saved association with a refresh failure retries only the refresh", async () => {
  const app = page();
  app.evaluate(`state.associationPreview = {result: {preview_id: "preview-1", summary: {changed_count: 1}}, request: {action: "assign"}, applied: false};
    $("association-reason").value = "核实项目归属";
    refreshLedger = async () => {}; refreshProjects = async () => {};
    refreshAssociationOverview = async () => { throw new Error("刷新断线"); };
    refreshAssociationRecords = async () => {}; analyze = async () => {};`);
  const first = app.evaluate("applyAssociations()");
  app.replyTo("/api/project-associations/apply", true, {applied: true});
  await assert.rejects(first, /归属已保存，但刷新未完成/);
  assert.equal(app.evaluate("state.associationPreview.applied"), true);
  assert.equal(app.evaluate("state.analysis"), null);
  assert.equal(app.evaluate('$("apply-associations").textContent'), "刷新已保存结果");
  assert.equal(app.evaluate('$("association-reason").readOnly'), true);
  app.evaluate("refreshAssociationOverview = async () => {};");
  await app.evaluate("applyAssociations()");
  assert.equal(app.pendingUrls().includes("/api/project-associations/apply"), false);
  assert.equal(app.evaluate("state.associationPreview"), null);
});

test("an expired association preview cannot be resubmitted without a new preview", async () => {
  const app = page();
  app.evaluate(`state.associationPreview = {result: {preview_id: "preview-1", summary: {changed_count: 1}}, request: {}, applied: false};
    $("association-reason").value = "原计划";`);
  const operation = app.evaluate("applyAssociations()");
  app.replyTo("/api/project-associations/apply", false, {code: "association_preview_expired", message: "依据已变化"});
  await assert.rejects(operation, /依据已变化/);
  assert.equal(app.evaluate("state.associationPreview"), null);
  assert.equal(app.evaluate('$("apply-associations").disabled'), true);
  assert.match(app.evaluate('$("association-preview-caption").textContent'), /返回重新预览/);
});

test("an old apply response cannot clear a newer preview after its dialog closes", async () => {
  const app = page();
  app.evaluate(`state.associationPreview = {result: {preview_id: "preview-1", summary: {changed_count: 1}}, request: {}, applied: false};
    $("association-reason").value = "已确认"; $("association-dialog").showModal();`);
  const operation = app.evaluate("applyAssociations()");
  app.evaluate(`$("association-dialog").close(); state.analysis = {analysis_id: "newer"}; state.pendingBatch = {signature: "newer"};`);
  app.replyTo("/api/project-associations/apply", true, {applied: true});
  await operation;
  assert.equal(app.evaluate("state.analysis.analysis_id"), "newer");
  assert.equal(app.evaluate("state.pendingBatch.signature"), "newer");
  assert.equal(app.pendingUrls().includes("/api/project-associations"), false);
});

test("assignment coverage states physical grains and exact cost without blocking known project saving", () => {
  const app = page();
  app.evaluate(`state.analysis = {analysis_id: "known-project", availability_mode: "available", summary: {record_count: 1}};
    renderAssignmentCoverage({assignment_coverage: {status: "incomplete", unassigned_detail_count: 2,
      unassigned_rollup_count: 3, unassigned_record_count: 35500, unassigned_cost_usd: "0.000000000000000000000000123"}});
    syncActions();`);
  assert.equal(app.evaluate('$("assignment-coverage-note").hidden'), false);
  const text = app.evaluate('$("assignment-coverage-description").textContent');
  assert.match(text, /2 条明细、3 行历史日汇总/);
  assert.match(text, /0\.000000000000000000000000123 USD/);
  assert.equal(app.evaluate('$("create-batch").disabled'), false);
  app.evaluate("renderAssignmentCoverage({assignment_coverage: null})");
  assert.equal(app.evaluate('$("assignment-coverage-note").hidden'), true);
});

test("dynamic project refresh retains the association target and filter by identity", async () => {
  const app = page();
  app.evaluate('$("association-target-project").value = "p2"; $("association-filter-project").value = "p1"; $("assignment-project").value = "p2";');
  const operation = app.evaluate("refreshProjects()");
  app.replyTo("/api/projects", true, {projects: [{id: "p1", name: "重名项目", directories: []}, {id: "p2", name: "重名项目", directories: []}]});
  await operation;
  assert.equal(app.evaluate('$("association-target-project").value'), "p2");
  assert.equal(app.evaluate('$("association-filter-project").value'), "p1");
  assert.equal(app.evaluate('$("assignment-project").value'), "p2");
});

test("new association rows become selectable when the loading operation ends", () => {
  const app = page();
  app.evaluate(`state.busy = true; state.associationRows = [{record_key: "record-1", kind: "detail", date: "2026-10-01", model: "model"}];
    renderAssociationRecords();`);
  assert.equal(app.evaluate('document.querySelectorAll("[data-association-select]").every((item) => item.disabled)'), true);
  app.evaluate("state.busy = false; syncActions();");
  assert.equal(app.evaluate('document.querySelectorAll("[data-association-select]").every((item) => !item.disabled)'), true);
  app.evaluate("state.associationAllFiltered = true; syncActions();");
  assert.equal(app.evaluate('document.querySelectorAll("[data-association-select]").every((item) => item.disabled)'), true);
});

test("truncated directory metadata marks recovery metrics and groups as partial", () => {
  const app = page();
  app.evaluate(`state.associations = {summary: {recoverable_sessions: 1,
    recoverable_detail_count: 2, unassigned_detail_count: 3}, projects: [], groups: [],
    metadata_scan_truncated: true, groups_truncated: true}; renderAssociationOverview();`);
  assert.match(app.evaluate('$("association-overview").children[3].children[2].textContent'), /已检查部分/);
  assert.match(app.evaluate('$("association-groups").children.at(-1).textContent'), /待归属总量仍为完整台账/);
});

test("keyboard record selection preserves focus on the replacement checkbox", () => {
  const app = page();
  app.evaluate(`state.associationRows = [{record_key: "record-1", kind: "detail", date: "2026-10-01", model: "model"}];
    renderAssociationRecords();
    const checkbox = document.querySelectorAll("[data-association-select]")[1];
    checkbox.checked = true; checkbox.emit("change");`);
  assert.equal(app.evaluate('state.associationSelected.has("record-1")'), true);
  assert.equal(app.evaluate('document.querySelectorAll("[data-association-select]")[1].focused'), true);
});

test("a known ledger mutation expires association previews and in-flight overview reads", async () => {
  const app = page();
  app.evaluate(`state.associationPreview = {result: {preview_id: "old"}, request: {}};
    state.associationSelected.set("old", {record_key: "old"});`);
  const overview = app.evaluate("refreshAssociationOverview()");
  app.evaluate('invalidateAssociations("同步已更新，请刷新")');
  app.replyTo("/api/project-associations", true, {older: true, projects: [], groups: [], summary: {}});
  await overview;
  assert.equal(app.evaluate("state.associations"), null);
  assert.equal(app.evaluate("state.associationPreview"), null);
  assert.equal(app.evaluate("state.associationSelected.size"), 0);
  assert.equal(app.evaluate('$("association-status").textContent'), "同步已更新，请刷新");
});

test("record exception clearing and future session-default removal have distinct explanations", () => {
  const app = page();
  app.evaluate('state.tab = "details"; $("assignment-project").value = ""; $("session-scope").checked = false; renderAssignmentMode();');
  assert.equal(app.evaluate('$("assign").textContent'), "取消逐条例外");
  assert.match(app.evaluate('$("assignment-mode-description").textContent'), /返回已保存的项目归属依据/);
  app.evaluate('$("session-scope").checked = true; $("session-scope").emit("change");');
  assert.equal(app.evaluate('$("assign").textContent'), "解除会话默认");
  assert.match(app.evaluate('$("assignment-mode-description").textContent'), /已确认的历史归属保留/);
  app.evaluate('$("assignment-project").value = "project-1"; $("assignment-project").emit("change");');
  assert.match(app.evaluate('$("assignment-mode-description").textContent'), /全部现存明细及后续新增明细/);
});

test("identity-confirmed record ownership displays its Chinese provenance", () => {
  const app = page();
  assert.equal(app.evaluate('projectCell({project_name: "已核对项目", assignment_origin: "identity_confirmation"}).children[0].textContent'), "身份核对归属");
});
