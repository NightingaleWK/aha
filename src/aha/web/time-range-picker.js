"use strict";

window.AhaTimeRange = (() => {
  const presets = {today: "当天", last_24h: "近 24 小时", last_7d: "近 7 天", last_14d: "近 14 天", last_30d: "近 30 天", month: "本月", all: "全部"};
  const offset = 8 * 60 * 60 * 1000;
  const clone = (value) => value ? JSON.parse(JSON.stringify(value)) : null;
  const local = (epoch) => new Date(epoch + offset).toISOString().slice(0, 19);
  const iso = (epoch) => `${local(epoch)}+08:00`;
  const inclusiveEnd = (range) => local(Date.parse(range.end_before) - 1000);
  const minuteValid = (value) => {
    if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value) || value.startsWith("0000-")) return false;
    const epoch = Date.parse(`${value}:00+08:00`);
    return Number.isFinite(epoch) && local(epoch).slice(0, 16) === value;
  };
  const supportedPreview = (range) => range && minuteValid(range.start_at.slice(0, 16))
    && minuteValid(range.end_before.slice(0, 16));
  function element(tag, className, text) {
    const item = document.createElement(tag);
    if (className) item.className = className;
    if (text !== undefined) item.textContent = text;
    return item;
  }
  function button(text, className = "button") {
    const item = element("button", className, text); item.type = "button"; return item;
  }
  function name(intent) {
    return intent?.kind === "preset" ? presets[intent.preset] || "时间范围" : intent?.kind === "legacy_dates" ? "原记录日期" : "自定义";
  }
  function describe(range) {
    if (!range?.start_at || !range?.end_before) return "";
    const start = local(Date.parse(range.start_at));
    const end = inclusiveEnd(range);
    const width = range.precision === "day" ? 10 : range.precision === "minute" ? 16 : 19;
    return `${start.slice(0, width).replace("T", " ")} 至 ${end.slice(0, width).replace("T", " ")}`;
  }
  function fromAnalysis(result) {
    if (result?.time_range) return result.time_range;
    if (!result?.start_date || !result?.end_date) return null;
    return {start_at: `${result.start_date}T00:00:00+08:00`, end_before: iso(Date.parse(`${result.end_date}T00:00:00+08:00`) + 86400000),
      precision: "day", intent: {kind: "legacy_dates", start_date: result.start_date, end_date: result.end_date}};
  }
  function editableIntent(result) {
    const range = fromAnalysis(result);
    if (!range) return {kind: "preset", preset: "today", follow_now: true};
    if (["preset", "custom"].includes(range.intent?.kind)) return clone(range.intent);
    return {kind: "custom", start: range.start_at.slice(0, 16), end: inclusiveEnd(range).slice(0, 16), follow_now: false};
  }
  function wholeDays(result) {
    const range = fromAnalysis(result);
    if (!range) return null;
    return {kind: "custom", start: `${range.start_at.slice(0, 10)}T00:00`, end: `${inclusiveEnd(range).slice(0, 10)}T23:59`, follow_now: false};
  }

  class Picker {
    constructor(root, {id, label = "时间范围", context, onApply}) {
      this.root = root; this.id = id; this.label = label; this.context = context; this.onApply = onApply;
      this.intent = {kind: "preset", preset: "today", follow_now: true};
      this.resolved = null; this.lastResolved = null; this.pending = true; this.disabled = false;
      this.abort = new AbortController();
      this.trigger = button("", "time-range-trigger");
      this.trigger.id = `${id}-trigger`;
      this.trigger.setAttribute("aria-haspopup", "dialog");
      this.trigger.setAttribute("aria-expanded", "false");
      this.trigger.setAttribute("aria-controls", `${id}-panel`);
      this.title = element("span", "time-range-title");
      this.subtitle = element("span", "time-range-subtitle");
      this.subtitle.id = `${id}-description`;
      this.trigger.setAttribute("aria-describedby", this.subtitle.id);
      const text = element("span", "time-range-text"); text.append(this.title);
      const calendarIcon = element("span", "range-icon", "▦"); calendarIcon.setAttribute("aria-hidden", "true");
      const arrow = element("span", "control-chevron", "⌄"); arrow.setAttribute("aria-hidden", "true");
      this.trigger.append(calendarIcon, text, arrow);
      this.panel = element("div", "time-range-panel");
      this.panel.id = `${id}-panel`; this.panel.hidden = true;
      this.panel.setAttribute("popover", "manual");
      this.panel.setAttribute("role", "dialog");
      this.panel.setAttribute("aria-labelledby", `${id}-title`);
      const heading = element("div", "time-range-heading");
      const title = element("h3", "", "选择时间范围"); title.id = `${id}-title`;
      heading.append(title, element("span", "tag", "北京时间"));
      this.shortcutBar = element("div", "time-presets"); this.shortcutBar.setAttribute("aria-label", "快捷范围");
      this.presetButtons = new Map();
      for (const [value, text] of Object.entries(presets)) {
        const item = button(text, "chip"); item.dataset.preset = value;
        item.addEventListener("click", () => this.choosePreset(value), {signal: this.abort.signal});
        this.shortcutBar.append(item); this.presetButtons.set(value, item);
      }
      const body = element("div", "time-range-body");
      this.endpoints = element("div", "time-endpoints");
      this.inputs = {};
      for (const [key, text] of [["start", "开始时间"], ["end", "结束时间"]]) {
        const group = element("div", "time-endpoint");
        const label = element("label", "time-endpoint-label", text); label.htmlFor = `${id}-${key}-date`;
        const fields = element("div", "time-endpoint-inputs");
        const date = element("input"); date.type = "date"; date.id = `${id}-${key}-date`;
        date.min = "0001-01-01"; date.max = "9999-12-31";
        const time = element("input"); time.type = "time"; time.step = "60"; time.id = `${id}-${key}-time`;
        time.setAttribute("aria-label", `${text}（小时和分钟）`);
        const hint = element("p", "field-help"); hint.id = `${id}-${key}-hint`;
        hint.textContent = key === "start" ? "按北京时间选择" : "手动设置时，包含结束分钟";
        date.setAttribute("aria-describedby", hint.id); time.setAttribute("aria-describedby", hint.id);
        for (const input of [date, time]) {
          input.addEventListener("focus", () => { this.activeEndpoint = key; this.jumpToEndpoint(); }, {signal: this.abort.signal});
          input.addEventListener("input", () => this.editEndpoint(key), {signal: this.abort.signal});
          input.addEventListener("change", () => this.editEndpoint(key), {signal: this.abort.signal});
        }
        fields.append(date, time); group.append(label, fields, hint); this.endpoints.append(group);
        this.inputs[key] = {date, time, hint, group};
      }
      this.calendar = element("div", "range-calendar");
      const calendarTop = element("div", "calendar-top");
      this.previousMonth = button("‹", "icon-button"); this.previousMonth.setAttribute("aria-label", "上个月");
      this.nextMonth = button("›", "icon-button"); this.nextMonth.setAttribute("aria-label", "下个月");
      this.monthLabel = element("strong", "calendar-month"); this.monthLabel.id = `${id}-month`;
      this.monthLabel.setAttribute("aria-live", "polite");
      this.previousMonth.addEventListener("click", () => this.moveMonth(-1), {signal: this.abort.signal});
      this.nextMonth.addEventListener("click", () => this.moveMonth(1), {signal: this.abort.signal});
      calendarTop.append(this.previousMonth, this.monthLabel, this.nextMonth);
      this.calendarTabs = element("div", "calendar-endpoint-tabs");
      this.endpointButtons = {};
      for (const [key, text] of [["start", "选择开始日期"], ["end", "选择结束日期"]]) {
        const item = button(text, "calendar-endpoint-tab");
        item.addEventListener("click", () => { this.activeEndpoint = key; this.jumpToEndpoint(); }, {signal: this.abort.signal});
        this.endpointButtons[key] = item; this.calendarTabs.append(item);
      }
      const weekdays = element("div", "calendar-weekdays"); weekdays.setAttribute("aria-hidden", "true");
      for (const day of ["一", "二", "三", "四", "五", "六", "日"]) weekdays.append(element("span", "", day));
      this.grid = element("div", "calendar-grid"); this.grid.setAttribute("role", "grid");
      this.grid.setAttribute("aria-labelledby", this.monthLabel.id);
      this.grid.addEventListener("click", (event) => {
        const day = event.target.closest("[data-date]"); if (day && !day.disabled) this.pickDate(day.dataset.date);
      }, {signal: this.abort.signal});
      this.grid.addEventListener("keydown", (event) => this.calendarKey(event), {signal: this.abort.signal});
      this.calendar.append(this.calendarTabs, calendarTop, weekdays, this.grid);
      body.append(this.endpoints, this.calendar);
      this.explanation = element("p", "time-range-explanation"); this.explanation.setAttribute("aria-live", "polite");
      this.error = element("p", "time-range-error"); this.error.hidden = true; this.error.id = `${id}-error`; this.error.setAttribute("role", "alert");
      const footer = element("div", "time-range-footer");
      const followLabel = element("label", "checkbox-label time-follow");
      this.follow = element("input"); this.follow.type = "checkbox";
      this.follow.addEventListener("change", () => this.toggleFollow(), {signal: this.abort.signal});
      followLabel.append(this.follow, element("span", "", "结束时间跟随当前时刻"));
      const actions = element("div", "time-range-actions");
      this.cancel = button("取消"); this.confirm = button("确定并更新", "button primary");
      this.cancel.addEventListener("click", () => this.close(true), {signal: this.abort.signal});
      this.confirm.addEventListener("click", () => { void this.apply(); }, {signal: this.abort.signal});
      actions.append(this.cancel, this.confirm); footer.append(followLabel, actions);
      this.panel.append(heading, this.shortcutBar, body, this.explanation, this.error, footer);
      root.append(this.trigger, this.subtitle, this.panel);
      this.trigger.addEventListener("click", () => this.opened ? this.close(true) : this.open(), {signal: this.abort.signal});
      this.panel.addEventListener("keydown", (event) => {
        if (event.key === "Enter" && event.target.tagName === "INPUT") { event.preventDefault(); void this.apply(); }
        if (event.key === "Tab") this.trapTab(event);
      }, {signal: this.abort.signal});
      document.addEventListener("pointerdown", (event) => {
        if (this.opened && !this.applying && !event.composedPath().includes(this.root)) this.close();
      }, {capture: true, signal: this.abort.signal});
      document.addEventListener("keydown", (event) => {
        if (this.opened && event.key === "Escape") {
          event.preventDefault(); event.stopPropagation(); if (!this.applying) this.close(true);
        }
      }, {capture: true, signal: this.abort.signal});
      root.closest("dialog")?.addEventListener("close", () => this.close(), {signal: this.abort.signal});
      window.addEventListener("resize", () => this.position(), {signal: this.abort.signal});
      document.addEventListener("scroll", () => this.position(), {capture: true, signal: this.abort.signal});
      this.renderTrigger();
    }
    getIntent() { return clone(this.intent); }
    setIntent(intent, resolved = null) {
      this.intent = clone(intent); this.resolved = resolved; this.pending = !resolved;
      if (resolved) this.lastResolved = resolved;
      this.renderTrigger();
    }
    setResolved(resolved) {
      this.resolved = resolved; this.lastResolved = resolved; this.pending = false;
      this.renderTrigger();
    }
    markPending() { this.pending = true; this.renderTrigger(); }
    setDisabled(disabled) {
      this.disabled = disabled; this.trigger.disabled = disabled;
      if (disabled && this.opened && !this.applying) this.close();
    }
    renderTrigger() {
      const title = `${name(this.intent)}${this.intent.follow_now ? " · 跟随当前时刻" : ""}`;
      this.title.textContent = title;
      this.subtitle.textContent = !this.pending && this.resolved ? describe(this.resolved) : "选择日期与时间，确认后更新预览";
      this.trigger.setAttribute("aria-label", `${this.label}：${title}，${this.subtitle.textContent}`);
    }
    anchor() {
      const previous = this.lastResolved?.end_before;
      if (previous && Number.isFinite(Date.parse(previous))) return previous;
      const now = Date.parse(this.context().now);
      return Number.isFinite(now) ? iso(Math.floor(now / 1000) * 1000 + 1000) : null;
    }
    preview(intent, anchor = this.anchor()) {
      const coverage = this.context().coverage;
      if (intent.kind === "preset" && intent.preset === "all") {
        if (!coverage?.start_date || !coverage?.end_date) return null;
        return {start_at: `${coverage.start_date}T00:00:00+08:00`, end_before: iso(Date.parse(`${coverage.end_date}T00:00:00+08:00`) + 86400000), precision: "day"};
      }
      if (intent.kind === "custom") {
        if (!minuteValid(intent.start)) return null;
        const end = intent.follow_now ? anchor : minuteValid(intent.end) ? iso(Date.parse(`${intent.end}:00+08:00`) + 60000) : null;
        return end ? {start_at: `${intent.start}:00+08:00`, end_before: end, precision: intent.follow_now ? "second" : "minute"} : null;
      }
      const end = intent.follow_now ? anchor : intent.end_before;
      if (!end || !Number.isFinite(Date.parse(end))) return null;
      const endEpoch = Date.parse(end);
      const date = local(endEpoch - 1000).slice(0, 10);
      let start = Date.parse(`${date}T00:00:00+08:00`);
      if (intent.preset === "last_24h") start = endEpoch - 86400000;
      else if (intent.preset === "month") start = Date.parse(`${date.slice(0, 7)}-01T00:00:00+08:00`);
      else if (/^last_\d+d$/.test(intent.preset)) start -= (Number(intent.preset.match(/\d+/)[0]) - 1) * 86400000;
      return {start_at: iso(start), end_before: end, precision: "second"};
    }
    open() {
      if (this.disabled || this.applying) return;
      window.AhaForms?.closeAll();
      this.opened = true; this.panel.hidden = false;
      this.draft = this.getIntent(); this.activeEndpoint = "start"; this.fixedAnchor = this.anchor(); this.serverError = "";
      const preview = !this.pending && this.resolved ? this.resolved : this.preview(this.draft);
      this.fillInputs(preview);
      this.viewMonth = this.inputs.start.date.value.slice(0, 7) || this.context().now?.slice(0, 7);
      this.focusedDate = this.inputs.start.date.value;
      this.trigger.setAttribute("aria-expanded", "true");
      if (this.panel.showPopover) this.panel.showPopover();
      this.renderDraft(); this.position();
      const selected = this.presetButtons.get(this.draft.preset);
      (selected && !selected.disabled ? selected : this.inputs.start.date).focus();
    }
    close(returnFocus = false) {
      if (!this.opened || this.applying) return;
      this.opened = false;
      if (this.panel.hidePopover && this.panel.matches(":popover-open")) this.panel.hidePopover();
      this.panel.hidden = true; this.draft = null;
      this.trigger.setAttribute("aria-expanded", "false");
      if (returnFocus && !this.disabled) this.trigger.focus();
    }
    fillInputs(range) {
      const start = range?.start_at?.slice(0, 16) || "";
      const end = range ? inclusiveEnd(range).slice(0, 16) : "";
      for (const [key, value] of [["start", start], ["end", end]]) {
        this.inputs[key].date.value = value.slice(0, 10);
        this.inputs[key].time.value = value.slice(11, 16);
      }
    }
    choosePreset(preset) {
      if (this.applying || this.presetButtons.get(preset).disabled) return;
      this.draft = {kind: "preset", preset, follow_now: preset !== "all"};
      this.fixedAnchor = this.anchor(); this.serverError = "";
      this.fillInputs(this.preview(this.draft));
      this.activeEndpoint = "start"; this.jumpToEndpoint();
    }
    inputMinute(key) {
      return `${this.inputs[key].date.value}T${this.inputs[key].time.value}`;
    }
    editEndpoint(key) {
      if (this.applying) return;
      const follow = this.draft.follow_now && key !== "end";
      this.draft = {kind: "custom", start: this.inputMinute("start"), follow_now: Boolean(follow)};
      if (!follow) this.draft.end = this.inputMinute("end");
      this.activeEndpoint = key; this.serverError = "";
      if (this.inputs[key].date.value) this.viewMonth = this.inputs[key].date.value.slice(0, 7);
      this.renderDraft();
    }
    toggleFollow() {
      if (this.applying) return;
      this.serverError = "";
      this.draft.follow_now = this.follow.checked;
      if (this.draft.kind === "preset") {
        if (this.follow.checked) delete this.draft.end_before;
        else this.draft.end_before = this.fixedAnchor || this.anchor();
      } else {
        if (this.follow.checked) delete this.draft.end;
        else this.draft.end = this.inputMinute("end");
      }
      if (this.follow.checked) this.activeEndpoint = "start";
      this.renderDraft();
    }
    validationError() {
      if (!this.draft) return "";
      if (this.draft.kind === "preset") {
        if (this.draft.preset === "all" && !this.context().coverage?.start_date) return "本地台账暂无可查询的日期。";
        if (!this.preview(this.draft)) return "尚未取得服务端时间，请重新打开页面后选择。";
        if (!supportedPreview(this.preview(this.draft))) return "时间范围超出支持范围，请重新选择。";
        return "";
      }
      if (!minuteValid(this.draft.start)) return "请填写有效的开始日期和时间。";
      if (!this.draft.follow_now) {
        if (!minuteValid(this.draft.end)) return "请填写有效的结束日期和时间。";
        if (this.draft.end < this.draft.start) return "结束时间不能早于开始时间。";
      }
      if (!supportedPreview(this.preview(this.draft))) return "时间范围超出支持范围，请重新选择。";
      return "";
    }
    renderDraft() {
      if (!this.draft) return;
      const follow = Boolean(this.draft.follow_now);
      for (const [preset, item] of this.presetButtons) {
        const selected = this.draft.kind === "preset" && this.draft.preset === preset;
        item.classList.toggle("active", selected); item.setAttribute("aria-pressed", String(selected));
        item.disabled = this.applying || (preset === "all" && !this.context().coverage?.start_date);
      }
      this.follow.checked = follow;
      this.follow.disabled = this.applying || this.draft.preset === "all";
      this.inputs.end.date.disabled = follow || this.applying; this.inputs.end.time.disabled = follow || this.applying;
      this.inputs.start.date.disabled = this.applying; this.inputs.start.time.disabled = this.applying;
      this.inputs.end.hint.textContent = follow ? "截止本次更新预览的时刻" : "手动设置时，包含结束分钟";
      for (const key of ["start", "end"]) {
        this.inputs[key].group.classList.toggle("active", key === this.activeEndpoint);
        this.endpointButtons[key].classList.toggle("active", key === this.activeEndpoint);
        this.endpointButtons[key].setAttribute("aria-pressed", String(key === this.activeEndpoint));
        this.endpointButtons[key].disabled = this.applying || (key === "end" && follow);
      }
      const error = this.serverError || this.validationError();
      this.error.hidden = !error; this.error.textContent = error;
      this.confirm.disabled = Boolean(error) || this.applying;
      this.cancel.disabled = this.applying;
      this.confirm.textContent = this.applying ? "正在更新…" : "确定并更新";
      for (const input of [this.inputs.start.date, this.inputs.start.time, this.inputs.end.date, this.inputs.end.time]) {
        input.setAttribute("aria-invalid", String(Boolean(error)));
        if (error) input.setAttribute("aria-errormessage", this.error.id); else input.removeAttribute("aria-errormessage");
      }
      const preview = this.preview(this.draft);
      const explanation = preview ? `参考范围：${describe(preview)}。` : "请选择开始和结束时间。";
      this.explanation.textContent = explanation + (follow ? "跟随范围在本次预览时确定；保存沿用预览，不会继续延长。" : this.draft.kind === "preset" && this.draft.preset !== "all" ? "保留快捷范围的秒级截止；编辑端点将转为自定义分钟范围。" : "包含起止分钟；历史日汇总仅在完整覆盖当天时计入。");
      this.renderCalendar();
      if (this.opened) this.position();
    }
    jumpToEndpoint() {
      const date = this.inputs[this.activeEndpoint].date.value;
      if (date) { this.viewMonth = date.slice(0, 7); this.focusedDate = date; }
      this.renderDraft();
    }
    moveMonth(amount) {
      const current = new Date(`${this.viewMonth}-01T00:00:00Z`);
      current.setUTCMonth(current.getUTCMonth() + amount);
      if (current.getUTCFullYear() < 1 || current.getUTCFullYear() > 9999) return;
      this.viewMonth = current.toISOString().slice(0, 7); this.focusedDate = `${this.viewMonth}-01`;
      this.renderCalendar();
    }
    renderCalendar() {
      if (!this.viewMonth) return;
      const first = new Date(`${this.viewMonth}-01T00:00:00Z`);
      this.monthLabel.textContent = `${first.getUTCFullYear()} 年 ${first.getUTCMonth() + 1} 月`;
      this.previousMonth.disabled = this.applying || this.viewMonth === "0001-01";
      this.nextMonth.disabled = this.applying || this.viewMonth === "9999-12";
      const firstGrid = first.getTime() - ((first.getUTCDay() + 6) % 7) * 86400000;
      const start = this.inputs.start.date.value; const end = this.inputs.end.date.value;
      const today = this.context().now?.slice(0, 10);
      let focus = this.focusedDate;
      if (!focus || focus.slice(0, 7) !== this.viewMonth) focus = `${this.viewMonth}-01`;
      this.grid.replaceChildren();
      for (let week = 0; week < 6; week += 1) {
        const row = element("div", "calendar-week"); row.setAttribute("role", "row");
        for (let day = 0; day < 7; day += 1) {
          const epoch = firstGrid + (week * 7 + day) * 86400000;
          const date = new Date(epoch).toISOString().slice(0, 10);
          const inMonth = date.slice(0, 7) === this.viewMonth;
          const item = button(String(new Date(epoch).getUTCDate()), "calendar-day");
          item.dataset.date = date; item.setAttribute("role", "gridcell");
          item.setAttribute("aria-label", `${date}${date === start ? "，开始日期" : ""}${date === end ? "，结束日期" : ""}`);
          item.setAttribute("aria-selected", String(date === start || date === end));
          item.classList.toggle("outside-month", !inMonth);
          item.classList.toggle("in-range", Boolean(start && end && date > start && date < end));
          item.classList.toggle("range-start", date === start); item.classList.toggle("range-end", date === end);
          if (date === today) item.setAttribute("aria-current", "date");
          item.disabled = this.applying || date < "0001-01-01" || date > "9999-12-31";
          item.tabIndex = date === focus && !item.disabled ? 0 : -1;
          row.append(item);
        }
        this.grid.append(row);
      }
    }
    pickDate(date) {
      if (this.applying) return;
      const key = this.activeEndpoint;
      this.inputs[key].date.value = date;
      if (!this.inputs[key].time.value) this.inputs[key].time.value = key === "start" ? "00:00" : "23:59";
      this.editEndpoint(key);
      this.focusedDate = date;
      if (key === "start" && !this.draft.follow_now) this.activeEndpoint = "end";
      this.renderDraft();
      this.grid.querySelector(`[data-date="${date}"]`)?.focus();
    }
    calendarKey(event) {
      const target = event.target.closest("[data-date]");
      if (!target || this.applying) return;
      const date = new Date(`${target.dataset.date}T00:00:00Z`);
      const days = {ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7};
      if (event.key in days) date.setUTCDate(date.getUTCDate() + days[event.key]);
      else if (event.key === "Home") date.setUTCDate(date.getUTCDate() - (date.getUTCDay() + 6) % 7);
      else if (event.key === "End") date.setUTCDate(date.getUTCDate() + 6 - (date.getUTCDay() + 6) % 7);
      else if (["PageUp", "PageDown"].includes(event.key)) {
        const originalDay = date.getUTCDate(); date.setUTCDate(1); date.setUTCMonth(date.getUTCMonth() + (event.key === "PageUp" ? -1 : 1));
        const last = new Date(date); last.setUTCMonth(last.getUTCMonth() + 1); last.setUTCDate(0);
        date.setUTCDate(Math.min(originalDay, last.getUTCDate()));
      } else return;
      event.preventDefault();
      if (date.getUTCFullYear() < 1 || date.getUTCFullYear() > 9999) return;
      this.focusedDate = date.toISOString().slice(0, 10); this.viewMonth = this.focusedDate.slice(0, 7);
      this.renderCalendar(); this.grid.querySelector(`[data-date="${this.focusedDate}"]`)?.focus();
    }
    trapTab(event) {
      const items = [...this.panel.querySelectorAll("button:not(:disabled),input:not(:disabled)")].filter((item) => item.tabIndex >= 0);
      if (!items.length) { event.preventDefault(); return; }
      if (event.shiftKey && event.target === items[0]) { event.preventDefault(); items.at(-1).focus(); }
      else if (!event.shiftKey && event.target === items.at(-1)) { event.preventDefault(); items[0].focus(); }
    }
    position() {
      if (!this.opened) return;
      const rect = this.trigger.getBoundingClientRect();
      const width = Math.min(680, innerWidth - 24);
      this.panel.style.width = `${width}px`;
      this.panel.style.maxHeight = `${innerHeight - 24}px`;
      this.panel.style.left = `${Math.max(12, Math.min(rect.left, innerWidth - width - 12))}px`;
      const height = this.panel.offsetHeight;
      this.panel.style.top = `${Math.max(12, Math.min(rect.bottom + 8, innerHeight - height - 12))}px`;
    }
    async apply() {
      if (this.applying || !this.draft || this.disabled) return;
      const error = this.validationError();
      if (error) { this.serverError = error; this.renderDraft(); return; }
      const intent = clone(this.draft);
      this.applying = true; this.renderDraft();
      try {
        await this.onApply(intent);
        this.applying = false; this.close(true);
      } catch (error) {
        this.serverError = error.message || "范围未能应用，请调整后重试。";
      } finally {
        this.applying = false;
        if (this.opened) { this.renderDraft(); this.position(); }
      }
    }
    destroy() {
      this.applying = false; this.close(); this.abort.abort(); this.root.replaceChildren();
    }
  }
  return {create: (root, options) => new Picker(root, options), describe, fromAnalysis, editableIntent, wholeDays, name};
})();
