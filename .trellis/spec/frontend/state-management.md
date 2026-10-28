# 页面状态与请求

## 状态所有权

[app.js](../../../src/aha/web/app.js) 的单个 `state` 管本次页面状态。持久资料由服务器 Store 管，页面不另存一份报销账本。

| 状态 | 内容与使用方式 |
| --- | --- |
| csrf/today | 当前启动凭证和北京时间，由 status 初始化 |
| captures/capture/currentCaptureId/config | 资料快照、当前选中与项目配置 |
| analysis/tab/page/rows/total/selected | 当前分析、预览分页和选择；selected 是 Map |
| batches/batch | 报销列表和展开详情，变更后刷新 |
| pendingBatch | 本次保存的 request、batchId、signature、previewed，用于同内容重试 |
| revision/lifecycle | 打开弹窗的批次、版本、generation、分析或操作身份 |
| busy/noticeTimer/stopped | 串行操作、短成功提示计时与退出后的控件禁用 |

完整字段、权限和失效规则以 [页面契约](./local-web-contract.md) 为准。

## 请求与串行操作

`api(path, body?)` 统一 same-origin Cookie、JSON、X-AHA-CSRF 和安全错误。`run(label, action)` 在 busy 时不重复执行，禁用控件、展示忙碌状态，finally 恢复并调用 syncActions。异步入口复用 run，不在事件函数里另发不受控保存。

预检与重试身份来自 `prepareBatch` 的真实片段：

```javascript
const signature = JSON.stringify({payload, batchId});
const prior = state.pendingBatch;
const key = prior?.signature === signature ? prior.request.idempotency_key : crypto.randomUUID();
const request = {...payload, idempotency_key: key};
```

请求未变化时复用 key。丢失创建响应后应重试原保存，不强行用新的临时预览覆盖；后端在 Store 中持久化重放。内容变更必须生成新身份。页面刷新后的后端状态仍以 records 为准。

## 失效与修订主体

来源、元数据、分类/人工归属、筛选或占用改变后调用 invalidate，清空当前分析、pendingBatch、选择和旧表格，禁用保存，要求新预览。翻页保留跨页选择；切 tab、重新分析、失效或显式清除会清空选择。导出基于当前分析的完整范围，不受分页影响。

`api` 收到 analysis_expired/classification_changed/availability_changed/usage_claimed 时，还会清除打开的 current 修订弹窗的 analysis、替换提示并 syncActions；仅清主页面是不完整的。frozen 修订维持冻结依据；current 修订的独立 capture/project/date 变化后必须重新预览。

当前修订绑定 batchId、base_version、expected_generation，并调用专用 `/api/batches/{id}/analysis`。不能把主页面的新建预览借作排除自身占用的修订，也不能让新建请求使用修订豁免。批次权威失效时刷新列表并重新打开当前记录。

## 保存、下载与生命周期

saveBatch 先保存，再清理相应状态、刷新记录/预览，最后下载已保存版本；下载失败明确提示“记录已保存”，从报销记录重下原包。下载不能设置提交或已报销状态。

生命周期由服务端 `is_effective/lifecycle/generation/can_*` 决定；弹窗的原因和选中版本参与请求签名，原子处理在后端。前端状态不是抢占用量或释放占用的依据。

## 检查入口

[test_http.py](../../../tests/test_http.py) 覆盖过期预览、专用主体和持久重放，[test_batches.py](../../../tests/test_batches.py) 覆盖版本/占用结果。实际浏览器须额外保持修订弹窗打开，制造一次权威变化并核对禁保存，再更新预览保存；HTTP 测试不能单独证明 DOM 状态已正确清除。
