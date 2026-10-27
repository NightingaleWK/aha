# 实施门面（已冻结）

用户已批准实施。各模块遵循本契约，变更先通知主会话和依赖实现者。

## 纯占用算法：claims.py

```python
scope_key(member: dict) -> str
semantic_key(member: dict) -> str | None
evaluate(members: list[dict], snapshot: dict, exclude_batch_id: str | None = None) -> dict
```

成员沿用 analysis.members：kind、key、content_hash、date、model、app_type、data_source、provider_id、session_id、created_at、规范化Token、汇总request_count等。

snapshot 为 `{claim_revision:int, claims:[{member,owner}], legacy_holds:[{member,owner}]}`。owner 为 `{batch_id,number,version,status,lifecycle}`。可附 owners 映射，但消费者依赖上述两列表即可。

evaluate 返回 `{claim_revision:int, available_keys:list[str], excluded:list[{key,reason,owners:list[owner]}]}`。reason 为 identity / suspected_rebuild / cross_grain / rollup_scope / internal_overlap / legacy_hold。纯函数不算金额、不改成员。内部跨粒度冲突整组排除，其他独立明细不按同秒同Token合并。exclude 仅免本批次；调用方须验证真实修订主体。

## Store 方法

```python
claim_revision() -> int
claim_snapshot(exclude_batch_id=None) -> dict
create_batch(analysis, claim, idempotency_key, batch_id=None, *,
             expected_generation=None, expected_active_version=None,
             request_signature=None) -> dict
replay_create(idempotency_key, request_signature) -> dict | None
set_status(batch_id, version, status, expected_generation=None) -> dict
withdraw_batch(batch_id, expected_generation, reason, idempotency_key) -> dict
void_batch(batch_id, expected_generation, reason, idempotency_key) -> dict
resolve_legacy(batch_id, selected_version, expected_generation, reason, idempotency_key) -> dict
```

analysis 顶层有 claim_revision、availability_mode(`available`/`all`)、target_batch_id(新建为None，修订为实际ID)。新建/保存不只信mode，事务内重查成员；all与0成员拒绝。现有目录revision仍检查。生命周期保存与幂等优先于占用过期判断。

HTTP由服务层计算 `content_hash({path,body})` 作为 request_signature，先调用 replay_create 再访问分析缓存。新幂等记录持久化此签名，支持分析缓存清空/重启后的相同请求回取；签名不符或旧v1没有签名时明确冲突，不猜测。内部可信调用可省略签名，仍按规范业务内容检查幂等。

## 结果

保留原批次/版本字段，追加 `lifecycle(active/voided/legacy_review)`、`active_version:int|None`、`generation:int`、`is_effective:bool`、`can_edit/can_submit/can_reimburse/can_withdraw/can_void/can_resolve:bool`。

详情 `.revisions` 各项包含同一批次控制字段及其 is_effective；历史 can_edit/status/resolve 均false（resolve候选在legacy_review时可用）。`.status_history` 保留原金融状态历史；新增 `.claim_history` 为有效身份/撤回/作废/确认事件。作废不覆盖原revision.status，界面以 lifecycle 展示已作废。

generation 初始1，状态/有效版本/生命周期每次真实变化递增。claim_history 每项包含 `id,batch_id,version,action,reason,created_at,from_version,to_version,old_status,new_status`；action为 create/revise/status/withdraw/void/resolve/migrate。legacy_review header可作废，各候选可确认保留；UI只展示一次批次作废入口。

## 失效与不变量

Store 在 BEGIN IMMEDIATE 中查幂等、当前有效版、generation、claim_revision、成员冲突，再写版本/占用/事件。冲突和过期409。status普通路径只允许draft→submitted/reimbursed、submitted→reimbursed；撤回走独立带原因操作；reimbursed纠错只能作废。

原ZIP下载一直按旧路径/哈希返回，不因作废或被替代修改。作废是终态，旧创建/作废幂等重试返回已完成结果，不重新占用或释放其他owner。

analysis 内 availability 聚合对象由 API/data 实现者与主会话另行冻结；Store只依赖顶层身份/成员字段和重查实际成员。
