# DOM 组件与事件

## 元素与渲染函数

[app.js](../../../src/aha/web/app.js) 使用 `node`、`table` 及 `renderProjects/renderAvailability/renderPreview/renderBatches/renderBatchDetail` 等普通函数组合页面。没有 props 生命周期；数据由 state 和函数参数传入，容器通过 `replaceChildren` 更新。

实际元素工厂片段：

```javascript
const item = document.createElement(tag);
if (className) item.className = className;
if (text !== undefined && text !== null) item.textContent = String(text);
```

来源/用户文字使用 `textContent`，不要拼 `innerHTML`。表格复用 `table(columns, rows, selectable)`，按列提供渲染器；金额展示使用 money、计数用 counts，计算归后端。业务 payload 和保存权限见 [页面契约](./local-web-contract.md)。

## 结构与交互

- 静态结构归 [index.html](../../../src/aha/web/index.html)，可变内容归渲染函数，样式归 [style.css](../../../src/aha/web/style.css)。不要在 JS 中复制整套静态 HTML 或构造第二份业务状态。
- `openProject/openRevision/openLifecycle` 填充并调用原生 `dialog.showModal()`；表单 submit 使用 `preventDefault`，异步变更经 run 包装。
- 实际事件绑定示例：`$("project-form").addEventListener("submit", (event) => { event.preventDefault(); run("正在保存项目…", saveProject); });`。新增绑定跟随现有脚本末尾入口与所操作的函数，不引入另一条并发保存路径。
- `notify/clearFeedback` 管反馈：成功提示短时浮动，失败保留；打开弹窗时操作错误也在弹窗内显示。不要成功后残留旧失败或让主页面提示盖住弹窗。
- 退出通过认证 shutdown 调用，关闭浏览器标签不能视为退出服务；退出后 `state.stopped` 禁用控件。

## 样式与可访问性

复用 `:root` 颜色/字号变量、系统字体、面板/表格/按钮类。正文和输入 16px，表格/按钮 15px，标签/表头 14px，次要至少 13px，主控件约 44px。长内容换行或容器滚动，响应式不靠缩小文字解决宽度。

保留 label、按钮可访问名称、aria-current/aria-selected、notice 的 status/live region、弹窗错误的 alert 和 focus-visible。隐藏元素用现有 hidden 规则，表格的选择和分页应保留可操作提示。

## 常见错误与验证

不要把金额转成 Number、通过前端可见页重算导出、让历史版本显示修改动作，或给冲突弹窗增加绕过操作。不要将目录线索覆盖描述成业务归属已确认。

按 [质量要求](./quality-guidelines.md) 在真实页面检查弹窗打开/关闭、键盘焦点、忙碌恢复、长文本/金额/币种与窄窗口；接口形状用 [test_http.py](../../../tests/test_http.py) 复核。状态失效和请求重试详见 [状态规范](./state-management.md)。
