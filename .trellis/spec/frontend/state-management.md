# 页面状态与请求

## 状态所有权

[app.js](../../../src/aha/web/app.js) 的 state 管本次页面，持久台账和报销事实由 Store 管。

| 状态 | 用途 |
| --- | --- |
| csrf/today/now | 本次启动凭证、北京时间日期与服务端秒级时刻 |
| ledger/sync/syncBusy/reconciliations | 本地统计、最近同步任务、同步控件、待核对事项 |
| config | 项目与分类 revision |
| analysis/tab/page/rows/total/cursor/nextCursor/cursors/selected | 分析、游标导航和跨页选择；page 仅为本地显示计数 |
| batches/batch | 报销列表和详情 |
| pendingBatch | 保存 request、signature、batchId、previewed，用于同内容重试 |
| revision/lifecycle | 弹窗的目标批次、版本、generation、分析及操作身份 |
| busy/noticeTimer/stopped | 普通串行操作、成功提示与退出状态 |
| filterGeneration/analysisRequest；revision.filterGeneration/request | 首页及修订的筛选与预览请求身份，阻止迟到响应改变新状态 |

## 请求与同步

api 统一凭证和安全错误。run 在 busy 时不重复执行并在 finally 恢复普通控件；同步使用独立 syncBusy，不锁住旧本地查询。只有 running job 继续轮询，completed/failed/needs_review 均终止；刷新从 status 恢复最近 job。失败或待核对不更新成功时间，不清掉旧台账。

prepareBatch 对 `{payload,batchId}` 计算签名，内容未变沿用原幂等 key，内容改变才换 key。丢失响应后重试原请求，Store 持久重放。页面不存第二套占用账。

## 失效与修订

筛选、分类、占用或数据 revision 改变后 invalidate 清分析、pendingBatch、选择和表格。相同标签翻页保留选择，切标签/重分析清选择。total=null 的聚合页仍显示本页数量和 next_cursor，不隐藏分页或猜测全量。

权威失效错误也清打开的 current 修订 analysis 并禁保存；frozen 修订继续绑定原版本。current 必须使用专用批次分析、base_version/expected_generation；主页面不能借自身占用豁免新建。

时间草稿取消不调用 invalidate；确认或其他真实筛选变化才使旧预览失效。跟随当前时刻只在新分析时由服务端取钟，保存沿用原 analysis_id；首页与当前修订的范围状态分别管理。

异步详情请求必须在成功、409和断连错误三个路径都校验请求身份。`api(path,body,isCurrent)` 在执行权威失效的全局 invalidate 前检查谓词，renderPreview 的成功和 catch 路径也检查当前身份；仅在接收成功结果后丢弃旧响应不够。过时错误不能清掉较新预览；当前请求的权威失效仍须清首页/current修订/待保存身份。

## 保存与生命周期

先保存、刷新记录，再下载指定版本；下载失败显示已保存。动作由 is_effective/lifecycle/generation/can_* 决定。撤回保留占用，作废释放，旧版本原包仍可下载。前端提示不能代替写事务权威重检。完整接口和浏览器场景见 [页面契约](./local-web-contract.md)。
