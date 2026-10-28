# 本机页面与 HTTP 契约

## 1. 范围与入口

页面由 [server.py](../../../src/aha/server.py) 提供，使用内置 HTML/CSS/JavaScript，没有前端构建器或外部资源。修改 `web/` 或请求字段前同时阅读 [后端契约](../backend/usage-evidence-contract.md)。产品文案使用简体中文。

页面查询本地台账；只有启动程序一次和用户主动操作触发来源同步。刷新页面不重复启动同步；关闭标签不会退出进程，显式“退出程序”关闭服务。没有周期轮询来源、关闭后采集、托盘或开机启动。同步任务运行期间的 job 状态轮询不属于周期采集。

## 2. HTTP 入口

| 接口 | 契约摘要 |
| --- | --- |
| `GET /api/status` | 本次启动凭证、日期、默认来源、启动与最近同步任务 |
| `GET /api/ledger` | 本地记录数、覆盖、成功同步时间、最近尝试和目录依据 |
| `POST /api/sync` | `{path?}`，空路径使用当前系统用户默认 CCS 库，返回异步 job |
| `GET /api/sync/{job}` | `running/completed/failed/needs_review` 与结果；只有 running 继续轮询 |
| `POST /api/source/sqlite` | SQLite 手动同步入口的兼容路由 |
| `POST /api/source/sql` | `{name,content_base64}`，流式解析受限 SQL，返回异步 job |
| `POST /api/session-metadata` | `{roots?:string[]}`，刷新本地目录依据 |
| `GET /api/projects` | 项目配置与分类 revision |
| `POST /api/projects`、`/api/projects/{id}` | `name/description/directories`，名称最多160字符 |
| `POST /api/assignments` | `project_id` 加 keys 或 session_ids；rollup 按整条记录处理 |
| `GET /api/reconciliations` | `{cases}`，来源重建、版本或覆盖的待核对事项 |
| `POST /api/reconciliations/{id}` | `choice/reason/expected_generation/idempotency_key`，按实际候选确认 |
| `POST /api/analysis` | project、起止日期、`availability_mode=available|all`；只查本地库 |
| `GET /api/analysis/{id}/details` | `kind=detail|rollup|daily|models`、cursor、size1–200 |
| `POST /api/batches/{id}/analysis` | base_version、expected_generation 与当前筛选，绑定目标修订主体 |
| `POST /api/batches/preview` | analysis 或有效冻结版本加 claim，返回阻断与占用信息 |
| `POST /api/batches` | analysis/claim/idempotency_key，保存冻结草稿 |
| `GET /api/batches`、`/api/batches/{id}` | 报销列表、版本、生命周期与当前差异数 |
| `POST /api/batches/{id}/revisions` | base_version/expected_generation/claim/idempotency_key，按需传 analysis_id |
| `POST /api/batches/{id}/revisions/{n}/status` | status、expected_generation |
| `POST /api/batches/{id}/withdraw`、`/void` | reason、expected_generation、idempotency_key |
| `GET /api/batches/{id}/revisions/{n}/download` | 流式返回指定版本原 ZIP |
| `POST /api/shutdown` | 本机认证后退出 |

请求字段的精确允许值由服务端边界与领域函数验证。页面不再发送 capture_id、旧分页 page 或旧版本消解请求。

## 3. 状态、分页与同步

`api()` 统一 same-origin Cookie、JSON 与 X-AHA-CSRF；Cookie 按端口命名。启动 URL 与 runtime 凭证不得进入业务链接、日志或导出。

同步与普通操作分别使用 syncBusy/busy；来源读取在后台 job，现有本地查询仍可用。成功、失败和待核对分别显示；needs_review 是终态，停止轮询并提示核对，不显示成功提示。刷新页面恢复最近任务，不能被较早启动任务覆盖。上次成功时间和最近失败/待核对尝试分开展示。

明细、历史汇总、每日和模型使用游标，固定每页50条；游标绑定分析 revision 与筛选。total 可能为 null，此时显示本页数量并依据 next_cursor 导航，不猜总页数。切换标签、筛选或重新分析清选择；同标签翻页允许跨页勾选。导出使用完整分析范围，不只导出可见页。

来源、目录规则、人工归属、筛选、占用或数据 revision 改变后清当前预览、选择和保存身份。服务端返回 analysis_expired/data_changed/classification_changed/availability_changed/usage_claimed 等权威失效时，也须清打开的 current 修订分析并禁保存。frozen 修订仍以原冻结依据为准。

## 4. 保存、冻结与生命周期

- 后端负责金额与合计，页面只展示十进制字符串，不从分页或 JavaScript 浮点数求财务总额。
- available 用于新建，all 只读；零可用和待核对不得新建。显示排除原因及对应记录。
- current 修订必须通过目标批次专用分析获得自身占用豁免；主页面不能借用该主体。base_version/generation 防止旧弹窗覆盖新状态。
- 未改变的请求复用幂等 key；改变 payload 重新生成。保存后再下载；下载失败说明“记录已保存”，从报销记录重下原版本。
- 仅有效草稿可改。已提交可带原因撤回且保留占用；已报销纠错通过作废再新建。作废释放占用且为终态；旧版本与作废版本仍可下载原包。
- 用途/金额说明各最多4000字符；金额可空或零，填写须依据，币种 CNY/USD。参考 USD 成本与申请金额分开。新建成功清用途、金额和说明。
- 核对必须展示实际候选和所需原因，不自动把较晚导入的备份当最新事实，不补造差额明细。
- 用户/来源文字通过 textContent/DOM 插入，不拼接 innerHTML。

## 5. 可读性与产品表达

正文/输入16px，表格/按钮15px，标签/表头14px，次要至少13px；主要控件约44px。青绿、深色导航和卡片风格，标题“用量与费用/项目管理/报销记录”。筛选→指标→必要排除说明→申请表单→长预览；币种完整可见，容器滚动或换行，不缩字适配。

来源/协议细节放按需帮助；不向产品流程加入内部 epoch、迁移协议或助手旁白。成功提示短浮动，操作错误持续可见并进入当前弹窗。

## 6. 验证

运行 [前端质量检查](./quality-guidelines.md)。真实浏览器覆盖启动去重、手动成功/失败/needs_review、游标、目录归属、候选核对、占用失效、current/frozen 修订、提交/撤回/报销/作废重用、原包下载与退出。验证1440/1366/1280/430/375布局、CSV Excel 打开和 A4 打印。Store 测试不能替代界面请求或 DOM 验证。
