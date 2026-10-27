# 核算与 HTTP 实施接口

## 核算

`analyze` 保留原位置参数，追加 keyword：`claim_snapshot=None, availability_mode='all', target_batch_id=None, expected_generation=None, expected_active_version=None`。纯核算默认 all 兼容历史检查；HTTP 默认 available 且必须取得 Store 当前 snapshot。

顶层追加 `claim_revision`、`availability_mode`、`target_batch_id`、`expected_generation`、`expected_active_version`。所有返回 summary/daily/models/details/rollups/members 使用当前模式实际成员；可用过滤在聚合前完成。

`availability` 固定字段：

```text
{
  mode: 'available'|'all', claim_revision: int,
  matched_summary: 原筛选全部成员的标准summary,
  available_summary: 可用成员标准summary,
  excluded_summary: 被排除成员标准summary,
  excluded_groups: [{reason,message,row_count,record_count,detail_count,
                     rollup_record_count,total_cost_usd,owners:[owner]}]
}
```

标准 summary 保留原精确金额/Token/粒度字段。owner 沿 Store 协议：batch_id/number/version/status/lifecycle。reason 来自 claims.evaluate：identity、suspected_rebuild、cross_grain、rollup_scope、internal_overlap、legacy_hold。

all 视图的每行追加 `usage_state=available|claimed|ambiguous`、`usage_owners`、`usage_reason`；available 视图只含可用行。内部覆盖组及疑似/旧待核对归 ambiguous；明确别的批次身份占用归 claimed。客户端不自行加总。

## 路由与请求

- `POST /api/analysis`：原 capture/date/project/classification 字段，追加 `availability_mode`（默认 available）。不接受 target/exclude 批次，避免新建借用豁免。
- `POST /api/batches/{id}/analysis`：同上筛选 + `base_version` 与 `expected_generation`；仅当前有效草稿，强制 available。返回绑定目标批次的分析，默认排除本批次自己的占用。
- `POST /api/batches/preview`：新建传 analysis_id；修订传 batch_id、expected_generation、base_version，以及 analysis_id 或仅沿用冻结有效版本。返回 `{overlaps,conflicts,blocking}`，不支持确认继续。
- `POST /api/batches`：`{analysis_id,claim,idempotency_key}`，仅新建 available 主体。
- `POST /api/batches/{id}/revisions`：`{base_version,expected_generation,claim,idempotency_key,analysis_id?}`。有 analysis_id 必须是本批次修订预览；省略则沿用当前有效版本冻结用量。
- `POST /api/batches/{id}/revisions/{n}/status`：`{status,expected_generation}`，新生命周期由Store检查。
- `POST /api/batches/{id}/withdraw|void`：`{reason,expected_generation,idempotency_key}`。
- `POST /api/batches/{id}/resolve`：同上 + `selected_version`。

`base_version/expected_generation/selected_version` 其中 generation 接受非负整数，版本接受正整数；明确拒绝 bool；原因最多4000字符，操作幂等键至少16字符。Store 独占与版本结果字段沿 `implementation-api.md`。

## 预览、缓存和幂等

分页 GET 必须验证来源generation、项目revision与claim_revision。保存只向Store传原冻结成员，不在保存时静默刷新、减记录或改金额；Store在事务内重检。HTTP成功创建后的同请求重试必须先走幂等结果，再检查占用过期，旧创建请求不得复活已作废记录。

已存原ZIP下载保持原路由和字节。真实部署的Host/Origin/CSRF/JSON及原件隐私边界不改变。

HTTP 保存前先用 content_hash({path, body}) 调 Store.replay_create(key, signature)，命中直接返回已保存版本当前生效关系；未命中才取分析缓存并传 request_signature 给 create_batch。签名不含Cookie/CSRF，所以来源切换、清缓存、重启及作废后重试均可恢复原结果，不会复活。相同key不同body明确冲突。
