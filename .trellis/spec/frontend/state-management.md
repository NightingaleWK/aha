# 页面状态与请求

## 状态所有权

[app.js](../../../src/aha/web/app.js) 的 state 管本次页面，持久台账和报销事实由 Store 管。

| 状态 | 用途 |
| --- | --- |
| csrf/today/now | 本次启动凭证、北京时间日期与服务端秒级时刻 |
| ledger/sync/syncBusy/reconciliations | 本地统计、最近同步任务、同步控件、待核对事项 |
| syncGeneration/syncPreviewPending | 同步请求代际身份、忙操作结束后补更新同步引起的失效预览 |
| ledgerRequest/projectsRequest/reconciliationsRequest | 三类资料刷新各自的请求序号，拒绝旧成功与旧异常覆盖较新刷新 |
| config | 项目与分类 revision |
| analysis/tab/page/rows/total/cursor/nextCursor/cursors/selected | 分析、游标导航和跨页选择；page 仅为本地显示计数 |
| batches/batch | 报销列表和详情 |
| pendingBatch | 保存 request、signature、batchId、previewed，用于同内容重试 |
| revision/lifecycle | 弹窗的目标批次、版本、generation、分析及操作身份 |
| busy/noticeTimer/stopped | 普通串行操作、成功提示与退出状态 |
| filterGeneration/analysisRequest；revision.filterGeneration/request | 首页及修订的筛选与预览请求身份，阻止迟到响应改变新状态 |
| sourceBinding/bindingSelection/bindingRequest/dataDirectory | 当前来源绑定、待确认操作与请求身份、本机资料位置 |
| backupBusy/backupGeneration/backupJob/backupUpload/backupController | 备份或还原任务、分块上传、取消与迟到响应保护 |
| pendingBackupUploads | 状态恢复得到的遗留上传及显式清理入口 |
| associations/associationGeneration/associationSummaryRequest/associationRecordsRequest | 项目费用/待归属摘要、筛选代际及独立读请求身份 |
| associationSelected/associationAllFiltered/associationRows/associationCursor/associationCursors | 跨页逐条选择、全筛选意图及修订绑定分页；不保存全部筛选成员 |
| associationPreview/associationPreviewRequest | 预览身份、请求/重试签名、已应用但待刷新状态与关闭/迟到保护 |

## 请求与同步

api 统一凭证和安全错误。run 在 busy 时不重复执行并在 finally 恢复普通控件；同步使用独立 syncBusy，不锁住旧本地查询。只有 running job 继续轮询，completed/failed/needs_review 均终止；刷新从 status 恢复最近 job。失败或待核对不更新成功时间，不清掉旧台账。

来源卡优先级为同步中、失败、需要核对、历史成功、尚无成功。HTTP job.status与持久ledger.last_attempt.state须统一识别；last_sync仅为最近成功，不能用于推断最近尝试成功。初始化先恢复最新job再首次渲染，缺少job时采用last_attempt。失败时说明“当前显示已保存的本地数据”并独立保留上次成功时间；needs_review可能已保存新增事实，不能说当前资料就是上次成功快照。无成功时说明当前统计不代表实际用量，错误原因持续可见。重试立即隐藏旧失败，成功/待核对后更新真实终态；失败不禁用旧资料查询。

已知同步终态与后续页面刷新结果分开：刷新断线不得覆盖来源失败原因、把已完成/待核对改为同步失败，或让旧任务finally清掉新任务busy。同步代际保护覆盖所有迟到成功/错误/finally。初始化普通请求失败时running watcher仍可结束；旧初始化不得重跑startup同步或覆盖用户的新任务/新分析。

ledger/projects/reconciliations刷新同时校验各自请求序号和调用方同步代际，过时成功与异常均不提交状态。completed/needs_review一到达即使旧预览失效，页面刷新断线也不能保留旧保存身份；failed保留可用的旧预览。同步完成与忙操作交错时，待更新标记由run结束后消费，重新查询当前筛选，不能补发来源同步。

页面回归须覆盖有/无历史失败、持久state字段、HTTP status字段、刷新、重试中、失败恢复成功和needs_review；真实浏览器检查提示可读，不能只断言JS字符串。同步失败后的零条统计不能被说明成来源已更新或真实零消耗。

prepareBatch 对 `{payload,batchId}` 计算签名，内容未变沿用原幂等 key，内容改变才换 key。丢失响应后重试原请求，Store 持久重放。页面不存第二套占用账。

## 失效与修订

筛选、分类、占用或数据 revision 改变后 invalidate 清分析、pendingBatch、选择和表格。相同标签翻页保留选择，切标签/重分析清选择。total=null 的聚合页仍显示本页数量和 next_cursor，不隐藏分页或猜测全量。

权威失效错误也清打开的 current 修订 analysis 并禁保存；frozen 修订继续绑定原版本。current 必须使用专用批次分析、base_version/expected_generation；主页面不能借自身占用豁免新建。

