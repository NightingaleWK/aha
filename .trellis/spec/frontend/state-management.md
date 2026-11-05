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
