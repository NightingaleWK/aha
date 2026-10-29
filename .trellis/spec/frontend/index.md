# 前端开发规范

aha 的页面是由本机 Python 服务提供的原生 HTML/CSS/JavaScript，资源位于 `src/aha/web/`。代码组织、数据流和验证都以当前浏览器页面为准，后端入口见 [后端规范](../backend/index.md)。

## 开发前检查

- 先读当前任务需求/设计与 [本机页面契约](./local-web-contract.md)，确认请求、失效、主体和冻结材料规则。
- 修改页面结构读组件规范，修改选择/预览/保存读状态规范，修改载荷读数据边界规范。
- 复核 [server.py](../../../src/aha/server.py) 的真实请求边界；保留简体中文产品文案、内置资源和实际字号。
- 使用独立 data-dir，个人来源、材料、浏览器凭证和截图不进入 Git。
- 可见功能实施还需执行 [成品交付与清理](../backend/delivery-and-cleanup.md)：完成桌面程序验收及临时文件收尾；WSL 交互预览采用当次本机 HTTP 链接。

## 规范索引

| 文档 | 解决的问题 |
| --- | --- |
| [本机页面契约](./local-web-contract.md) | HTTP、业务操作、金额、隐私、字号和下载规则 |
| [资源布局](./directory-structure.md) | HTML/JS/CSS/SVG、服务资源映射和打包入口 |
| [DOM 组件与事件](./component-guidelines.md) | 元素工厂、表格、dialog、事件绑定与可访问反馈 |
| [状态与请求](./state-management.md) | state、run/api、失效、重试、分页、修订和生命周期 |
| [JavaScript 数据边界](./type-safety.md) | 真实对象、可选字段、金额字符串、空/零区别和服务端校验 |
| [质量要求](./quality-guidelines.md) | 语法、HTTP、真实浏览器、显示/导出与证据要求 |

## 质量检查

按 [质量要求](./quality-guidelines.md) 检查 JavaScript 语法和相关 HTTP 流程。请求形状、生命周期、下载或页面布局改变时补实际浏览器验证；Store 直调或 CSS 字符串检查不能代替真实页面行为。

业务字段和错误码保留原文，规范与产品文案使用简体中文。状态和组件分题已经覆盖实际请求/事件处理，不另维护框架 hooks 专题。