时间草稿取消不调用 invalidate；确认或其他真实筛选变化才使旧预览失效。跟随当前时刻只在新分析时由服务端取钟，保存沿用原 analysis_id；首页与当前修订的范围状态分别管理。

异步详情请求必须在成功、409和断连错误三个路径都校验请求身份。`api(path,body,isCurrent)` 在执行权威失效的全局 invalidate 前检查谓词，renderPreview 的成功和 catch 路径也检查当前身份；仅在接收成功结果后丢弃旧响应不够。过时错误不能清掉较新预览；当前请求的权威失效仍须清首页/current修订/待保存身份。

## 保存与生命周期

先保存、刷新记录，再下载指定版本；下载失败显示已保存。动作由 is_effective/lifecycle/generation/can_* 决定。撤回保留占用，作废释放，旧版本原包仍可下载。前端提示不能代替写事务权威重检。完整接口和浏览器场景见 [页面契约](./local-web-contract.md)。

## 换机确认、完整备份与历史入口

来源绑定使用独立bindingRequest，关闭弹窗使旧请求失效；确认成功后按原请求继续有限同步，不能把旧来源确认当事实候选全部接受。旧历史仍可查。恢复与来源协议见[恢复合同](../backend/recovery-and-device-contract.md)。

备份/上传/还原的backupGeneration独立于普通busy和同步代际。取消会推进代际并中断fetch；若旧创建请求稍后返回job/upload id，应立即取消对应后端资源，不能留下隐形上传或让旧finally清新任务busy。刷新后从status恢复transfer和未完成上传，提供清理入口；关闭弹窗不等于退出程序，任务仍可继续查看。

核对提交成功先失效旧分析与保存身份，再按当前原时间意图重查；过时核对结果不能替换用户新筛选。空范围提示与台账全局日期分别呈现，“查看全部历史”明确切到全部项目/全部用量并禁保存，报销需切回可用模式；不得把源失败解释成真实零消耗。

## 归属工作清单与批量提交

打开项目页加载费用/归属摘要和记录清单。筛选变化清旧选择/预览并推进associationGeneration；同筛选翻页可保留逐条选择，全筛选只保存选择意图，由服务端有界处理全部成员。动态项目选项保留真实value并AhaForms.sync，不闭包捕获旧option。

预览成功、失败、409和断连都检查请求身份；关闭弹窗或更换目标让旧响应失效。绑定/批量成功先失效分析及保存身份，再刷新config/ledger/归属摘要和当前筛选；同步成功也应使旧归属预览失效。只因刷新失败不能误报提交失败；operation.applied保留已提交身份，按钮改“刷新已保存结果”，重试不重复写入。响应丢失沿同preview/reason的原幂等key重试，明确过期则重新预览。

不能以busy结束的旧finally清新状态；对话框错误留在当前弹窗，Escape关闭并还原触发焦点。真实浏览器覆盖超过一页的筛选全选、从一条展开整会话、未来继承及逐条例外，不能仅通过payload字符串断言宣称成功。

新建/编辑项目API成功后立即保存服务端返回project.id，并使旧分析/保存身份及归属预览失效，再做依赖刷新。刷新失败明确“项目已保存”，保留已保存ID，重试不能再次创建同名新项目；项目/关联摘要两种刷新失败都要回归。metadata_scan_truncated与仅分组数超过1000分别说明：部分会话未检查时不显示伪造缺失分组，可缩小到具体会话继续，不能暗示待归属总量也被丢弃。

## 项目目录整体编辑

projectEditor/projectGeneration持有项目草稿、请求序号、服务端预览、稳定幂等key及applied/submitting状态。使用POST /api/projects/preview和/apply；预览不写配置，确认一次原子保存目录及历史，不能在取消时留下半绑定。目录清单包含其他项目已绑定路径并说明选中后整体转移；影响页面显示全量目录、原项目→目标项目、费用、已占用/待核对和未确定范围，金额不在前端求和。

更换草稿、目标、关闭或同步成功使旧预览失效；成功、409、断连及finally都检查当前编辑身份，旧响应不能覆盖新草稿。提交后的refreshProjects/refreshLedger/refreshAssociations都必须接收并继续传递调用方身份；调用方已过时时，不清新选择，也不再启动归属查询。提交未知结果使用原preview_id与幂等key重试；已提交但刷新失败改为“刷新已保存结果”，仅重查项目/ledger/归属结果，禁止再次创建同名项目。

项目卡根据directory_managed显示管理目录或确认目录关联。普通流程不呈现记录复选框／整个会话开关；高级无目录资料不能给已确认目录写相反项目例外。旧项目元信息保存不自动采用整体模式，明确关联确认才改变历史。键盘、Escape、关闭焦点、禁用状态和AhaForms.sync按组件合同验证。
