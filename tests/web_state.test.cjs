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
  }
  const elements = new Map();
  const body = new Element();
  const pending = [];
  const context = vm.createContext({
    document: {
      body, activeElement: body,
      getElementById(id) {
        if (!elements.has(id)) elements.set(id, new Element());
        return elements.get(id);
      },
      createElement() { return new Element(); },
      querySelectorAll() { return []; },
    },
    Node: Element, URLSearchParams, Intl, clearTimeout, setTimeout,
    AhaForms: {mount() {}, sync() {}, closeAll() {}},
    fetch(url) {
      if (url === "/api/status") return new Promise(() => {});
      return new Promise((resolve, reject) => pending.push({resolve, reject}));
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
    reply(ok, result) { pending.shift().resolve({ok, json: async () => result}); },
    disconnect() { pending.shift().reject(new Error("disconnected")); },
  };
}

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
