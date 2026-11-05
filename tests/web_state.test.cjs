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
      this.classList = {toggle() {}, add() {}, remove() {}};
    }
    addEventListener() {}
    setAttribute() {}
    removeAttribute() {}
    querySelectorAll() { return []; }
    append(...items) { this.children.push(...items); }
    replaceChildren(...items) { this.children = items; }
    close() {}
    getClientRects() { return []; }
  }
  const elements = new Map();
  const body = new Element();
  const pending = [];
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
        return selector === "[data-sync-control]" ? [this.getElementById("sync-control")] : [];
      },
    },
    Node: Element, URLSearchParams, Intl, clearTimeout, setTimeout,
    crypto: {randomUUID: () => "test-sync-key"},
    AhaForms: {mount() {}, sync() {}, closeAll() {}},
    fetch(url) {
      if (url === "/api/status") return new Promise((resolve) => { statusReply = resolve; });
      return new Promise((resolve, reject) => pending.push({url, resolve, reject}));
    },
  });
  context.window = context;
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../src/aha/web/time-range-picker.js"), "utf8"), context);
  context.AhaTimeRange.create = () => ({setDisabled() {}, markPending() {}});
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
    disconnect() { pending.shift().reject(new Error("disconnected")); },
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
