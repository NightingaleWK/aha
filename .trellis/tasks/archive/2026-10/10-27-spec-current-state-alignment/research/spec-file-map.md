# 规范文件与交付映射

本映射是实施前的目标文件集合，尚未表示文件已修改。共 17 份目标 spec：backend 7 份、frontend 7 份、guides 3 份。当前 18 份中的 hooks 模板移除，职责归并如下。

## backend

| 文件 | 目标内容 | 实例入口 |
| --- | --- | --- |
| `index.md` | 中文导航、开发前检查、按改动范围选择规范与验证 | README、pyproject、各分题 |
| `usage-evidence-contract.md` | 核对并中文整理业务契约，保留签名、字段、错误码和核心不变量 | domain、analysis、claims、batches、server、evidence |
| `directory-structure.md` | 模块职责、Store 门面与领域模块、tests/scripts/web 所有权 | storage、archive、projects、batches、server |
| `database-guidelines.md` | 原生 sqlite3、源库只读与应用库写入、事务/备份/迁移/原件 | sources、storage、migrations、并发和迁移测试 |
| `error-handling.md` | AppError、HTTP code/message、异常转换、回滚及保留现场 | domain、sources、storage、server、HTTP 测试 |
| `logging-guidelines.md` | 私有启动输出、禁用默认访问日志、库内审计事件、安全错误 | __main__、RequestHandler、claim_events、status_events |
| `quality-guidelines.md` | Python3.12、typing/Any 实情、Ruff/mypy/unittest、隔离数据、分层验证 | pyproject、tests、README、build_windows |

## frontend

| 文件 | 目标内容 | 实例入口 |
| --- | --- | --- |
| `index.md` | 原生页面导航、契约与五份分题入口、预检和质量门禁 | web 四份资源、server |
| `local-web-contract.md` | 中文整理 HTTP/交互/生命周期/字号契约，核对后端签名 | app.js、HTML/CSS、server、HTTP 测试 |
| `directory-structure.md` | 四份 web 资源、ASSETS 与打包范围 | web、server、pyproject |
| `component-guidelines.md` | DOM 工厂、表格、dialog、事件、可访问反馈、样式变量 | node/table、render/open 函数、HTML/CSS |
| `state-management.md` | state/run/api、失效、selected/分页、pendingBatch、修订主体和生命周期 | app.js、server 分析缓存与批次路由 |
| `type-safety.md` | JavaScript 数据契约、金额字符串、可选字段、null/空/零区别 | money/claim/validateClaim/prepareBatch、server 输入辅助函数 |
| `quality-guidelines.md` | Node/HTTP 测试、浏览器触发条件、视觉/下载/反馈复核与历史证据边界 | test_http*.py、归档 verification、README |

`hook-guidelines.md` 不再保留独立文件：api/run/事件绑定在状态与组件规范中说明。现行索引和初始化任务同步清理引用；已归档任务的历史路径记录保持原样，不将其误报为必须重写的现行断链。

## guides

| 文件 | 目标内容 |
| --- | --- |
| `index.md` | 中文入口、何时读复用/跨层指南，与两层契约的关系 |
| `code-reuse-thinking-guide.md` | domain/claims/analysis/Store/DOM 的实际复用；先 rg 搜索；移除 TS、CLI 平台及 reducer 等非本项目强制模式 |
| `cross-layer-thinking-guide.md` | 来源→留存→归属→分析→占用→导出→页面的边界；输入校验与事务重检分开；去除 Trellis 引擎开发流程 |

## 相关工作文档

| 文件/目录 | 允许的变动 |
| --- | --- |
| `README.md` | 开发规范导航；必要事实纠偏须有源码依据 |
| `.trellis/tasks/00-bootstrap-guidelines/prd.md` | 中文实际目标与清单、此前部分契约与本次补齐关系、验收及收尾条件 |
| `.trellis/tasks/00-bootstrap-guidelines/task.json` | 仅标题/说明/备注/相关文件等元数据；保留 id、name、创建信息、状态和目录 |
| `.trellis/tasks/00-bootstrap-guidelines/verification.md` | 新增规范验收映射与检查结果，引用本轮任务，不宣称正式业务验收或已归档 |
| 本任务目录 | 规划、研究、上下文和执行后验证记录 |

不创建额外父子任务：规范、导航与初始化清单属于同一文档交付。两个已归档产品任务仅作为只读证据。
