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
      const style = new Map();
      this.style = {setProperty(name, value) { style.set(name, value); }, getPropertyValue(name) { return style.get(name); }};
    }
    addEventListener(name, listener) {
      if (!this.listeners.has(name)) this.listeners.set(name, []);
      this.listeners.get(name).push(listener);
    }
    emit(name, fields = {}) {
      for (const listener of this.listeners.get(name) || []) listener({target: this, preventDefault() {}, ...fields});
    }
    contains(element) { return this === element || this.children.some((child) => child.contains(element)); }
    get options() { return this.children; }
    setAttribute(name, value) { this.attributes.set(name, value); }
    getAttribute(name) { return this.attributes.get(name) ?? null; }
    removeAttribute(name) { this.attributes.delete(name); }
    querySelectorAll(selector) {
      const matches = [];
      function visit(element) {
        if (selector === "input:checked" && element.type === "checkbox" && element.checked) matches.push(element);
        if (selector.startsWith(".") && element.className?.split(" ").includes(selector.slice(1))) matches.push(element);
        element.children.forEach(visit);
      }
      this.children.forEach(visit);
      return matches;
    }
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
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
        if (["[data-association-select]", "[data-association-group]", "[data-usage-select]"].includes(selector)) {
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
    state.sources = [{kind: "windows", configured: true, root: "C:\\\\Example\\\\.codex", status: "ready"}];
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

test("ledger settings dismisses when leaving and returns focus on Escape", () => {
  const app = page();
  const state = app.evaluate(`
    const summary = document.createElement("summary");
    const action = $("source-options");
    ledgerSettings.append(summary, action);
    ledgerSettings.querySelector = () => summary;
    ledgerSettings.open = true;
    ledgerSettings.emit("focusout", {relatedTarget: action});
    const keptOpenInside = ledgerSettings.open;
    ledgerSettings.emit("focusout", {relatedTarget: $("main")});
    const closedOnFocusLeave = !ledgerSettings.open;
    ledgerSettings.open = true;
    document.body.emit("click", {target: action});
    const keptOpenOnInnerClick = ledgerSettings.open;
    document.body.emit("click", {target: $("main")});
    const closedOnOuterClick = !ledgerSettings.open;
    ledgerSettings.open = true;
    let escaped = false;
    ledgerSettings.emit("keydown", {key: "Escape", preventDefault() { escaped = true; }});
    [keptOpenInside, closedOnFocusLeave, keptOpenOnInnerClick, closedOnOuterClick,
      escaped && !ledgerSettings.open && summary.focused];
  `);
  assert.deepEqual([...state], [true, true, true, true, true]);
});

test("settings dialogs dismiss the menu and retain its visible summary as the focus origin", async () => {
  const app = page();
  const source = app.evaluate(`
    const summary = document.createElement("summary");
    summary.getClientRects = () => [{}];
    ledgerSettings.querySelector = () => summary;
    ledgerSettings.open = true;
    $("source-options").emit("click");
    const origin = !ledgerSettings.open && $("source-dialog").open && state.sourceSettings.trigger === summary;
    summary.focused = false;
    $("source-dialog").close();
    [origin, summary.focused];
  `);
  assert.deepEqual([...source], [true, true]);
  app.replyTo("/api/codex-sources", true, {sources: []});
  assert.equal(app.evaluate(`
    ledgerSettings.open = true;
    $("review-data").emit("click");
    const reviewOrigin = !ledgerSettings.open && state.reconciliationView.trigger === summary;
    summary.focused = false;
    $("reconciliation-dialog").close();
    reviewOrigin && summary.focused;
  `), true);
  app.replyTo(app.pendingUrls()[0], true, {});
  assert.equal(app.evaluate(`
    let backupOrigin = false;
    $("backup-dialog").showModal = function () {
      backupOrigin = !ledgerSettings.open && summary.focused;
      this.open = true;
    };
    ledgerSettings.open = true;
    summary.focused = false;
    $("backup-options").emit("click");
    backupOrigin;
  `), true);
  app.statusReply({});
  await new Promise((resolve) => setImmediate(resolve));
});

test("source card prioritizes failure, running, review and recovery with historical data", () => {
  const app = page();
  app.evaluate(`state.ledger = {
    counts: {detail_count: 2}, coverage: {start_date: "2026-10-01", end_date: "2026-10-02"},
    last_successful_sync_at: "2026-10-02T02:47:00Z"
  }; state.sync = {status: "failed", message: "来源读取超过时限。"}; renderSource();`);
  assert.equal(app.evaluate('$("source-mode").textContent'), "同步失败");
  assert.match(app.evaluate('$("sync-error").textContent'), /来源读取超过时限/);
  assert.match(app.evaluate('$("sync-error").textContent'), /当前显示已保存的本地数据/);
  assert.match(app.evaluate('$("source-description").textContent'), /上次成功/);
  assert.match(app.evaluate('$("source-description").textContent'), /^2 条明细 · /);
  assert.match(app.evaluate('$("source-description").textContent'), /2026-10-01 至 2026-10-02/);

  app.evaluate('state.syncBusy = true; renderSource();');
  assert.equal(app.evaluate('$("source-mode").textContent'), "同步中");
  assert.equal(app.evaluate('$("sync-error").hidden'), true);
  assert.equal(app.evaluate('$("load-default").disabled'), true);

  app.evaluate('state.syncBusy = false; state.sync = {status: "needs_review"}; renderSource();');
  assert.equal(app.evaluate('$("source-mode").textContent'), "需要核对");
  assert.equal(app.evaluate('$("sync-error").hidden'), true);

  app.evaluate('state.sync = {status: "completed"}; renderSource();');
  assert.equal(app.evaluate('$("source-mode").textContent'), "已同步");
  assert.equal(app.evaluate('$("load-default").disabled'), false);
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
  app.evaluate(`state.ledger = {counts: {}, coverage: {}};
    state.sources[0].status = "unavailable"; state.sources[0].message = "找不到所选 Codex 目录。";
    state.sync = null; renderSource();`);
  assert.equal(app.evaluate('$("source-mode").textContent'), "同步失败");
  assert.match(app.evaluate('$("sync-error").textContent'), /找不到所选 Codex 目录/);
  assert.match(app.evaluate('$("sync-error").textContent'), /尚未成功同步，当前统计不代表实际用量/);
  assert.match(app.evaluate('$("source-description").textContent'), /尚无成功同步/);
});

test("saved review data can exist before the first successful sync", () => {
  const app = page();
  app.evaluate(`state.ledger = {counts: {detail_count: 2}, coverage: {}};
    state.sync = {status: "failed", message: "来源读取失败。"}; renderSource();`);
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
  assert.equal(app.evaluate('$("load-default").disabled'), true);
  app.reply(true, {id: "retry", status: "completed"});
  await retry;
  assert.equal(app.evaluate('$("source-mode").textContent'), "已同步");
  assert.equal(app.evaluate('$("sync-error").hidden'), true);
  assert.equal(app.evaluate('$("load-default").disabled'), false);
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
  assert.equal(app.evaluate('$("load-default").disabled'), false);
});

test("late refresh success or failure from an older job cannot affect a retry", async () => {
  for (const staleFails of [false, true]) {
    const app = page();
    app.evaluate(`state.ledger = {counts: {detail_count: 2}, coverage: {},
      last_successful_sync_at: "2026-10-02T02:47:00Z"};
      state.analysis = {analysis_id: "current"}; $("notice").hidden = true;
      $("reconciliation-count").textContent = "4";`);
    const old = app.evaluate("loadSource()");
    app.reply(true, {id: "old", status: "failed", message: "旧来源失败。"});
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(app.evaluate('$("source-mode").textContent'), "同步失败");
    const retry = app.evaluate("loadSource()");
    if (staleFails) app.reply(false, {code: "data_changed", message: "过时刷新失败。"});
    else app.reply(true, {counts: {detail_count: 999}, coverage: {}});
    app.reply(true, {projects: [{id: "old"}]});
    app.reply(true, {total: 99});
    await old;
    assert.equal(app.evaluate('$("source-mode").textContent'), "同步中");
    assert.equal(app.evaluate('$("load-default").disabled'), true);
    assert.equal(app.evaluate("state.ledger.counts.detail_count"), 2);
    assert.equal(app.evaluate("state.config.projects.length"), 0);
    assert.equal(app.evaluate('$("reconciliation-count").textContent'), "4");
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
    assert.equal(app.evaluate('$("load-default").disabled'), false);
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

test("initial rendering restores per-source failures when no job exists", async () => {
  const app = page();
  app.evaluate('refreshProjects = () => new Promise(() => {});');
  app.statusReply({csrf_token: "token", today: "2026-10-03", version: "test", ledger: {
    counts: {}, coverage: {}, last_successful_sync_at: "2026-10-02T02:47:00Z"
  }, sources: [{kind: "windows", configured: true, status: "failed", message: "上次同步未完成。"}]});
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(app.evaluate('$("source-mode").textContent'), "同步失败");
  assert.match(app.evaluate('$("sync-error").textContent'), /上次同步未完成/);
});

test("reload ignores jobs for replaced source bindings and preserves matching results", async () => {
  const windows = {kind: "windows", configured: true, root: "WIN", since: null, status: "no_change"};
  const wsl = {kind: "wsl", configured: true, root: "/codex", distribution: "Ubuntu", status: "completed"};
  const matching = [windows, wsl];
  for (const sources of [
    [{...windows, root: "NEW", status: "ready"}, wsl],
    [{...windows, since: "2026-10-02", status: "ready"}, wsl],
    [windows, {...wsl, distribution: "Debian", status: "ready"}],
    [windows, {...wsl, configured: false, status: "unconfigured"}],
    matching,
  ]) {
    const app = page();
    app.evaluate('refreshProjects = () => new Promise(() => {});');
    app.statusReply({csrf_token: "token", today: "2026-10-03", version: "test", ledger: {
      counts: {detail_count: 4}, coverage: {}, last_successful_sync_at: "2026-10-02T02:47:00Z",
    }, sources, sync: {id: "attempt", status: "failed", message: "旧来源失败。", sources: matching}});
    await new Promise((resolve) => setImmediate(resolve));
    assert.match(app.evaluate('$("source-description").textContent'), /4 条明细.*上次成功同步/);
    assert.equal(app.evaluate("state.sync?.id"), sources === matching ? "attempt" : undefined);
    assert.equal(app.evaluate('$("sync-error").hidden'), sources !== matching);
    const mode = sources === matching ? "同步失败" : sources[1].configured ? "本地资料" : "已同步";
    assert.equal(app.evaluate('$("source-mode").textContent'), mode);
    assert.equal(app.evaluate("state.analysis.analysis_id"), "old");
  }
});

test("an in-flight poll for an old binding cannot replace newly discovered sources", async () => {
  const app = page();
  app.evaluate('state.sources[0].root = "OLD";');
  const loading = app.evaluate("loadSource()");
  const previous = {kind: "windows", configured: true, root: "OLD"};
  app.replyTo("/api/sync", true, {id: "old", status: "running",
    sources: [{...previous, status: "running"}]});
  await new Promise((resolve) => setTimeout(resolve, 500));
  const opened = app.evaluate('openSourceSettings($("source-options"))');
  app.replyTo("/api/codex-sources", true, {
    sources: [{...previous, root: "NEW", status: "ready"}], distributions: [],
  });
  await opened;
  app.replyTo("/api/sync/old", true, {id: "old", status: "completed",
    sources: [{...previous, status: "completed"}]});
  await loading;
  assert.equal(app.evaluate('currentSource("windows").root'), "NEW");
  assert.equal(app.evaluate('$("source-mode").textContent'), "本地资料");
  assert.equal(app.evaluate("state.analysis.analysis_id"), "old");
  assert.equal(app.evaluate("state.syncBusy"), false);
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
  assert.equal(app.evaluate('$("load-default").disabled'), false);
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
    app.replyLatest("/api/reconciliations/summary", true, {total: 24});
    await new Promise((resolve) => setImmediate(resolve));
    if (staleFails) {
      app.replyTo("/api/projects", false, {code: "data_changed", message: "旧项目请求失败。"});
      app.replyTo("/api/reconciliations/summary", false, {code: "data_changed", message: "旧核对请求失败。"});
    } else {
      app.replyTo("/api/projects", true, {revision: 2, projects: []});
      app.replyTo("/api/reconciliations/summary", true, {total: 3});
    }
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(app.evaluate("state.config.revision"), 8);
    assert.equal(app.evaluate('$("reconciliation-count").textContent'), "24");
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

test("project and availability changes automatically use the home range and refresh all views", async () => {
  const app = page();
  app.evaluate('$("project-select").value = "p1"; $("availability-mode").value = "available"; $("project-select").emit("change");');
  await new Promise((resolve) => setImmediate(resolve));
  const request = app.pendingRequests().find((item) => item.url === "/api/analysis");
  assert.deepEqual(JSON.parse(request.options.body), {
    classification_revision: 0,
    time_range: {kind: "preset", preset: "last_14d", follow_now: true},
    project_id: "p1", availability_mode: "available",
  });
  assert.equal(app.evaluate("state.analysis"), null);
  app.replyTo("/api/analysis", true, {analysis_id: "p1", project_name: "项目",
    start_date: "2026-11-10", end_date: "2026-11-24", summary: {record_count: 0, total_cost_usd: "0"}, availability_mode: "available"});
  await new Promise((resolve) => setImmediate(resolve));
  app.replyTo("/api/analysis/p1/trend", true, {grain: "day", points: []});
  app.replyTo("/api/analysis/p1/details?kind=daily&size=50", true, {rows: [], total: 0});
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(app.evaluate("state.analysis.analysis_id"), "p1");
  assert.equal(app.evaluate('$("analyze").hidden'), true);
  app.evaluate('$("availability-mode").value = "all"; $("availability-mode").emit("change");');
  await new Promise((resolve) => setImmediate(resolve));
  const allRequest = app.pendingRequests().find((item) => item.url === "/api/analysis");
  assert.equal(JSON.parse(allRequest.options.body).availability_mode, "all");
  app.disconnectTo("/api/analysis");
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(app.evaluate('$("analyze").hidden'), false);
});

test("late trends cannot replace current exact bars or invalidate their analysis", async () => {
  const exact = "123456789123456789.000000000000019";
  for (const obsolete of ["success", "expired", "disconnect"]) {
    const app = page();
    const prior = app.evaluate("loadTrend()");
    replacePreview(app);
    const latest = app.evaluate("loadTrend()");
    app.replyTo("/api/analysis/new/trend", true, {grain: "day", points: [
      {start_date: "2026-11-01", end_date: "2026-11-01", total_cost_usd: exact, record_count: 1, unpriced_count: 0},
      {start_date: "2026-11-02", end_date: "2026-11-02", total_cost_usd: "0", record_count: 1, unpriced_count: 1},
    ]});
    await latest;
    if (obsolete === "success") app.replyTo("/api/analysis/old/trend", true, {grain: "month", points: []});
    else if (obsolete === "expired") app.replyTo("/api/analysis/old/trend", false, {code: "availability_changed"});
    else app.disconnectTo("/api/analysis/old/trend");
    await prior;
    assertNewPreview(app);
    assert.equal(app.evaluate('$("trend-heading").textContent'), "每日费用趋势");
    const labels = app.evaluate('$("trend-plot").querySelectorAll(".trend-bar").map((bar) => bar.getAttribute("aria-label"))');
    assert.ok(labels[0].includes(exact + " USD"));
    assert.match(labels[1], /缺参考价/);
    assert.doesNotMatch(labels[1], /0 USD/);
    assert.equal(app.evaluate('$("trend-plot").querySelector(".trend-bar").style.getPropertyValue("--bar-height")'), "100%");
    assert.equal(app.evaluate('$("trend-retry").hidden'), true);
  }
});

test("a disconnected trend can retry locally and current expiry invalidates an open claim", async () => {
  const app = page();
  app.evaluate(`state.analysis = {analysis_id: "old", project_name: "项目", availability_mode: "available",
    start_date: "2026-11-01", end_date: "2026-11-14", summary: {record_count: 2, total_cost_usd: "123.45001"}};
    $("claim-purpose").value = "项目开发"; openClaimDialog();`);
  assert.equal(app.evaluate('$("create-batch").disabled'), false);
  const failed = app.evaluate("loadTrend()");
  app.disconnectTo("/api/analysis/old/trend");
  await failed;
  assert.equal(app.evaluate('$("trend-retry").hidden'), false);
  assert.equal(app.evaluate('$("create-batch").disabled'), false);
  const retry = app.evaluate("loadTrend()");
  app.replyTo("/api/analysis/old/trend", false, {code: "availability_changed", message: "当前用量已变化。"});
  await retry;
  assert.equal(app.evaluate("state.analysis"), null);
  assert.equal(app.evaluate('$("create-batch").disabled'), true);
  assert.equal(app.evaluate('$("claim-purpose").value'), "项目开发");
  assert.equal(app.evaluate('$("claim-preview-cost").textContent'), "123.45001 USD");
  assert.equal(app.evaluate('$("claim-refresh-preview").hidden'), false);
  app.evaluate(`state.analysis = {analysis_id: "fresh", project_name: "项目", availability_mode: "available",
    start_date: "2026-11-02", end_date: "2026-11-14", summary: {record_count: 1, total_cost_usd: "7.99"}}; syncActions();`);
  assert.equal(app.evaluate('$("create-batch").disabled'), true);
  await app.evaluate("refreshClaimPreview()");
  assert.equal(app.evaluate('$("create-batch").disabled'), false);
  assert.equal(app.evaluate('$("claim-preview-cost").textContent'), "7.99 USD");
  assert.equal(app.evaluate('$("claim-purpose").value'), "项目开发");
});

test("daily scope belongs to its page requests and leaves the claim scope intact", async () => {
  const app = page();
  app.evaluate(`state.analysis = {analysis_id: "old", project_name: "项目", availability_mode: "available",
    start_date: "2026-11-01", end_date: "2026-11-14", summary: {record_count: 2, total_cost_usd: "200"}};`);
  const first = app.evaluate('selectPreviewTab("daily", "2026-11-01")');
  const second = app.evaluate('selectPreviewTab("daily", "2026-11-02")');
  app.replyTo("/api/analysis/old/details?kind=daily&size=50&day=2026-11-02", true, {
    rows: [{date: "2026-11-02", total_cost_usd: "11"}], total: null, next_cursor: "day2-page2",
  });
  await second;
  app.replyTo("/api/analysis/old/details?kind=daily&size=50&day=2026-11-01", false, {code: "analysis_expired"});
  await first;
  assert.equal(app.evaluate('$("daily-selection-label").textContent'), "仅看 2026-11-02");
  assert.equal(app.evaluate("state.rows[0]?.date"), "2026-11-02");
  assert.equal(app.evaluate("state.nextCursor"), "day2-page2");
  app.evaluate("openClaimDialog()");
  assert.equal(app.evaluate('$("claim-preview-range").textContent'), "2026-11-01 至 2026-11-14（北京时间）");
  assert.equal(app.evaluate('$("claim-preview-cost").textContent'), "200 USD");
  app.evaluate('$("claim-dialog").close()');
  const models = app.evaluate('selectPreviewTab("models")');
  app.replyTo("/api/analysis/old/details?kind=models&size=50", true, {rows: [], total: 0});
  await models;
  assert.equal(app.evaluate("state.dailyDate"), "");
  assert.equal(app.evaluate('$("daily-selection").hidden'), true);
});

test("daily, model and individual views use detail-only records", async () => {
  const html = fs.readFileSync(path.join(__dirname, "../src/aha/web/index.html"), "utf8");
  assert.deepEqual([...html.matchAll(/data-tab="([^"]+)"/g)].map(([, tab]) => tab), ["daily", "models", "details"]);

  const app = page();
  const load = app.evaluate('selectPreviewTab("daily")');
  app.replyTo("/api/analysis/old/details?kind=daily&size=50", true, {total: 1, rows: [{
    date: "2026-11-02", project_name: "项目甲", model: "model-a", detail_count: 9, total_cost_usd: "3.25",
  }]});
  await load;
  const [headers, values] = JSON.parse(app.evaluate(`(() => {
    const [head, body] = $("preview-table").children[0].children;
    return JSON.stringify([head, body].map((part) => part.children[0].children.map((cell) => cell.textContent)));
  })()`));
  assert.deepEqual(headers.slice(0, 4), ["日期", "项目", "模型", "明细数"]);
  assert.deepEqual(values.slice(0, 4), ["2026-11-02", "项目甲", "model-a", "9"]);
});

test("zero claim amount needs an explanation and a lost save reply retries the same request", async () => {
  const app = page();
  app.evaluate(`state.analysis = {analysis_id: "claim-scope", project_name: "项目", availability_mode: "available",
    start_date: "2026-11-01", end_date: "2026-11-14", summary: {record_count: 1, total_cost_usd: "1"}};
    openClaimDialog(); $("claim-amount").value = "0"; $("claim-currency").value = "CNY"; $("claim-form").emit("submit");`);
  assert.equal(app.pendingUrls().includes("/api/batches/preview"), false);
  assert.equal(app.evaluate('$("claim-note").getAttribute("aria-invalid")'), "true");
  assert.equal(app.evaluate('$("claim-note").focused'), true);
  app.evaluate('$("claim-note").value = "公司已承担"; $("claim-form").emit("submit");');
  const preview = JSON.parse(app.pendingRequests().find((item) => item.url === "/api/batches/preview").options.body);
  assert.equal(preview.analysis_id, "claim-scope");
  assert.equal(preview.claim.amount, "0");
  app.replyTo("/api/batches/preview", true, {blocking: false});
  await new Promise((resolve) => setImmediate(resolve));
  const first = app.pendingRequests().find((item) => item.url === "/api/batches").options.body;
  app.disconnectTo("/api/batches");
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(app.evaluate('$("claim-dialog").open'), true);
  app.evaluate('$("claim-form").emit("submit")');
  assert.equal(app.pendingUrls().includes("/api/batches/preview"), false);
  assert.equal(app.pendingRequests().find((item) => item.url === "/api/batches").options.body, first);
  app.replyTo("/api/batches", false, {code: "usage_claimed", message: "用量已被占用"});
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(app.evaluate('$("create-batch").disabled'), true);
  assert.equal(app.evaluate('$("claim-amount").value'), "0");
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

test("an empty minute-range revision preview describes its scope and blocks saving", () => {
  const app = page();
  app.evaluate(`const emptyPreview = {
    project_name: "项目", start_date: "2026-10-26", end_date: "2026-10-26",
    time_range: {start_at: "2026-10-26T08:00:00+08:00",
      end_before: "2026-10-26T09:01:00+08:00", precision: "minute"},
    summary: {record_count: 0, total_cost_usd: "0"}
  }; state.revision = {analysis: emptyPreview}; $("revision-basis").value = "current";
  renderRevisionPreview(emptyPreview); syncActions();`);
  const text = app.evaluate(`(function text(item) {
    return (item.textContent || "") + item.children.map(text).join(" ");
  })($("revision-preview"))`);
  assert.match(text, /当前范围没有可用记录/);
  assert.match(text, /08:00 至 2026-10-26 09:00/);
  assert.doesNotMatch(text, /参考成本 0 USD/);
  assert.equal(app.evaluate('$("save-revision").disabled'), true);
});

test("archived revisions show saved costs and material actions without an edit action", () => {
  const app = page();
  app.evaluate(`state.batch = {id: "archived", number: "AHA-000001", revisions: [{
    version: 1, is_effective: true, status: "submitted", created_at: "2024-01-30T00:00:00Z",
    can_edit: false, can_reimburse: true,
    claim: {amount: null, purpose: "归档用途"},
    analysis: {project_name: "旧项目", start_date: "2024-01-29", end_date: "2024-01-29",
      summary: {total_cost_usd: "1.25", rollup_count: 1},
      summary_complete: false,
      time_coverage: {complete: false, omitted_rollup_count: 1, omitted_days: ["2024-01-29"]}}
  }]}; renderBatchDetail();`);
  const text = app.evaluate(`(function text(item) {
    return (item.textContent || "") + item.children.map(text).join(" ");
  })($("batch-detail"))`);
  assert.match(text, /参考成本 1\.25 USD/);
  assert.match(text, /归档用途/);
  assert.match(text, /下载材料.*标记已报销/);
  assert.doesNotMatch(text, /修改报销记录|历史日汇总|统计不完整/);
});

test("empty current filters explain retained history without changing the chosen range", () => {
  const app = page();
  const before = app.evaluate("JSON.stringify(timeRange.getIntent())");
  app.evaluate(`state.ledger = {coverage: {start_date: "2026-06-17", end_date: "2026-11-10"}};
    renderEmptyRange({summary: {record_count: "0"}});`);
  assert.equal(app.evaluate('$("empty-range-note").hidden'), false);
  assert.match(app.evaluate('$("empty-range-description").textContent'), /本地明细覆盖/);
  assert.match(app.evaluate('$("empty-range-description").textContent'), /2026-06-17 至 2026-11-10/);
  assert.equal(app.evaluate("JSON.stringify(timeRange.getIntent())"), before);
  app.evaluate('renderEmptyRange({summary: {record_count: "1"}});');
  assert.equal(app.evaluate('$("empty-range-note").hidden'), true);
});

test("an unbound restored ledger offers native sources while retaining the local preview", async () => {
  const app = page();
  app.evaluate(`state.sources = [{kind: "windows", configured: false, status: "unconfigured"},
    {kind: "wsl", configured: false, status: "unconfigured"}]; renderSource();`);
  assert.equal(app.evaluate('$("source-mode").textContent'), "待确认本机来源");
  const operation = app.evaluate("loadSource()");
  app.replyTo("/api/codex-sources", true, {distributions: ["Ubuntu"]});
  await operation;
  assert.equal(app.evaluate('$("source-dialog").open'), true);
  assert.equal(app.evaluate("state.analysis.analysis_id"), "old");
  assert.equal(app.evaluate("state.syncBusy"), false);
  assert.equal(app.pendingUrls().includes("/api/sync"), false);
  app.evaluate('$("source-dialog").close();');
  assert.equal(app.evaluate('$("load-default").focused'), true);
});

test("WSL confirmation sends its selected distribution and updates only that source", async () => {
  const app = page();
  const opened = app.evaluate('openSourceSettings($("source-options"))');
  app.replyTo("/api/codex-sources", true, {distributions: ["Ubuntu", "Debian"]});
  await opened;
  assert.equal(app.evaluate('$("save-wsl-source").disabled'), true);
  app.evaluate('$("wsl-distribution").value = "Ubuntu"; $("wsl-distribution").emit("change");');
  assert.equal(app.evaluate('$("save-wsl-source").disabled'), false);
  const operation = app.evaluate('saveSourceSettings("wsl")');
  const payload = JSON.parse(app.pendingRequests()[0].options.body);
  assert.deepEqual(payload, {kind: "wsl", root: "", since: "", distribution: "Ubuntu"});
  assert.equal(app.evaluate('$("load-default").disabled'), true);
  app.replyTo("/api/codex-sources", true, {sources: [
    {kind: "wsl", root: "/home/example/.codex", distribution: "Ubuntu", configured: true, status: "ready"},
  ]});
  await operation;
  assert.equal(app.evaluate('currentSource("windows").configured'), true);
  assert.equal(app.evaluate('$("wsl-source-root").value'), "/home/example/.codex");
  assert.match(app.evaluate('$("source-settings-status").textContent'), /已确认 WSL 来源/);
  assert.equal(app.evaluate("state.analysis.analysis_id"), "old");
  assert.equal(app.pendingUrls().includes("/api/sync"), false);
  app.evaluate('$("wsl-distribution").value = "Debian"; $("wsl-distribution").emit("change");');
  assert.equal(app.evaluate('$("wsl-source-root").value'), "");
});

test("closed or replaced source discovery ignores stale success, rejection and disconnect", async () => {
  for (const response of ["success", "conflict", "disconnect"]) {
    const app = page();
    const old = app.evaluate('openSourceSettings($("source-options"))');
    app.evaluate('$("source-dialog").close()');
    const latest = app.evaluate('openSourceSettings($("source-options"))');
    app.replyLatest("/api/codex-sources", true, {distributions: ["Debian"], history_default_since: "2026-11-23"});
    await latest;
    app.evaluate('$("windows-source-root").value = "CURRENT";');
    if (response === "success") app.replyTo("/api/codex-sources", true, {distributions: ["Ubuntu"], history_default_since: "2026-10-01"});
    if (response === "conflict") app.replyTo("/api/codex-sources", false, {code: "data_changed", message: "旧请求"});
    if (response === "disconnect") app.disconnectTo("/api/codex-sources");
    await old;
    assert.equal(app.evaluate('$("wsl-distribution").options.at(-1).value'), "Debian");
    assert.equal(app.evaluate('$("windows-source-root").value'), "CURRENT");
    assert.equal(app.evaluate('$("wsl-source-since").value'), "2026-11-23");
    assert.equal(app.evaluate('$("source-settings-error").hidden'), true);
    assert.equal(app.evaluate("state.analysis.analysis_id"), "old");
  }
});

test("an unbound source defaults to legacy coverage while a confirmed all-history setting remains empty", async () => {
  const app = page();
  const opened = app.evaluate('openSourceSettings($("source-options"))');
  app.replyTo("/api/codex-sources", true, {
    history_default_since: "2026-11-18",
    distributions: ["Ubuntu"],
    sources: [{kind: "windows", configured: true, status: "ready", root: "CURRENT", since: null}],
  });
  await opened;
  assert.equal(app.evaluate('$("windows-source-since").value'), "");
  assert.equal(app.evaluate('$("wsl-source-since").value'), "2026-11-18");
  app.evaluate('$("wsl-distribution").value = "Ubuntu"; $("wsl-distribution").emit("change");');
  assert.equal(app.evaluate('$("wsl-source-since").value'), "2026-11-18");
  app.evaluate('$("wsl-source-all-history").emit("click");');
  const saved = app.evaluate('saveSourceSettings("wsl")');
  assert.deepEqual(JSON.parse(app.pendingRequests()[0].options.body),
    {kind: "wsl", root: "", since: "", distribution: "Ubuntu"});
  app.replyTo("/api/codex-sources", true, {sources: [
    {kind: "wsl", configured: true, status: "ready", root: "/example", distribution: "Ubuntu", since: null},
  ]});
  await saved;
  assert.equal(app.evaluate('$("wsl-source-since").value'), "");
});

test("a saved old source can update the card without replacing a newer source draft", async () => {
  const app = page();
  const opened = app.evaluate('openSourceSettings($("source-options"))');
  app.replyTo("/api/codex-sources", true, {distributions: []});
  await opened;
  app.evaluate('$("windows-source-root").value = "OLD";');
  const old = app.evaluate('saveSourceSettings("windows")');
  app.evaluate('$("source-dialog").close()');
  const latest = app.evaluate('openSourceSettings($("source-options"))');
  app.replyLatest("/api/codex-sources", true, {distributions: []});
  await latest;
  assert.equal(app.evaluate('$("save-windows-source").disabled'), true);
  app.evaluate('$("windows-source-root").value = "NEW";');
  app.replyTo("/api/codex-sources", true, {sources: [
    {kind: "windows", root: "CANONICAL_OLD", configured: true, status: "ready"},
  ]});
  await old;
  assert.equal(app.evaluate('currentSource("windows").root'), "CANONICAL_OLD");
  assert.equal(app.evaluate('$("windows-source-root").value'), "NEW");
  assert.equal(app.evaluate('$("source-settings-status").hidden'), true);
  assert.equal(app.evaluate('$("save-windows-source").disabled'), false);
});

const windowsSynced = {
  kind: "windows", root: "C:\\Example\\.codex", configured: true, status: "completed",
  last_success_at: "2026-11-24T02:00:00Z",
  result: {coverage_from: "2026-11-22T10:00:00+08:00", coverage_through: "2026-11-24T09:30:00+08:00",
    files: 3, new_count: 4, unchanged_count: 2, pending_count: 0, issues: {}},
};
const wslReading = {
  kind: "wsl", distribution: "Ubuntu", root: "/home/example/.codex", configured: true,
  status: "running", last_success_at: null,
};
test("a resolved startup job shows Windows results and WSL failure separately without posting another startup", async () => {
  const app = page();
  app.evaluate(`refreshProjects = async () => {}; refreshReconciliations = async () => {};
    refreshBatches = async () => {}; analyze = async () => {};`);
  const sources = [windowsSynced, {...wslReading, status: "unavailable", message: "WSL 暂时无法读取。"}];
  app.statusReply({csrf_token: "token", today: "2026-11-24", version: "test",
    ledger: {counts: {detail_count: 4}, coverage: {}}, sources,
    sync: {id: "launch", status: "needs_review", sources}});
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(app.evaluate('$("source-mode").textContent'), "部分完成");
  assert.match(app.evaluate('$("source-endpoints").children[0].children[1].textContent'), /2026\/11\/24/);
  assert.match(app.evaluate('$("source-endpoints").children[0].children[2].textContent'), /09:30:00/);
  assert.match(app.evaluate('$("source-endpoints").children[0].children[3].textContent'), /新增 4 条.*检查 3 个文件/);
  assert.equal(app.evaluate('$("source-endpoints").children[1].children[0].children[1].textContent'), "暂不可用");
  assert.match(app.evaluate('$("source-endpoints").children[1].children[2].textContent'), /WSL 暂时无法读取/);
  assert.equal(app.pendingUrls().includes("/api/sync"), false);
});

test("a complete Windows and WSL retry clears both saved source coverage warnings", async () => {
  const app = page();
  const partialSources = [windowsSynced, wslReading].map((source) => ({...source, status: "partial",
    result: {issues: {invalid_cumulative_usage: 1, line_limit: 1}}}));
  app.evaluate(`state.sources = ${JSON.stringify(partialSources)};
    state.sync = {status: "needs_review"}; renderSource();
    refreshLedger = async () => { state.ledger.last_successful_sync_at = "2026-11-25T01:32:00Z"; };
    refreshProjects = async () => {}; refreshReconciliations = async () => {};
    run = async () => {};`);
  assert.equal(app.evaluate('$("source-mode").textContent'), "部分完成");
  assert.equal(app.evaluate('$("sync-error").hidden'), false);
  assert.match(app.evaluate('$("source-endpoints").children[0].children.at(-1).textContent'), /累计用量无法核实/);
  assert.match(app.evaluate('$("source-endpoints").children[1].children.at(-1).textContent'), /单条日志过长/);

  const operation = app.evaluate("loadSource()");
  app.replyTo("/api/sync", true, {id: "retry", status: "completed", sources: [
    windowsSynced, {...wslReading, status: "no_change", result: {issues: {}}},
  ]});
  await operation;
  assert.equal(app.evaluate('$("source-mode").textContent'), "已同步");
  assert.equal(app.evaluate('$("sync-error").hidden'), true);
  assert.match(app.evaluate('$("source-description").textContent'), /上次成功同步 2026\/11\/25/);
  assert.equal(app.evaluate('$("source-endpoints").children[1].children[0].children[1].textContent'), "无新增");
  const text = app.evaluate(`(function text(item) {
    return (item.textContent || "") + item.children.map(text).join(" ");
  })($("source-endpoints"))`);
  assert.doesNotMatch(text, /部分覆盖|累计用量无法核实|单条日志过长/);
});

test("one committed source expires old saving even while the second source is running or cancelled", async () => {
  const app = page();
  app.evaluate(`state.busy = true; state.pendingBatch = {signature: "old"};
    refreshLedger = async () => {}; refreshProjects = async () => {}; refreshReconciliations = async () => {};`);
  const operation = app.evaluate("loadSource()");
  assert.deepEqual(JSON.parse(app.pendingRequests()[0].options.body), {trigger: "manual"});
  app.replyTo("/api/sync", true, {id: "dual", status: "running", sources: [windowsSynced, wslReading]});
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(app.evaluate("state.analysis"), null);
  assert.equal(app.evaluate("state.pendingBatch"), null);
  assert.equal(app.evaluate('$("cancel-sync").disabled'), false);
  const cancel = app.evaluate("cancelSync()");
  assert.deepEqual(JSON.parse(app.pendingRequests()[0].options.body), {});
  assert.equal(app.evaluate('$("cancel-sync").disabled'), true);
  await new Promise((resolve) => setTimeout(resolve, 500));
  const sources = [windowsSynced, {...wslReading, status: "cancelled"}];
  app.replyTo("/api/sync/dual", true, {id: "dual", status: "cancelled", sources});
  await operation;
  app.replyTo("/api/sync/dual/cancel", false, {code: "data_changed", message: "过时的取消结果"});
  await cancel;
  assert.equal(app.evaluate('$("source-mode").textContent'), "已取消");
  assert.equal(app.evaluate('$("cancel-sync").hidden'), true);
  assert.equal(app.evaluate("state.syncPreviewPending"), true);
  assert.match(app.evaluate('$("notice").children[0].textContent'), /完成的来源已入账/);
});

function reconciliationPage(cases = [], extra = {}) {
  return {
    cases, total: cases.length, eligible_count: cases.filter((item) => item.batch_eligible).length,
    next_cursor: null, version: "version-1", sources: [{id: "windows", name: "Windows"}], ...extra,
  };
}
function reconciliationPreview(count, previewHash, extra = {}) {
  return {count, preview_hash: previewHash, candidate_count: 0, current_cost_usd: "0", candidate_cost_usd: "0", ...extra};
}
function replyReconciliationPage(app, result) {
  app.replyTo(app.pendingUrls().find((url) => url.startsWith("/api/reconciliations/page?")), true, result);
}
async function openReconciliationPage(app, result = reconciliationPage([{id: "case-1", generation: 2}])) {
  const opened = app.evaluate("openReconciliations()");
  replyReconciliationPage(app, result);
  await opened;
}
function commitSingleReconciliation(app) {
  return app.evaluate(`commitReconciliation(state.reconciliationView, "/api/reconciliations/case-1",
    {choice: "current", reason: "已核对", expected_generation: 2}, {})`);
}
function assertConfirmationReasonDefault(app, field) {
  assert.equal(app.evaluate(`${field}.value`), "已人工确认");
  assert.equal(app.evaluate(`${field}.placeholder`), "已人工确认");
}

test("reconciliation immediately expires saving and automatically previews the same filters", async () => {
  const app = page();
  await openReconciliationPage(app);
  app.evaluate(`$("project-select").value = "original-project";
    timeRange.setIntent({kind: "preset", preset: "last_7d", follow_now: true});
    state.pendingBatch = {signature: "old"};
    refreshLedger = async () => {}; refreshProjects = async () => {};
    refreshReconciliations = async () => {};
    analyze = async () => { state.repreview = {project: $("project-select").value, intent: timeRange.getIntent()}; };`);
  const operation = commitSingleReconciliation(app);
  assert.equal(app.evaluate("state.analysis"), null);
  assert.equal(app.evaluate("state.pendingBatch"), null);
  assert.equal(app.evaluate('$("create-batch").disabled'), true);
  app.reply(true, {state: "resolved"});
  await new Promise((resolve) => setImmediate(resolve));
  replyReconciliationPage(app, reconciliationPage());
  await operation;
  assert.equal(app.evaluate("state.repreview.project"), "original-project");
  assert.equal(app.evaluate("state.repreview.intent.preset"), "last_7d");
});

test("a reconciliation refresh failure leaves the old save identity expired", async () => {
  const app = page();
  await openReconciliationPage(app);
  app.evaluate(`state.pendingBatch = {signature: "old"};
    refreshProjects = async () => {}; refreshReconciliations = async () => {};`);
  const operation = commitSingleReconciliation(app);
  app.reply(true, {state: "resolved"});
  await new Promise((resolve) => setImmediate(resolve));
  app.disconnectTo("/api/ledger");
  app.disconnectTo(app.pendingUrls().find((url) => url.startsWith("/api/reconciliations/page?")));
  await operation;
  assert.equal(app.evaluate("state.analysis"), null);
  assert.equal(app.evaluate("state.pendingBatch"), null);
  assert.equal(app.evaluate('$("create-batch").disabled'), true);
  assert.equal(app.evaluate('$("reconciliation-saved").textContent'), "核对结果已保存。");
  assert.match(app.evaluate('$("reconciliation-error").textContent'), /连接中断/);
  assert.match(app.evaluate('$("filter-status").textContent'), /核对结果已保存/);
});

test("late reconciliation refreshes cannot overwrite a newer filter preview", async () => {
  for (const fail of [false, true]) {
    const app = page();
    await openReconciliationPage(app);
    app.evaluate(`refreshProjects = async () => {}; refreshReconciliations = async () => {};
      analyze = async () => { throw new Error("stale reconciliation must not requery"); };`);
    const operation = commitSingleReconciliation(app);
    app.reply(true, {state: "resolved"});
    await new Promise((resolve) => setImmediate(resolve));
    app.evaluate('state.filterGeneration += 1; state.analysis = {analysis_id: "newer"}; state.ledger = {newer: true};');
    if (fail) app.disconnectTo("/api/ledger");
    else app.replyTo("/api/ledger", true, {older: true});
    replyReconciliationPage(app, reconciliationPage());
    await operation;
    assert.equal(app.evaluate("state.analysis.analysis_id"), "newer");
    assert.equal(app.evaluate("state.ledger.newer"), true);
  }
});

test("reconciliation loads evidence on demand and explicit selections survive pagination", async () => {
  const app = page();
  const a = {id: "a", generation: 1, batch_eligible: true};
  const b = {id: "b", generation: 1, batch_eligible: false, type: "native_uncertain"};
  const c = {id: "c", generation: 2, batch_eligible: true};
  await openReconciliationPage(app, reconciliationPage([a, b], {total: 1401, eligible_count: 1300, next_cursor: "next"}));
  assert.deepEqual(app.pendingUrls(), []);
  assert.equal(app.evaluate("state.reconciliationView.controls.filter(({check}) => check).length"), 1);
  app.evaluate('state.reconciliationView.controls[1].detail.emit("click")');
  assert.deepEqual(app.pendingUrls(), ["/api/reconciliations/b"]);
  app.reply(true, {case: {...b, choices: ["current"], candidate_summary: {cache_read_tokens: 12}}});
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(app.evaluate('state.reconciliationView.controls[1].form.submit.getAttribute("data-reconciliation-submit")'), "b");
  assertConfirmationReasonDefault(app, "state.reconciliationView.controls[1].form.reason");
  assert.equal(app.evaluate("state.reconciliationView.controls[1].form.reason.required"), true);
  app.evaluate('$("reconciliation-select-page").checked = true; $("reconciliation-select-page").emit("change");');
  app.evaluate('$("reconciliation-next").emit("click");');
  assert.match(app.pendingUrls()[0], /cursor=next/);
  replyReconciliationPage(app, reconciliationPage([c], {total: 1401, eligible_count: 1300}));
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(app.evaluate('state.reconciliationView.selected.has("a")'), true);
  app.evaluate('state.reconciliationView.controls[0].check.checked = true; state.reconciliationView.controls[0].check.emit("change")');
  const preview = app.evaluate("previewReconciliationBatch(state.reconciliationView)");
  assert.deepEqual(JSON.parse(app.pendingRequests()[0].options.body), {
    filters: {eligibility: "all"}, ids: ["a", "c"], version: "version-1",
  });
  app.reply(true, reconciliationPreview(2, "explicit-preview"));
  await preview;
  assert.match(app.evaluate('$("reconciliation-batch-summary").textContent'), /确认 2 项/);
  assertConfirmationReasonDefault(app, '$("reconciliation-batch-reason")');
  app.evaluate('$("reconciliation-batch-reason").value = "旧批次草稿"; $("reconciliation-batch-cancel").emit("click")');
  const repreview = app.evaluate("previewReconciliationBatch(state.reconciliationView)");
  app.reply(true, reconciliationPreview(2, "current-preview"));
  await repreview;
  assertConfirmationReasonDefault(app, '$("reconciliation-batch-reason")');
});

test("reconciliation preview reports candidate adoption and exact cost effects for each selection mix", async () => {
  const app = page();
  const cases = ["a", "b", "c"].map((id) => ({id, generation: 1, batch_eligible: true}));
  await openReconciliationPage(app, reconciliationPage(cases));
  app.evaluate('$("reconciliation-select-all").emit("click")');
  const selections = [
    [{}, "将确认 3 项，均沿用已入账的历史用量和参考成本。"],
    [{
      candidate_count: 2,
      current_cost_usd: "9007199254740993.000000000000000017",
      candidate_cost_usd: "9007199254740993.000000000000000019",
    }, "将确认 3 项。2 项采用 Codex 原生候选的发生时间、用量和参考成本，参考成本合计由 9007199254740993.000000000000000017 USD 调整为 9007199254740993.000000000000000019 USD。1 项沿用已入账的历史用量和参考成本。"],
    [{
      candidate_count: 3, current_cost_usd: "12.500", candidate_cost_usd: "0",
    }, "将确认 3 项。3 项采用 Codex 原生候选的发生时间、用量和参考成本，参考成本合计由 12.5 USD 调整为 0 USD。"],
  ];
  for (const [extra, summary] of selections) {
    const operation = app.evaluate("previewReconciliationBatch(state.reconciliationView)");
    app.reply(true, reconciliationPreview(3, "preview-impact", extra));
    await operation;
    assert.equal(app.evaluate('$("reconciliation-batch-summary").textContent'), summary);
    assert.equal(app.evaluate('$("reconciliation-batch-submit").disabled'), false);
    app.evaluate('$("reconciliation-batch-cancel").emit("click")');
  }
  const unreadable = app.evaluate("previewReconciliationBatch(state.reconciliationView)");
  app.reply(true, reconciliationPreview(3, "preview-unreadable", {candidate_count: 1, candidate_cost_usd: null}));
  await unreadable;
  assert.equal(app.evaluate('$("reconciliation-batch-form").hidden'), true);
  assert.equal(app.evaluate('$("reconciliation-batch-submit").disabled'), true);
  assert.match(app.evaluate('$("reconciliation-error").textContent'), /重新预览/);
});

test("filtered all selects across pages and retries an uncertain batch with the same idempotency key", async () => {
  const app = page();
  const eligible = {id: "a", generation: 1, batch_eligible: true};
  await openReconciliationPage(app, reconciliationPage([eligible]));
  app.evaluate(`$("reconciliation-type").value = "identity"; $("reconciliation-type").emit("change");
    $("reconciliation-source").value = "windows"; $("reconciliation-source").emit("change");
    $("reconciliation-start").value = "2026-10-14"; $("reconciliation-start").emit("change");
    $("reconciliation-eligibility").value = "batch"; $("reconciliation-eligibility").emit("change");
    $("reconciliation-filter-form").emit("submit");`);
  replyReconciliationPage(app, reconciliationPage([eligible], {total: 5261, eligible_count: 5261, next_cursor: "next"}));
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(app.evaluate('$("reconciliation-source").value'), "windows");
  app.evaluate('$("reconciliation-select-all").emit("click")');
  assert.match(app.evaluate('$("reconciliation-selection").textContent'), /5,261.*含其他页/);
  const preview = app.evaluate("previewReconciliationBatch(state.reconciliationView)");
  const filters = {type: "identity", source_id: "windows", start_date: "2026-10-14", eligibility: "batch"};
  assert.deepEqual(JSON.parse(app.pendingRequests()[0].options.body), {filters, version: "version-1"});
  app.reply(true, reconciliationPreview(5261, "filtered-preview"));
  await preview;
  app.evaluate('$("reconciliation-batch-reason").value = ""; $("reconciliation-batch-form").emit("submit")');
  assert.deepEqual(app.pendingUrls(), []);
  assert.match(app.evaluate('$("reconciliation-error").textContent'), /请填写核对说明/);
  assert.equal(app.evaluate('$("reconciliation-batch-reason").placeholder'), "已人工确认");
  app.evaluate('$("reconciliation-batch-reason").value = "证据匹配"; $("reconciliation-batch-form").emit("submit")');
  const first = JSON.parse(app.pendingRequests()[0].options.body);
  assert.deepEqual(first.filters, filters);
  assert.equal(first.ids, undefined);
  assert.equal(first.preview_hash, "filtered-preview");
  assert.equal(first.reason, "证据匹配");
  assert.equal(app.evaluate("state.analysis"), null);
  app.disconnectTo("/api/reconciliations/batch");
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(app.evaluate('$("reconciliation-batch-form").hidden'), false);
  assert.equal(app.evaluate('$("reconciliation-batch-reason").value'), "证据匹配");
  assert.match(app.evaluate('$("reconciliation-error").textContent'), /相同说明重试/);
  app.evaluate('$("reconciliation-batch-form").emit("submit")');
  assert.deepEqual(JSON.parse(app.pendingRequests()[0].options.body), first);
  app.replyTo("/api/reconciliations/batch", true, {resolved_count: 5261, open_count: 825, classification_revision: 0});
  await new Promise((resolve) => setImmediate(resolve));
  replyReconciliationPage(app, reconciliationPage([], {version: "version-2"}));
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(app.evaluate('$("reconciliation-count").textContent'), "825");
  app.replyTo("/api/reconciliations/summary", true, {total: 820});
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(app.evaluate('$("reconciliation-count").textContent'), "820");
  assert.match(app.evaluate('$("reconciliation-saved").textContent'), /已批量确认 5,261 项/);
  assert.equal(app.evaluate('$("reconciliation-batch-form").hidden'), true);
  assert.equal(app.evaluate('$("reconciliation-search").disabled'), false);
  assert.deepEqual(app.pendingUrls(), ["/api/ledger"]);
});

test("obsolete reconciliation page and preview responses cannot affect new filters or invalidate a newer preview", async () => {
  for (const lateError of [false, true]) {
    const app = page();
    const eligible = {id: "a", generation: 1, batch_eligible: true};
    const old = app.evaluate("openReconciliations()");
    const obsoletePath = app.pendingUrls()[0];
    app.evaluate('$("reconciliation-type").value = "identity"; $("reconciliation-type").emit("change"); $("reconciliation-filter-form").emit("submit")');
    const latestPath = app.pendingUrls()[1];
    app.replyTo(latestPath, true, reconciliationPage([eligible], {version: "fresh"}));
    app.replyTo(obsoletePath, !lateError, lateError ? {code: "data_changed", message: "过时页面"} : reconciliationPage());
    await old;
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(app.evaluate("state.reconciliationView.page.version"), "fresh");
    app.evaluate('$("reconciliation-select-all").emit("click")');
    const preview = app.evaluate("previewReconciliationBatch(state.reconciliationView)");
    app.evaluate('$("reconciliation-eligibility").value = "manual"; $("reconciliation-eligibility").emit("change")');
    app.replyTo("/api/reconciliations/batch-preview", !lateError,
      lateError ? {code: "data_changed", message: "过时预览"} : reconciliationPreview(1, "obsolete"));
    await preview;
    assert.equal(app.evaluate('$("reconciliation-batch-form").hidden'), true);
    assert.equal(app.evaluate('$("reconciliation-error").hidden'), true);
    assert.equal(app.evaluate("state.analysis.analysis_id"), "old");
  }
});

test("stale reconciliation cursor reloads the filter without carrying the previous selection", async () => {
  const app = page();
  const eligible = {id: "a", generation: 1, batch_eligible: true};
  await openReconciliationPage(app, reconciliationPage([eligible], {total: 63, eligible_count: 63, next_cursor: "next"}));
  app.evaluate('$("reconciliation-select-all").emit("click"); $("reconciliation-next").emit("click");');
  app.reply(false, {code: "invalid_cursor", message: "资料已更新"});
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(app.pendingUrls()[0].includes("cursor"), false);
  replyReconciliationPage(app, reconciliationPage([eligible], {version: "version-2"}));
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(app.evaluate("state.reconciliationView.allFiltered"), false);
  assert.equal(app.evaluate('$("reconciliation-preview").disabled'), true);
  assert.match(app.evaluate('$("reconciliation-error").textContent'), /重新选择/);
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

test("directory and historical reconciliation display their real choices and native evidence", () => {
  const app = page();
  app.evaluate(`for (const entry of [
    {id: "directory", type: "directory", current_cwd: "C:/old-project", candidate_cwd: "D:/new-project", choices: ["current", "candidate"]},
    {id: "source", type: "source", observed: {detail: 4}, previous: {detail: 10}, choices: ["current"]},
    {id: "native-overlap", type: "native_overlap", choices: ["current", "independent"]},
    {id: "native-uncertain", type: "native_uncertain", pending_reason: "cumulative_baseline_unconfirmed",
      candidate_summary: {input_tokens: 3, output_tokens: 2, cache_read_tokens: 5, cache_creation_tokens: 0}, choices: ["current"]}
  ]) {
    const detail = node("div");
    renderReconciliationDetail(null, detail, entry);
    $("reconciliation-list").append(detail);
  }`);
  const text = app.evaluate(`JSON.stringify((function collect(element) {
    return [element.textContent || "", ...element.children.flatMap(collect)];
  })($("reconciliation-list")))`);
  assert.match(text, /C:\/old-project/);
  assert.match(text, /D:\/new-project/);
  assert.match(text, /采用当前电脑目录/);
  assert.match(text, /保留已保存目录/);
  assert.match(text, /此前来源 10 条明细/);
  assert.match(text, /本次来源 4 条明细/);
  assert.match(text, /确认此来源，保留本地历史/);
  assert.match(text, /沿用已入账历史/);
  assert.match(text, /确认为新用量/);
  assert.match(text, /累计用量的起点待确认/);
  assert.match(text, /输入 3 · 输出 2/);
  assert.match(text, /缓存读取 5 · 缓存写入 0/);
  assert.match(text, /确认排除候选/);
});

function directoryPreview(overrides = {}) {
  return {
    preview_id: "directory-preview-1",
    project: {id: "saved-project", name: "合成新项目", description: "", directories: ["/work/a"], directory_managed: true},
    summary: {detail_count: 80, session_count: 2, total_cost_usd: "0.000000000000000000000000123", changed_count: 79, already_assigned_count: 1, claimed_count: 2, pending_count: 1, recovered_sessions: 0},
    directories: [{path: "/work/a", detail_count: 80, session_count: 2, total_cost_usd: "0.000000000000000000000000123"}],
    changes: [{from_project_id: "old-project", from_project_name: "旧项目", to_project_id: "saved-project", to_project_name: "合成新项目", detail_count: 79, total_cost_usd: "0.000000000000000000000000123"}],
    transfers: [{path: "/work/a", from_project_id: "old-project", from_project_name: "旧项目"}], warnings: [],
    ...overrides,
  };
}
function prepareDirectoryEditor(app) {
  app.evaluate(`openProject(); $("edit-project-name").value = "合成新项目";
    $("edit-project-directories").value = "/work/a";`);
}
function stubProjectRefreshes(app) {
  app.evaluate(`refreshProjects = async () => {}; refreshLedger = async () => {};
    refreshAssociations = async () => {}; state.activePage = "projects";`);
}

test("directory save previews all impact without writing a project or asking for record selection", async () => {
  const app = page(); prepareDirectoryEditor(app);
  const preview = app.evaluate("saveProject()");
  assert.deepEqual(app.pendingUrls(), ["/api/projects/preview"]);
  assert.deepEqual(JSON.parse(app.pendingRequests()[0].options.body), {name: "合成新项目", description: "", directories: ["/work/a"]});
  assert.equal(app.evaluate('$("edit-project-id").value'), "");
  app.replyTo("/api/projects/preview", true, directoryPreview());
  await preview;
  assert.equal(app.evaluate('$("project-editor").hidden'), true);
  assert.equal(app.evaluate('$("project-binding-impact").hidden'), false);
  assert.equal(app.evaluate('$("apply-project-binding").disabled'), false);
  // In the minimal DOM separate static containers are not parented to the section.
  assert.match(app.evaluate('$("project-binding-summary").children[1].textContent'), /0\.000000000000000000000000123 USD/);
  assert.match(app.evaluate('$("project-binding-transfers").children[0].textContent'), /旧项目.*整体转入.*合成新项目/);
  assert.equal(app.evaluate('$("edit-project-id").value'), "");
  assert.equal(app.pendingUrls().includes("/api/projects/apply"), false);
  app.evaluate('$("project-dialog").close();');
  assert.equal(app.evaluate("state.projectEditor"), null);
  assert.equal(app.pendingUrls().length, 0);
});

test("directory creation retains its saved identity and refresh failures retry only reads", async () => {
  for (const failedRefresh of ["projects", "ledger", "associations"]) {
    const app = page(); prepareDirectoryEditor(app); stubProjectRefreshes(app);
    const preview = app.evaluate("saveProject()");
    app.replyTo("/api/projects/preview", true, directoryPreview()); await preview;
    app.evaluate(`state.pendingBatch = {signature: "old"};
      state.associationPreview = {result: {preview_id: "old"}, request: {}};
      ${failedRefresh === "projects" ? 'refreshProjects' : failedRefresh === "ledger" ? 'refreshLedger' : 'refreshAssociations'} = async () => { throw new Error("刷新断线"); };`);
    const saved = app.evaluate("applyProjectBinding()");
    app.replyTo("/api/projects/apply", true, {applied: true, project: directoryPreview().project});
    await assert.rejects(saved, /项目与目录关联已保存，但刷新未完成/);
    assert.equal(app.evaluate('$("edit-project-id").value'), "saved-project");
    assert.equal(app.evaluate("state.projectEditor.applied"), true);
    assert.equal(app.evaluate("state.analysis"), null);
    assert.equal(app.evaluate("state.pendingBatch"), null);
    assert.equal(app.evaluate("state.associationPreview"), null);
    assert.equal(app.evaluate('$("apply-project-binding").textContent'), "刷新已保存结果");
    assert.equal(app.evaluate('$("back-project-editor").disabled'), true);
    stubProjectRefreshes(app);
    await app.evaluate("applyProjectBinding()");
    assert.equal(app.pendingUrls().length, 0);
    assert.equal(app.evaluate('$("project-dialog").open'), false);
  }
});

test("directory preview ignores stale success, 409 and disconnect after closing or replacement", async () => {
  for (const outcome of ["success", "expired", "disconnect"]) {
    const app = page(); prepareDirectoryEditor(app);
    const preview = app.evaluate("saveProject()");
    app.evaluate(`$("project-dialog").close(); openProject();
      $("edit-project-name").value = "较新项目";
      state.analysis = {analysis_id: "newer"}; state.pendingBatch = {signature: "newer"};`);
    if (outcome === "disconnect") app.disconnectTo("/api/projects/preview");
    else app.replyTo("/api/projects/preview", outcome === "success", outcome === "success" ? directoryPreview()
      : {code: "classification_changed", message: "旧预览已过期"});
    await preview;
    assert.equal(app.evaluate("state.projectEditor.preview"), null);
    assert.equal(app.evaluate('$("edit-project-name").value'), "较新项目");
    assert.equal(app.evaluate("state.analysis.analysis_id"), "newer");
    assert.equal(app.evaluate("state.pendingBatch.signature"), "newer");
  }
});

test("editing a directory draft or a known ledger mutation expires its impact", async () => {
  for (const mutation of ['$("edit-project-name").emit("input")', 'invalidateAssociations("同步已更新")']) {
    const app = page(); prepareDirectoryEditor(app);
    const preview = app.evaluate("saveProject()");
    app.evaluate(mutation);
    app.replyTo("/api/projects/preview", true, directoryPreview()); await preview;
    assert.equal(app.evaluate("state.projectEditor.preview"), null);
    assert.equal(app.evaluate('$("project-editor").hidden'), false);
    assert.equal(app.evaluate('$("apply-project-binding").disabled'), true);
  }
});

test("directory apply retries a lost response with the identical persistent key", async () => {
  const app = page(); prepareDirectoryEditor(app); stubProjectRefreshes(app);
  const preview = app.evaluate("saveProject()");
  app.replyTo("/api/projects/preview", true, directoryPreview()); await preview;
  const first = app.evaluate("applyProjectBinding()");
  const body = JSON.parse(app.pendingRequests()[0].options.body);
  assert.equal(body.preview_id, "directory-preview-1");
  assert.equal(Object.hasOwn(body, "reason"), false);
  app.disconnectTo("/api/projects/apply"); await assert.rejects(first, /连接中断/);
  assert.equal(app.evaluate('$("back-project-editor").disabled'), true);
  assert.equal(app.evaluate('$("apply-project-binding").textContent'), "重试确认保存结果");
  app.evaluate('invalidateAssociations("同步已更新");');
  assert.equal(app.evaluate('state.projectEditor.preview.preview_id'), "directory-preview-1");
  const retried = app.evaluate("applyProjectBinding()");
  assert.deepEqual(JSON.parse(app.pendingRequests()[0].options.body), body);
  app.replyTo("/api/projects/apply", true, {applied: true, project: directoryPreview().project}); await retried;
  assert.equal(app.evaluate('$("project-dialog").open'), false);
});

test("directory confirmation rejects changed drafts and stale authority without partial saving", async () => {
  for (const expired of [false, true]) {
    const app = page(); prepareDirectoryEditor(app);
    const preview = app.evaluate("saveProject()");
    app.replyTo("/api/projects/preview", true, directoryPreview()); await preview;
    if (!expired) {
      app.evaluate('$("edit-project-directories").value = "/different";');
      await assert.rejects(app.evaluate("applyProjectBinding()"), /项目设置已更改/);
    } else {
      const apply = app.evaluate("applyProjectBinding()");
      app.replyTo("/api/projects/apply", false, {code: "project_binding_preview_expired", message: "依据已变化"});
      await assert.rejects(apply, /依据已变化/);
    }
    assert.equal(app.evaluate("state.projectEditor.preview"), null);
    assert.equal(app.evaluate('$("edit-project-id").value'), "");
    assert.equal(app.evaluate('$("project-editor").hidden'), false);
    assert.equal(app.pendingUrls().length, 0);
  }
});

test("an older directory apply cannot alter a new editor or invalidate its newer analysis", async () => {
  const app = page(); prepareDirectoryEditor(app);
  const preview = app.evaluate("saveProject()");
  app.replyTo("/api/projects/preview", true, directoryPreview()); await preview;
  const apply = app.evaluate("applyProjectBinding()");
  app.evaluate(`$("project-dialog").close(); openProject();
    $("edit-project-name").value = "另一个项目"; state.analysis = {analysis_id: "newer"}; state.pendingBatch = {signature: "newer"};`);
  app.replyTo("/api/projects/apply", true, {applied: true, project: directoryPreview().project}); await apply;
  assert.equal(app.evaluate('$("edit-project-id").value'), "");
  assert.equal(app.evaluate('$("edit-project-name").value'), "另一个项目");
  assert.equal(app.evaluate("state.analysis.analysis_id"), "newer");
  assert.equal(app.evaluate("state.pendingBatch.signature"), "newer");
  assert.equal(app.pendingUrls().length, 0);
});

test("sync during a submitted directory change does not lose its committed identity", async () => {
  const app = page(); prepareDirectoryEditor(app); stubProjectRefreshes(app);
  const preview = app.evaluate("saveProject()");
  app.replyTo("/api/projects/preview", true, directoryPreview()); await preview;
  const apply = app.evaluate("applyProjectBinding()");
  app.evaluate('invalidateAssociations("同步已完成");');
  assert.equal(app.evaluate("state.projectEditor.stale"), true);
  app.replyTo("/api/projects/apply", true, {applied: true, project: directoryPreview().project}); await apply;
  assert.equal(app.evaluate('$("edit-project-id").value'), "saved-project");
  assert.equal(app.pendingUrls().length, 0);
});

test("post-save association refreshes belong to the directory editor that requested them", async () => {
  for (const outcome of ["success", "expired", "disconnect"]) {
    const app = page(); prepareDirectoryEditor(app);
    app.evaluate(`refreshProjects = async () => {}; refreshLedger = async () => {};
      state.activePage = "projects";`);
    const preview = app.evaluate("saveProject()");
    app.replyTo("/api/projects/preview", true, directoryPreview()); await preview;
    const apply = app.evaluate("applyProjectBinding()");
    app.replyTo("/api/projects/apply", true, {applied: true, project: directoryPreview().project});
    await new Promise((resolve) => setImmediate(resolve));
    const recordsUrl = app.pendingUrls().find((url) => url.startsWith("/api/project-associations/records?"));
    assert.ok(recordsUrl);
    app.evaluate(`$("project-dialog").close(); openProject();
      $("edit-project-name").value = "较新项目";
      state.analysis = {analysis_id: "newer"}; state.pendingBatch = {signature: "newer"};
      state.associations = {newer: true}; state.associationRows = [{record_key: "newer"}];`);
    if (outcome === "disconnect") app.disconnectTo("/api/project-associations");
    else app.replyTo("/api/project-associations", outcome === "success", outcome === "success"
      ? {summary: {}, projects: [], groups: []} : {code: "classification_changed", message: "旧归属请求过期"});
    app.replyTo(recordsUrl, true, {rows: []});
    await apply;
    assert.equal(app.evaluate("state.associations.newer"), true);
    assert.equal(app.evaluate("state.associationRows[0].record_key"), "newer");
    assert.equal(app.evaluate("state.analysis.analysis_id"), "newer");
    assert.equal(app.evaluate("state.pendingBatch.signature"), "newer");
    assert.equal(app.evaluate('$("edit-project-name").value'), "较新项目");
  }
});

test("an inactive directory editor cannot start another association refresh", async () => {
  const app = page();
  app.evaluate('state.associationSelected.set("newer", {record_key: "newer"});');
  await app.evaluate("refreshAssociations(() => false)");
  assert.equal(app.pendingUrls().length, 0);
  assert.equal(app.evaluate('state.associationSelected.has("newer")'), true);
});

test("empty directory history still offers a usable binding confirmation", async () => {
  const app = page(); prepareDirectoryEditor(app);
  const preview = app.evaluate("saveProject()");
  app.replyTo("/api/projects/preview", true, directoryPreview({summary: {detail_count: 0, session_count: 0, total_cost_usd: "0", changed_count: 0, already_assigned_count: 0}, changes: [], transfers: []}));
  await preview;
  assert.equal(app.evaluate('$("apply-project-binding").disabled'), false);
  assert.match(app.evaluate('$("project-binding-summary").children.at(-1).textContent'), /新用量会自动归入/);
});

test("directory candidates include saved old-machine paths and identify whole-folder transfers", () => {
  const app = page();
  app.evaluate(`state.config.projects = [
    {id: "old", name: "旧项目", directories: ["/old/repo"]},
    {id: "current", name: "当前项目", directories: ["/new/repo"]}
  ]; state.ledger.directories = [{path: "/new/repo", session_count: 2, detail_count: 80}];
  openProject(state.config.projects[1]);`);
  const draft = JSON.parse(app.evaluate('JSON.stringify(projectDraft())'));
  assert.deepEqual(draft.directories, ["/new/repo"]);
  assert.match(app.evaluate('$("project-candidates").children[1].children[1].children[1].textContent'), /旧项目.*整体转入/);
  assert.equal(app.evaluate('$("project-candidates").children.length'), 2);
});

test("usage records are read-only by default and advanced selection excludes known directories", () => {
  const app = page();
  app.evaluate(`state.tab = "details"; state.rows = [
    {record_key: "known", cwd: "/work/a", assignment_origin: "directory_rule"},
    {record_key: "managed", cwd: null, assignment_origin: "directory_binding"},
    {record_key: "unknown", cwd: null, assignment_origin: "unassigned"}
  ]; renderRowTable();`);
  assert.equal(app.evaluate('document.querySelectorAll("[data-usage-select]").length'), 0);
  app.evaluate('$("usage-legacy-tools").open = true; $("usage-legacy-tools").emit("toggle");');
  assert.equal(app.evaluate('document.querySelectorAll("[data-usage-select]").length'), 4);
  assert.equal(app.evaluate('document.querySelectorAll("[data-usage-select]")[1].disabled'), true);
  assert.equal(app.evaluate('document.querySelectorAll("[data-usage-select]")[2].disabled'), true);
  app.evaluate('const all = document.querySelectorAll("[data-usage-select]")[0]; all.checked = true; all.emit("change");');
  assert.deepEqual(JSON.parse(app.evaluate('JSON.stringify([...state.selected.keys()])')), ["unknown"]);
  app.evaluate('$("usage-legacy-tools").open = false; $("usage-legacy-tools").emit("toggle");');
  assert.equal(app.evaluate('state.selected.size'), 0);
  assert.equal(app.evaluate('$("assignment-bar").hidden'), true);
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

test("each project association preview prefills a fresh explanation and preserves an edited draft", async () => {
  const app = page();
  app.evaluate('state.associationAllFiltered = true; $("association-target-project").value = "project-1";');
  for (const action of ["assign", "reclassify", "recover"]) {
    const preview = app.evaluate(`previewAssociations(${JSON.stringify(action)})`);
    assertConfirmationReasonDefault(app, '$("association-reason")');
    app.evaluate('$("association-reason").value = "当前归属依据"');
    app.replyTo("/api/project-associations/preview", true, {preview_id: action, summary: {}});
    await preview;
    assert.equal(app.evaluate('$("association-reason").value'), "当前归属依据");
    app.evaluate('$("association-dialog").close()');
  }
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
  assert.equal(app.evaluate('$("association-reason").value'), "核实项目归属");
  app.evaluate("refreshAssociationOverview = async () => {};");
  await app.evaluate("applyAssociations()");
  assert.equal(app.pendingUrls().includes("/api/project-associations/apply"), false);
  assert.equal(app.evaluate("state.associationPreview"), null);
});

test("withdraw and void require an editable explanation and retry the same submitted draft", async () => {
  const app = page();
  app.evaluate(`const batch = {id: "batch-1", generation: 3, number: "001", project_name: "甲"};
    refreshBatches = async () => {}; analyze = async () => {}; openLifecycle("withdraw", batch);`);
  assertConfirmationReasonDefault(app, '$("lifecycle-reason")');
  app.evaluate('$("lifecycle-reason").value = ""');
  await assert.rejects(app.evaluate("saveLifecycle()"), /请填写操作原因/);
  assert.deepEqual(app.pendingUrls(), []);
  app.evaluate('$("lifecycle-reason").value = "撤回更正时间"');
  const pending = app.evaluate("saveLifecycle()");
  const original = JSON.parse(app.pendingRequests()[0].options.body);
  assert.equal(original.reason, "撤回更正时间");
  app.disconnectTo("/api/batches/batch-1/withdraw");
  await assert.rejects(pending, /连接中断/);
  assert.equal(app.evaluate('$("lifecycle-reason").value'), "撤回更正时间");
  const retry = app.evaluate("saveLifecycle()");
  assert.deepEqual(JSON.parse(app.pendingRequests()[0].options.body), original);
  app.replyTo("/api/batches/batch-1/withdraw", true, {});
  await retry;
  app.evaluate('openLifecycle("void", batch)');
  assertConfirmationReasonDefault(app, '$("lifecycle-reason")');
  const submitted = app.evaluate("saveLifecycle()");
  assert.equal(JSON.parse(app.pendingRequests()[0].options.body).reason, "已人工确认");
  app.replyTo("/api/batches/batch-1/void", true, {});
  await submitted;
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

test("unassigned details show their exact cost without blocking known project saving", () => {
  const app = page();
  app.evaluate(`state.analysis = {analysis_id: "known-project", availability_mode: "available", summary: {record_count: 1}};
    renderAssignmentCoverage({assignment_coverage: {status: "incomplete", unassigned_detail_count: 2,
      unassigned_record_count: 2, unassigned_cost_usd: "0.000000000000000000000000123"}});
    syncActions();`);
  assert.equal(app.evaluate('$("assignment-coverage-note").hidden'), false);
  const text = app.evaluate('$("assignment-coverage-description").textContent');
  assert.match(text, /2 条明细待归属/);
  assert.match(text, /0\.000000000000000000000000123 USD/);
  assert.equal(app.evaluate('$("open-claim").disabled'), false);
  app.evaluate("openClaimDialog()");
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


test("advanced page selection never includes directory-managed records", () => {
  const app = page();
  app.evaluate(`state.associationRows = [
    {record_key: "managed", kind: "detail", assignment_origin: "directory_binding"},
    {record_key: "unknown", kind: "detail", assignment_origin: "unassigned"}
  ]; renderAssociationRecords();
  const all = document.querySelectorAll("[data-association-select]")[0]; all.checked = true; all.emit("change");`);
  assert.deepEqual(JSON.parse(app.evaluate('JSON.stringify([...state.associationSelected.keys()])')), ["unknown"]);
  assert.equal(app.evaluate('document.querySelectorAll("[data-association-select]")[1].disabled'), true);
  app.evaluate(`state.config.projects = [{id: "managed-project", directory_managed: true}];
    $("association-filter-project").value = "all"; syncAssociationActions();`);
  assert.equal(app.evaluate('$("association-all-filtered").disabled'), true);
});
