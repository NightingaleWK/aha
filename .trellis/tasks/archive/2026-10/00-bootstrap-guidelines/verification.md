# 规范初始化验收映射

日期：2026-10-27。现状基线为 `main` / `434c785`；本轮执行记录见[文档校准验证](../10-27-spec-current-state-alignment/verification.md)。

## 交付与完成依据

最终规范共 17 份：backend 7、frontend 7、guides 3。既有两份业务契约由前两项产品任务引入，本次补齐其余适用分题、中文整理并核对已有契约；删除 hooks 模板，实际请求和事件内容归并到状态、组件规范。

| 交付项 | 文档与可核对实例 |
| --- | --- |
| 后端模块组织 | [目录规范](../../../../spec/backend/directory-structure.md)：Store.config 局部导入 projects.configuration，模块职责映射到 src/aha |
| SQLite | [持久化规范](../../../../spec/backend/database-guidelines.md)：Store._transaction、只读 WAL backup、逐条迁移；双进程/提交故障测试 |
| 错误 | [错误规范](../../../../spec/backend/error-handling.md)：AppError 与安全 JSON、来源异常转换及事务回滚 |
| 输出和历史 | [运行输出规范](../../../../spec/backend/logging-guidelines.md)：禁用 log_message、私有 AHA_URL/runtime、SQLite status_events/claim_events |
| 后端质量 | [质量规范](../../../../spec/backend/quality-guidelines.md)：真实有效版本/原 ZIP 断言，隔离命令及原生发布门禁 |
| 前端资源 | [资源规范](../../../../spec/frontend/directory-structure.md)：ASSETS 与 package-data、HTML/JS/CSS/SVG 所有权 |
| DOM 与事件 | [组件规范](../../../../spec/frontend/component-guidelines.md)：node/textContent、表格、dialog、submit/run 和可访问反馈 |
| 状态与请求 | [状态规范](../../../../spec/frontend/state-management.md)：pendingBatch 请求签名与幂等、预览/弹窗失效、专用修订主体 |
| 数据边界 | [数据规范](../../../../spec/frontend/type-safety.md)：金额空字符串→后端 None/JSON null，record_key 选择与后端指纹绑定 |
| 前端质量 | [质量规范](../../../../spec/frontend/quality-guidelines.md)：共享 CookieJar 真实请求例子、浏览器触发条件与显示/材料检查 |
| 两份主要契约 | [后端契约](../../../../spec/backend/usage-evidence-contract.md)、[页面契约](../../../../spec/frontend/local-web-contract.md)：保留七部分结构与既有技术标识，核对真实接口和业务约束 |
| 思考与入口 | [思考指南](../../../../spec/guides/index.md)：复用与跨层 aha 实例；[README](../../../../../README.md)和各层索引提供导航 |

## 检查结论

- 17 份现行 spec 的占位文字已移除，三个索引与真实文件集合一致。
- 本地文档/源码链接、页内锚点、命名测试和代码围栏已自检；两份原契约的 snake_case 技术标识保留。
- 核对了 HTTP 输入解析与事务内重检、前后端金额表示及选择/指纹的职责，避免沿用模板泛化规则。
- 本任务的身份、创建/归属信息、优先级和 `in_progress` 状态保留；原始 trellis init 来源备注保留。更新范围是文档与说明元数据。
- 产品源码、测试、依赖、构建脚本、已归档任务与历史日志均未修改；本轮没有个人资料读写、迁移、发布或 Git 提交/推送/归档。

全范围独立复核和修正后增量复核均通过，最终检查数值统一记录在[本轮验证](../10-27-spec-current-state-alignment/verification.md)，不重复维护。源码基线 124 项测试与静态检查的时间范围在该记录中单列。

## 当前状态与收尾

规范文件和自检依据已齐备，PRD 的完成项由上表和本轮验证支持。本任务在2026-10-27验收时保持未归档；2026-10-28用户明确授权收尾后，已由Trellis归档为completed。文档完成不代表重新运行 Windows/浏览器/Excel/PDF 验收，也不代表正式资料迁移或实际报销通过。

## 收尾授权（2026-10-28）

用户已明确批准提交、推送及归档；上述保持 `in_progress` 的结论对应 2026-10-27 文档验收阶段。本次按授权归档本任务与现状校准任务，迁移后的本地链接和上下文另行复查。身份和初始化来源保留，完成日期与工作提交见归档后的 `task.json`；不扩写为产品或正式资料的新验收。

## 归档结果（2026-10-28）

本任务与现状校准任务均已归档，完成日期为2026-10-28；工作提交为 `5690e0b50cf7e73b12fdffb83a74867092fc3d7d`。迁移后的文档链接、上下文与身份复核通过，详细结果沿用上文所链本轮验证，不重复维护计数。
