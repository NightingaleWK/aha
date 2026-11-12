# 项目关联接口合同（实施）

服务端复用现有 Cookie/CSRF/Host/Origin 和 AppError 边界。金额均为精确十进制字符串；数量为整数。所有读取只访问本地台账，所有应用均经原子事务重检和持久幂等重放。

## 读取

- `GET /api/project-associations`：返回 `{data_revision, classification_revision, claim_revision, summary, projects, groups}`。
  - `summary={detail_count,rollup_count,record_count,assigned_detail_count,unassigned_detail_count,unassigned_rollup_count,unassigned_record_count,unassigned_cost_usd,recoverable_sessions,recoverable_detail_count,directory_only_sessions,directory_only_detail_count,ambiguous_sessions}`。全局口径排除 suppressed，保留可用状态的区别供明细查看。
  - `projects=[{id,name,detail_count,rollup_count,record_count,total_cost_usd,available_cost_usd,claimed_cost_usd,pending_count,start_date,end_date}]`（包括零用量项目）；参考成本仅含 available/claimed 已核实成员，pending 单列；不能直接称为可报销金额。
  - `groups=[{reason,directory,session_count,detail_count,rollup_count,record_count,total_cost_usd,start_date,end_date}]`；reason 为 `recoverable`（唯一历史目录可匹配已有项目）、`directory_unbound`（有目录但没有项目规则）、`missing`（无依据）、`conflict`（多个历史依据或开放矛盾核对）。最多前 1,000 组；响应 `groups_truncated` 明确是否截断，不能冒称全量。
- `GET /api/project-associations/records?...`：返回 `{rows,next_cursor,has_more,...revisions}`。`rows` 含 `{record_key,kind,session_id,cwd,project_id,project_name,assignment_origin,date,model,record_count,total_cost_usd,reason}`，size 1–200，默认50；next_cursor 绑定筛选和修订。按 event_time/record_key keyset 分页。

记录读取与预览选择共用过滤字段：`project_id`（默认 `unassigned`，也可 `all` 或真实ID）、`start_date`/`end_date`（北京时间整天，可留空）、`directory`（精确目录组，非模糊推断）、`session_id`、`reason`（all/recoverable/directory_unbound/missing/conflict）。选择已分配历史作追溯操作时使用 project_id=all 或原项目ID。

## 预览

`POST /api/project-associations/preview`：

```json
{"action":"assign","project_id":"目标项目UUID","filters":{"project_id":"unassigned","directory":"/work/repo"},"keys":[],"session_ids":[],"bind_sessions":false}
```

- action 为 `assign`（人工分配）、`recover`（采用唯一历史目录，按当前规则恢复）、`reclassify`（显式按当前目录规则追溯重算）。
- keys/session_ids 非空时精确选择，二者互斥；均为空表示**全部符合 filters 的记录**，不是当前页。
- assign 要求真实目标 project_id；`bind_sessions=true` 时展开所选 detail 会话的全部现存明细，并建立未来持续默认；逐条既有有效人工例外保持优先，预览按展开后的范围计数。
- recover 可传 filters 或 session_ids；仅针对当前非 matched 且有唯一有效历史依据的会话，既匹配项目也包含只能恢复目录的会话；最多 1,000 个会话。本机已 matched 的普通待分配不在恢复集合，保持 directory_unbound 普通清单；其目标项目可由显式 reclassify 按当前规则确认。
- 预览不写真实业务表。返回 `{preview_id,action,summary,projects,warnings,...revisions}`；summary 含 `{selected_detail_count,selected_rollup_count,selected_record_count,total_cost_usd,changed_count,session_count,recovered_sessions,directory_only_sessions,manual_exceptions}`。projects 为按目标项目分组的预期成员和参考成本，含未改变项；实际改变数量单列 changed_count，不能将分组总量冒称增量。warnings 为可读字符串数组。
- 有界最大批量 100,000 条记录 / 1,000 会话，超限明确 `assignment_too_large`，提示缩小范围或分批。不将全体成员传到前端或保存在Python数组。

## 应用

`POST /api/project-associations/apply {preview_id,idempotency_key,reason}`：reason 非空；对 action/筛选/目标/修订与元数据候选摘要做权威重检。返回 `{applied:true,action,changed_count,recovered_sessions,summary,...revisions}`。

事务中流式选择、写逐条持久关系/会话默认/审核事件，重算受影响 scopes 和日/月统计后统一推进分类修订；事实内容、claims、coverage 和旧 ZIP 不改。响应丢失后同幂等 key 原样重放；不同请求复用 key 为 idempotency_conflict。预览过期为 `association_preview_expired`（409），不要先部分应用；未知 preview 为 `association_preview_required`。

现有 `/api/assignments` 继续支持 keys/session_ids；session_ids 现提供持续绑定，keys 仍是内容指纹人工例外。上述新接口用于带影响预览的批量和显式追溯。

## Store 门面

`association_status()`、`association_records(filters, cursor=None, size=50)`、`preview_associations(request)`、`apply_associations(preview_id, reason, idempotency_key)`；由新领域模块实现，Store 只作薄门面。前端在成功后失效分析及保存身份并刷新 config/ledger/关联状态。
