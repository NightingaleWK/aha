"use strict";

// The native select owns the value, options and permissions. This layer only
// presents them; programmatic writes are followed by AhaForms.sync().
window.AhaForms = (() => {
  const controls = new Map();
  let active = null;
  let nextId = 0;

  function element(tag, className, text) {
    const item = document.createElement(tag);
    if (className) item.className = className;
    if (text !== undefined) item.textContent = text;
    return item;
  }
  function labelText(select) {
    if (select.getAttribute("aria-label")) return select.getAttribute("aria-label");
    return [...select.labels].map((label) => {
      const copy = label.cloneNode(true);
      copy.querySelectorAll("select,input,textarea,button,.form-control,.field-help").forEach((item) => item.remove());
      return copy.textContent.trim();
    }).filter(Boolean).join(" ") || "选择";
  }
  function optionDisabled(option) {
    return option.disabled || (option.parentElement?.tagName === "OPTGROUP" && option.parentElement.disabled);
  }
  function closeAll(returnFocus = false) {
    active?.close(returnFocus);
  }

  class SelectControl {
    constructor(select) {
      this.select = select;
      this.label = labelText(select);
      this.segmented = select.dataset.control === "segmented";
      this.searchable = select.dataset.searchable === "true";
      this.id = `form-control-${++nextId}`;
      this.root = element("span", `form-control${this.segmented ? " form-segmented" : ""}`);
      this.abort = new AbortController();
      this.focusedIndex = -1;
      this.previousHidden = select.hidden;
      this.previousTabindex = select.getAttribute("tabindex");
      this.previousAriaHidden = select.getAttribute("aria-hidden");
      select.hidden = true;
      select.setAttribute("aria-hidden", "true");
      select.tabIndex = -1;
      select.after(this.root);
      if (this.segmented) {
        this.root.setAttribute("role", "radiogroup");
        this.root.setAttribute("aria-label", this.label);
        this.root.addEventListener("keydown", (event) => this.segmentKey(event), {signal: this.abort.signal});
      } else {
        this.trigger = element("button", "form-select-trigger");
        this.trigger.type = "button";
        this.trigger.setAttribute("role", "combobox");
        this.trigger.setAttribute("aria-haspopup", "listbox");
        this.trigger.setAttribute("aria-controls", `${this.id}-list`);
        this.trigger.setAttribute("aria-expanded", "false");
        this.value = element("span", "form-select-value");
        const arrow = element("span", "control-chevron", "⌄"); arrow.setAttribute("aria-hidden", "true");
        this.trigger.append(this.value, arrow);
        this.popup = element("div", "form-select-popup");
        this.popup.hidden = true;
        this.popup.setAttribute("popover", "manual");
        if (this.searchable) {
          this.search = element("input", "form-select-search");
          this.search.type = "search";
          this.search.placeholder = "搜索项目…";
          this.search.autocomplete = "off";
          this.search.setAttribute("role", "combobox");
          this.search.setAttribute("aria-label", `搜索${this.label}`);
          this.search.setAttribute("aria-controls", `${this.id}-list`);
          this.search.setAttribute("aria-expanded", "true");
          this.search.setAttribute("aria-autocomplete", "list");
          this.search.addEventListener("input", () => { this.focusedIndex = -1; this.renderOptions(); }, {signal: this.abort.signal});
          this.popup.append(this.search);
        }
        this.list = element("div", "form-select-list");
        this.list.id = `${this.id}-list`;
        this.list.setAttribute("role", "listbox");
        this.list.setAttribute("aria-label", this.label);
        this.empty = element("p", "form-select-empty", this.searchable ? "没有匹配的项目" : "暂无可选项");
        this.empty.setAttribute("role", "status"); this.empty.hidden = true;
        this.popup.append(this.list, this.empty);
        this.root.append(this.trigger, this.popup);
        this.trigger.addEventListener("click", (event) => { event.preventDefault(); this.opened ? this.close() : this.open(); }, {signal: this.abort.signal});
        this.root.addEventListener("keydown", (event) => this.keydown(event), {signal: this.abort.signal});
        this.list.addEventListener("pointerdown", (event) => event.preventDefault(), {signal: this.abort.signal});
        this.list.addEventListener("click", (event) => {
          const option = event.target.closest("[data-option-index]");
          if (option && this.list.contains(option)) { event.preventDefault(); this.choose(Number(option.dataset.optionIndex)); }
        }, {signal: this.abort.signal});
        for (const label of select.labels) {
          if (label.control !== select) continue;
          label.addEventListener("click", (event) => {
            if (event.composedPath().includes(this.root)) return;
            event.preventDefault(); this.trigger.focus();
          }, {signal: this.abort.signal});
        }
      }
      select.addEventListener("change", () => this.sync(), {signal: this.abort.signal});
      select.addEventListener("invalid", () => {
        this.sync(); (this.trigger || this.root.querySelector("button:not(:disabled)"))?.focus();
      }, {signal: this.abort.signal});
      this.observer = new MutationObserver(() => this.sync());
      this.observer.observe(select, {childList: true, subtree: true, characterData: true,
        attributes: true, attributeFilter: ["disabled", "label", "value", "selected", "aria-invalid", "aria-describedby"]});
      this.sync();
    }
    sync() {
      const select = this.select;
      this.root.classList.toggle("is-disabled", select.disabled);
      this.root.setAttribute("aria-disabled", String(select.disabled));
      if (this.segmented) {
        const focusedValue = this.root.contains(document.activeElement) ? document.activeElement.dataset.value : null;
        const signature = JSON.stringify([...select.options].map((option) => [option.value, option.label, option.hidden]));
        const changed = signature !== this.segmentSignature;
        if (changed) {
          this.segmentSignature = signature; this.root.replaceChildren();
          for (const option of select.options) {
            const index = option.index;
            const button = element("button", "form-segment", option.label);
            button.type = "button"; button.dataset.value = option.value;
            button.setAttribute("role", "radio");
            button.addEventListener("click", (event) => { event.preventDefault(); this.choose(index); });
            this.root.append(button);
          }
        }
        [...this.root.children].forEach((button, index) => {
          const option = select.options[index];
          button.setAttribute("aria-checked", String(option.selected));
          button.disabled = select.disabled || optionDisabled(option);
          button.hidden = option.hidden; button.tabIndex = option.selected ? 0 : -1;
        });
        if (changed && focusedValue !== null) [...this.root.children].find((button) => button.dataset.value === focusedValue)?.focus();
        return;
      }
      const selected = select.options[select.selectedIndex];
      this.value.textContent = selected?.label || "请选择";
      this.trigger.title = selected?.label || "";
      this.trigger.setAttribute("aria-label", `${this.label}：${selected?.label || "请选择"}`);
      this.trigger.disabled = select.disabled;
      for (const name of ["aria-invalid", "aria-describedby"]) {
        if (select.hasAttribute(name)) this.trigger.setAttribute(name, select.getAttribute(name));
        else this.trigger.removeAttribute(name);
      }
      if (select.disabled && this.opened) this.close();
      if (this.search) this.search.disabled = select.disabled;
      if (this.opened) { this.renderOptions(); this.position(); }
    }
    choose(index) {
      const option = this.select.options[index];
      if (this.select.disabled || !option || optionDisabled(option)) return;
      const changed = this.select.selectedIndex !== index;
      this.select.selectedIndex = index;
      this.close(true);
      this.sync();
      if (changed) this.select.dispatchEvent(new Event("change", {bubbles: true}));
    }
    segmentKey(event) {
      if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End"].includes(event.key) || this.select.disabled) return;
      event.preventDefault();
      const options = [...this.select.options].filter((option) => !option.hidden && !optionDisabled(option));
      if (!options.length) return;
      let index = options.findIndex((option) => option.selected);
      if (event.key === "Home") index = 0;
      else if (event.key === "End") index = options.length - 1;
      else index = (index + (["ArrowLeft", "ArrowUp"].includes(event.key) ? -1 : 1) + options.length) % options.length;
      this.choose(options[index].index);
      this.root.querySelector('[aria-checked="true"]')?.focus();
    }
    renderOptions() {
      const query = (this.search?.value || "").trim().toLocaleLowerCase("zh-CN");
      this.visibleOptions = [...this.select.options].filter((option) => !option.hidden && option.label.toLocaleLowerCase("zh-CN").includes(query));
      const enabled = this.visibleOptions.filter((option) => !optionDisabled(option));
      if (!enabled.some((option) => option.index === this.focusedIndex)) this.focusedIndex = enabled.find((option) => option.selected)?.index ?? enabled[0]?.index ?? -1;
      this.list.replaceChildren();
      for (const option of this.visibleOptions) {
        const item = element("div", "form-select-option");
        item.id = `${this.id}-option-${option.index}`;
        item.dataset.optionIndex = String(option.index);
        item.setAttribute("role", "option");
        item.setAttribute("aria-selected", String(option.selected));
        item.setAttribute("aria-disabled", String(optionDisabled(option)));
        item.classList.toggle("is-focused", option.index === this.focusedIndex);
        const check = element("span", "form-option-check", option.selected ? "✓" : ""); check.setAttribute("aria-hidden", "true");
        item.append(element("span", "", option.label), check);
        this.list.append(item);
      }
      this.empty.hidden = this.visibleOptions.length !== 0;
      const activeId = this.focusedIndex < 0 ? null : `${this.id}-option-${this.focusedIndex}`;
      for (const input of [this.trigger, this.search].filter(Boolean)) {
        if (activeId) input.setAttribute("aria-activedescendant", activeId);
        else input.removeAttribute("aria-activedescendant");
      }
    }
    position() {
      if (!this.opened) return;
      const rect = this.trigger.getBoundingClientRect();
      const width = Math.min(Math.max(rect.width, this.searchable ? 280 : 180), innerWidth - 24);
      this.popup.style.width = `${width}px`;
      const roomBelow = innerHeight - rect.bottom - 12;
      const roomAbove = rect.top - 12;
      const above = roomBelow < 220 && roomAbove > roomBelow;
      this.popup.style.maxHeight = `${Math.max(120, Math.min(380, above ? roomAbove - 6 : roomBelow - 6))}px`;
      this.popup.style.left = `${Math.max(12, Math.min(rect.left, innerWidth - width - 12))}px`;
      this.popup.style.top = above ? `${Math.max(12, rect.top - this.popup.offsetHeight - 6)}px` : `${Math.max(12, Math.min(rect.bottom + 6, innerHeight - this.popup.offsetHeight - 12))}px`;
    }
    open() {
      if (this.select.disabled || !this.select.isConnected) return;
      closeAll();
      this.opened = true; active = this;
      this.popup.hidden = false;
      if (this.search) this.search.value = "";
      this.focusedIndex = this.select.selectedIndex;
      this.trigger.setAttribute("aria-expanded", "true");
      this.renderOptions();
      if (this.popup.showPopover) this.popup.showPopover();
      this.position();
      (this.search || this.trigger).focus();
      this.list.querySelector(".is-focused")?.scrollIntoView({block: "nearest"});
    }
    close(returnFocus = false) {
      if (this.segmented || !this.opened) return;
      this.opened = false;
      if (this.popup.hidePopover && this.popup.matches(":popover-open")) this.popup.hidePopover();
      this.popup.hidden = true;
      this.trigger.setAttribute("aria-expanded", "false");
      this.trigger.removeAttribute("aria-activedescendant");
      if (active === this) active = null;
      if (returnFocus && !this.trigger.disabled && this.trigger.isConnected) this.trigger.focus();
    }
    keydown(event) {
      if (this.select.disabled) return;
      if (event.key === "Tab") {
        const fromSearch = event.target === this.search;
        this.close();
        if (fromSearch) this.trigger.focus({preventScroll: true});
        return;
      }
      if (event.key === "Escape" && this.opened) { event.preventDefault(); event.stopPropagation(); this.close(true); return; }
      if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
        event.preventDefault();
        if (!this.opened) { this.open(); return; }
        const enabled = this.visibleOptions.filter((option) => !optionDisabled(option));
        if (!enabled.length) return;
        let index = enabled.findIndex((option) => option.index === this.focusedIndex);
        if (event.key === "Home") index = 0;
        else if (event.key === "End") index = enabled.length - 1;
        else index = (index + (event.key === "ArrowUp" ? -1 : 1) + enabled.length) % enabled.length;
        this.focusedIndex = enabled[index].index;
        this.renderOptions(); this.list.querySelector(".is-focused")?.scrollIntoView({block: "nearest"});
      } else if (event.key === "Enter" || (event.key === " " && event.target === this.trigger)) {
        event.preventDefault();
        if (this.opened) this.choose(this.focusedIndex); else this.open();
      } else if (event.target === this.trigger && this.searchable && event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
        event.preventDefault(); this.open(); this.search.value = event.key; this.renderOptions();
      }
    }
    destroy() {
      this.close(); this.abort.abort(); this.observer.disconnect(); this.root.remove();
      this.select.hidden = this.previousHidden;
      for (const [name, value] of [["tabindex", this.previousTabindex], ["aria-hidden", this.previousAriaHidden]]) {
        if (value === null) this.select.removeAttribute(name); else this.select.setAttribute(name, value);
      }
      controls.delete(this.select);
    }
  }
  function mount(root = document) {
    const selects = root.matches?.("select") ? [root] : [...root.querySelectorAll("select")];
    for (const select of selects) if (!controls.has(select) && select.dataset.control !== "native") controls.set(select, new SelectControl(select));
  }
  function sync(root = document) {
    mount(root);
    for (const [select, control] of controls) if (root === document || root === select || root.contains(select)) control.sync();
  }
  function destroy(root) {
    for (const [select, control] of controls) if (root === select || root.contains(select)) control.destroy();
  }
  document.addEventListener("pointerdown", (event) => {
    if (active && !event.composedPath().includes(active.root)) active.close();
  }, true);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && active) { event.preventDefault(); event.stopPropagation(); active.close(true); }
  }, true);
  document.addEventListener("focusin", (event) => {
    if (active && !event.composedPath().includes(active.root)) active.close();
  });
  document.addEventListener("close", (event) => { if (active && event.target.contains(active.select)) active.close(); }, true);
  window.addEventListener("resize", () => active?.position());
  document.addEventListener("scroll", () => active?.position(), true);
  const lifecycle = new MutationObserver((mutations) => {
    for (const [select, control] of controls) if (!select.isConnected) control.destroy();
    for (const mutation of mutations) for (const added of mutation.addedNodes) if (added.nodeType === Node.ELEMENT_NODE) mount(added);
  });
  lifecycle.observe(document.documentElement, {childList: true, subtree: true});
  return {mount, sync, destroy, closeAll};
})();
