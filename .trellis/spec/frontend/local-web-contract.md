# 本机页面与 HTTP 契约

## 1. 范围与入口

页面由 [server.py](../../../src/aha/server.py) 提供，使用内置 HTML/CSS/JavaScript，没有前端构建器或外部资源。修改 `web/` 或请求字段前同时阅读 [后端契约](../backend/usage-evidence-contract.md)。产品文案使用简体中文。

页面查询本地台账；程序就绪后按已确认来源启动一次同步，用户可手动再同步，服务按本次生命周期去重。刷新、重复双击重开和托盘打开不重跑已有启动同步；关闭标签不会退出进程。页面与 Windows 托盘的“退出程序”共用关闭流程。没有周期轮询来源、关闭后采集或开机启动。同步任务运行期间的 job 状态轮询不属于周期采集；实例与退出的后端边界见 [运行契约](../backend/runtime-lifecycle-contract.md)。

## 2. HTTP 入口

| 接口 | 契约摘要 |
| --- | --- |
| `GET /api/status` | 本次启动凭证、日期、北京时间秒级 now、逐端来源、启动与最近同步任务 |
| `GET /api/instance` | 认证后的轻量实例身份/状态，供启动器复用，不读台账、不返回业务信息 |
| `GET /api/ledger` | 本地记录数、覆盖、成功同步时间、最近尝试和目录依据 |
| `GET /api/codex-sources` | `sources`、`windows_default`、`distributions` 和 `history_default_since` |
| `POST /api/codex-sources` | `{kind,root,distribution?,since?}`。校验后确认并返回 `sources`，不会隐式同步 |
| `POST /api/sync` | `{trigger?}`，值为 `startup` 或 `manual`，默认手动，返回异步 job |
| `GET /api/sync/{job}` | `running/completed/failed/needs_review/cancelled` 与逐端结果，只有 running 继续轮询 |
| `POST /api/sync/{job}/cancel` | 请求有限后台作业取消，轮询终态确认结果 |
| `POST /api/session-metadata` | 使用已确认本机 Codex 根刷新旧台账的目录依据 |
| `GET /api/projects` | 项目配置与分类 revision |
| `POST /api/projects/preview`、`/api/projects/apply` | 目录草稿→整体影响→一次确认，原子保存配置和历史，见[目录整体合同](../backend/project-association-contract.md#8-已确认目录的整体归属合同) |
| `POST /api/projects`、`/api/projects/{id}` | 旧兼容路径，目录变更须先预览确认；仅允许不改目录的元信息更新 |
| `POST /api/assignments` | `project_id` 加 keys 或 session_ids；rollup 按整条记录处理 |
| `GET /api/project-associations`、`/records` | 项目费用/待归属分组及修订绑定的keyset记录清单 |
| `POST /api/project-associations/preview`、`/apply` | 全筛选/逐条/整会话的归属影响预览与原子幂等应用；协议见[项目归属合同](../backend/project-association-contract.md) |
| `GET /api/reconciliations/summary` | `{total}`，台账中待处理的核对事项数 |
| `GET /api/reconciliations/page` | `type/source_id/start_date/end_date/eligibility/cursor/size`，返回 `{cases,total,eligible_count,next_cursor,version,sources}` |
| `GET /api/reconciliations/{id}` | `{case}`，按需查看完整新旧证据、选择和 generation |
| `POST /api/reconciliations/batch-preview` | `{filters,ids?,version}`，返回 `{count,candidate_count,current_cost_usd,candidate_cost_usd,preview_hash}`，省略 ids 表示跨页全选筛选范围内的可批量项，两个精确金额字符串仅汇总采用候选的事项 |
| `POST /api/reconciliations/batch` | `{filters,ids?,preview_hash,reason,idempotency_key}`，返回 `{resolved_count,open_count,...revisions}` |
| `GET /api/reconciliations` | 兼容入口，返回 `{cases}` |
| `POST /api/reconciliations/{id}` | `choice/reason/expected_generation/idempotency_key`，按实际候选确认 |
| `POST /api/analysis` | project、time_range意图或旧起止日期（二者互斥）、`availability_mode=available|all`；只查本地库 |
| `GET /api/analysis/{id}/details` | `kind=detail|rollup|daily|models`、cursor、size1–200 |
| `POST /api/batches/{id}/analysis` | base_version、expected_generation 与当前筛选，绑定目标修订主体 |
| `POST /api/batches/preview` | analysis 或有效冻结版本加 claim，返回阻断与占用信息 |
| `POST /api/batches` | analysis/claim/idempotency_key，保存冻结草稿 |
| `GET /api/batches`、`/api/batches/{id}` | 报销列表、版本、生命周期与当前差异数 |
| `POST /api/batches/{id}/revisions` | base_version/expected_generation/claim/idempotency_key，按需传 analysis_id |
| `POST /api/batches/{id}/revisions/{n}/status` | status、expected_generation |
| `POST /api/batches/{id}/withdraw`、`/void` | reason、expected_generation、idempotency_key |
| `GET /api/batches/{id}/revisions/{n}/download` | 流式返回指定版本原 ZIP |
| `POST /api/shutdown` | 本机认证后接受退出请求；页面显示正在退出，不将 HTTP 成功等同全部资源已释放 |

待核对分页的 `eligibility` 为 `all/batch/manual`。开始和结束日期均按北京时间日历日包含，默认每页 50 项，size 允许 1–200。游标和预览绑定当前资料版本。后端权威资格和事务见 [批量核对合同](../backend/usage-evidence-contract.md#分页核对与批量确认同一消费)。

请求字段的精确允许值由服务端边界与领域函数验证。页面不再发送 capture_id、旧分页 page 或旧版本消解请求。

## 3. 状态、分页与同步

`api()` 统一 same-origin Cookie、JSON 与 X-AHA-CSRF；Cookie 按端口命名。启动 URL 与 runtime 凭证不得进入业务链接、日志或导出。

同步与普通操作分别使用 syncBusy 与 busy。本地查询在后台读取期间继续可用。job 的 `sources` 逐端报告本次尝试，运行前保留绑定及先前成功时间。任一端完成发布即使另一个端随后失败或取消，页面也要失效旧预览。页面刷新时，最近任务的来源种类、根目录、发行版和起日均须匹配当前绑定。配置改变后保留台账和对应来源的历史结果，忽略旧绑定的迟到轮询。

每端 `sources` 有 `kind`、`root`、`distribution`、`since`、`configured` 和 `status`。成功时间为 `last_success_at`，当前 `result` 可含 `coverage_from`、`coverage_through`、`issues` 与新增/核对计数。日期采用北京时间，失败仍可在 `last_success_range` 查看最近成功范围。

设置时 `kind` 为 `windows` 或 `wsl`，WSL 必须明确选择发行版，空根按当前环境发现。起日 `since` 是北京时间 `YYYY-MM-DD`（含该日），空字符串读取全部历史。旧台账初次确认默认使用最后一个已有历史日，修改起日时重扫并按稳定事件去重。设置弹窗、发现、保存与同步互有独立的请求身份。

明细、历史汇总、每日和模型使用游标，固定每页50条；游标绑定分析 revision 与筛选。total 可能为 null，此时显示本页数量并依据 next_cursor 导航，不猜总页数。切换标签、筛选或重新分析清选择；同标签翻页允许跨页勾选。导出使用完整分析范围，不只导出可见页。

来源、目录规则、人工归属、筛选、占用或数据 revision 改变后清当前预览、选择和保存身份。服务端返回 analysis_expired/data_changed/classification_changed/availability_changed/usage_claimed 等权威失效时，也须清打开的 current 修订分析并禁保存。frozen 修订仍以原冻结依据为准。

时间面板支持快捷范围、日历和分钟输入；取消保留原预览，确认直接更新。页面范围、报销列表/详情和材料展示服务端实际解析结果。部分日历史汇总单独提示“统计不完整”，不伪造小时排除费用，不等同“待核对”；提供“改查整天”，有合法确定成员仍可保存。旧冻结完整性缺失显示未知，不能标为完整。精确合同见 [时间范围](../backend/time-range-contract.md)。

## 4. 保存、冻结与生命周期

- 后端负责金额与合计，页面只展示十进制字符串，不从分页或 JavaScript 浮点数求财务总额。
- available 用于新建，all 只读；零可用和待核对不得新建。显示排除原因及对应记录。
- current 修订必须通过目标批次专用分析获得自身占用豁免；主页面不能借用该主体。base_version/generation 防止旧弹窗覆盖新状态。
- 未改变的请求复用幂等 key；改变 payload 重新生成。保存后再下载；下载失败说明“记录已保存”，从报销记录重下原版本。
- 仅有效草稿可改。已提交可带原因撤回且保留占用；已报销纠错通过作废再新建。作废释放占用且为终态；旧版本与作废版本仍可下载原包。
- 用途/金额说明各最多4000字符；金额可空或零，填写须依据，币种 CNY/USD。参考 USD 成本与申请金额分开。新建成功清用途、金额和说明。
- 核对必须展示实际候选和所需原因，不自动把较晚导入的备份当最新事实，不补造差额明细。
- 单笔、批量核对、项目归属及撤回／作废的说明只在新确认表单打开时预填「已人工确认」，清空后以同一文字作为占位提示。当前值可编辑，显式确认提交实际文字。同一操作的失败和重试保留草稿。
- 用户/来源文字通过 textContent/DOM 插入，不拼接 innerHTML。

## 5. 可读性与产品表达

正文/输入16px，表格/按钮15px，标签/表头14px，次要至少13px；主要控件约44px。青绿、深色导航和卡片风格，标题“用量与费用/项目管理/报销记录”。筛选→指标→必要排除说明→申请表单→长预览；币种完整可见，容器滚动或换行，不缩字适配。

来源/协议细节放按需帮助；不向产品流程加入内部 epoch、迁移协议或助手旁白。成功提示短浮动，操作错误持续可见并进入当前弹窗。

项目页首先回答项目费用与已纳入目录。常用流程为新建/管理项目目录→查看完整影响→确认保存并关联，不提供逐条挑选、跨页全选或整会话开关；旧项目通过确认目录关联采用新模式，目录内旧人工跨项目归属在预览后整体迁入。无目录旧资料处理收纳高级区域。兼容旧模式批量仍须明确“当前页/所选记录/全部筛选/整个会话及未来”范围；有效关系保存在aha中。查看全部费用仍是all只读口径，申请报销切回可用用量。同期未归属单独说明，不能混算成某项目或假称全部已完成；覆盖与冻结合同见[项目归属合同](../backend/project-association-contract.md)。

## 6. 验证

运行 [前端质量检查](./quality-guidelines.md)。真实浏览器覆盖启动去重、手动成功/失败/needs_review、游标、目录归属、候选核对、占用失效、current/frozen 修订、提交/撤回/报销/作废重用、原包下载与退出。验证1440/1366/1280/430/375布局、CSV Excel 打开和 A4 打印。Store 测试不能替代界面请求或 DOM 验证。

## 换机与完整恢复入口

完整备份/分块还原、本机来源绑定及独立资料目录的签名、限额和错误以[恢复合同](../backend/recovery-and-device-contract.md)为准。本地界面显示资料位置，完整恢复包为私有资料，费用分享使用独立报销原包。恢复结果提供独立台账打开方式，明确默认双击仍打开原默认目录；不在线换当前库。
