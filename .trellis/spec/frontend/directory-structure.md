# 页面资源布局

## 实际入口

| 路径 | 职责 |
| --- | --- |
| `src/aha/web/index.html` | 三个业务页面、表单、筛选、预览区和原生 dialog 的静态结构 |
| `src/aha/web/app.js` | DOM 渲染、事件、临时状态、API、预览、批次和下载 |
| `src/aha/web/form-controls.js` | 基于原生 select 的搜索下拉、简单下拉与分段选择，共享键盘/禁用/销毁 |
| `src/aha/web/time-range-picker.js` | 北京时间意图、日历、分钟草稿、确认/取消与规范化范围展示 |
| `src/aha/web/style.css` | 颜色/字号变量、导航/面板/表格/弹窗、响应式布局和可访问焦点 |
| `src/aha/web/mark.svg` | 本机内置品牌图形 |
| `src/aha/server.py` | 资源白名单、Content-Type、认证和安全响应头 |
| `pyproject.toml` | web 的 HTML/CSS/JS/SVG package-data |

页面没有独立包管理器、构建产物目录或组件框架。页面按 `form-controls.js`、`time-range-picker.js`、`app.js` 顺序 defer 加载，资源全部来自本机服务；不要凭目录模板增加远程字体/CDN 或前端打包链。

## 服务与打包边界

[server.py](../../../src/aha/server.py) 的 `ASSETS` 显式映射资源，例如：

```python
"/app.js": ("app.js", "text/javascript; charset=utf-8"),
"/form-controls.js": ("form-controls.js", "text/javascript; charset=utf-8"),
"/time-range-picker.js": ("time-range-picker.js", "text/javascript; charset=utf-8"),
"/style.css": ("style.css", "text/css; charset=utf-8"),
"/mark.svg": ("mark.svg", "image/svg+xml"),
```

新增本机资源时同步核对这个白名单、[pyproject.toml](../../../pyproject.toml) 的 package-data 和 [Windows 构建入口](../../../scripts/build_windows.py) 的收集方式，验证安装/打包后仍能读取。页面使用绝对本机路径 `/app.js` 等，不把用户资料目录或运行凭证变为可静态访问目录。

## 修改与检查

HTML 的元素 id、`data-page/data-tab` 与 [app.js](../../../src/aha/web/app.js) 事件/渲染代码一起核对；样式 class 与 [style.css](../../../src/aha/web/style.css) 同步检索。三页共用脚本和状态，不为同一业务另建隐藏的数据副本。

[tests/test_http.py](../../../tests/test_http.py) 的 `test_auth_origin_csrf_static_and_payload_boundaries` 覆盖资源认证和边界；实际浏览器仍需验证页面加载及事件。新增资源不能只在源码运行时可用，还应在对应原生发布阶段核对。

业务行为见 [页面契约](./local-web-contract.md)，DOM 结构和事件方式见 [组件规范](./component-guidelines.md)。
