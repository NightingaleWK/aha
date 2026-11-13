# 逐笔归属、项目费用与换机连续性

## 1. 范围与目标

修改项目、记录归属、目录依据、批量分配、应用库升级或费用覆盖说明时阅读。aha 的主流程为**消费留存 → 逐笔归属 → 项目核算 → 冻结报销证据**。每条可统计消费最多有一个生效项目，未确定项是必须便于处理的待办；目录发现率不是完成指标。

同一时间、粒度和可用性口径下，各项目 + 未归属 = 全部可统计用量，金额和 Token 精确守恒；已被明细替代的 suppressed 日汇总不重复相加。项目合计必须可追溯到实际成员，不从前端可见页求和。

## 2. 签名与所有者

```python
Store.preview_project_binding(draft)
Store.apply_project_binding(preview_id, idempotency_key)
Store.association_status()
Store.association_records(filters, *, cursor=None, size=50)
Store.preview_associations(request)
Store.apply_associations(preview_id, reason, idempotency_key)
Store.assign_keys(keys, project_id) / Store.assign_sessions(session_ids, project_id)
```

- `directory_bindings.py`：目录整体保存草稿、归属影响、配置/历史一次确认和原子审核。
- `associations.py`：本地工作清单、筛选、旧模式影响预览、原子应用和审核。
- `project_links.py`：已接受逐条关系、会话默认及目录匹配的共享规则。
- `projects.py`：项目 UUID/目录配置、内容指纹人工例外；Store 保持薄门面。
- `ledger.py`：归属查询投影、可用性和精确日/月统计；`queries/batches/evidence` 负责项目选择与冻结。
- 应用 schema4 新增 `record_project_links`、`session_project_bindings`、`project_assignment_events`；schema3 DDL 独立保留为正式兼容定义。

## 3. 数据与请求合同

### 持久关系

先判断已明确确认的目录整体规则：命中已纳管目录时目录所有者优先于旧人工 override、持久关系及会话默认，详见第8节。未纳管旧模式下，有效记录 override（内容指纹匹配）优先于已接受逐条关系；已有关系不被同步、找不到日志或普通配置草稿清除。新成员可使用会话默认/唯一目录规则，第一次分类即留持久基线。`record_project_links.project_id=NULL` 是待归属基线，不代表完成或已确定项目，避免其他 scope 刷新把旧未归属记录无提示认领。

目录和会话是识别/批量辅助，业务身份沿用 aha 项目 UUID 与 canonical 消费 key。已有人工 override 不根据数量推断成整会话意图；费用内容修订仍走原核对和指纹规则。显式采用相反目录候选可重新判断其自动目录关系；未纳管旧模式保留有效逐条例外，命中已确认目录整体规则时按第8节统一归属。

确认两key为同一消费时，双方不同非空项目仍需核对；只有一方已有项目时保留唯一已知关系到canonical，记录identity_confirmation依据/审计，不将候选override原内容hash硬套到canonical，也不跳过费用修订或占用核对。清除逐条例外和解除整会话未来默认是两种不同操作，文案和权威写入必须对应。

旧模式普通保存不回算已确认历史；新的目录整体保存流程必须预览影响并明确确认，原子绑定目录并统一已有成员，不能复用保留逐条例外的旧批量动作。旧资料纠正历史仍可用独立预览/应用；整会话分配展开全部现存非 suppressed 明细并使后续新增明细继承，预览展示范围和有效人工例外。日汇总无会话，只能按完整留存行分配，不拆分或虚构逐笔成员。

### 工作清单与 API

所有接口沿用 Cookie/Host/Origin/CSRF：

| 接口 | 输入与结果 |
| --- | --- |
| `POST /api/projects/preview` | `{project_id?,name,description,directories}`，一致快照预览目录整体保存，含零记录目录 |
| `POST /api/projects/apply` | `{preview_id,idempotency_key}`，原子保存项目、目录所有权、模式和全部有依据历史 |
| `GET /api/project-associations` | 三修订号、summary、projects、按原因/目录分组；项目参考成本为已核实 available+claimed，pending 单列 |
| `GET /api/project-associations/records` | `project_id/start_date/end_date/directory/session_id/reason`、cursor、size1–200；event_time/record_key keyset |
| `POST /api/project-associations/preview` | `action=assign|recover|reclassify`、filters、keys 或 session_ids；assign 需目标 project_id，可 bind_sessions |
| `POST /api/project-associations/apply` | `preview_id/reason/idempotency_key`；原子应用并返回实际计数与新修订 |

keys/session_ids 互斥；都空表示全部符合 filters 的成员，不是当前页。目录过滤是已保存的精确目录组，不做名称相似猜测。最大批量 100,000 条记录、1,000 会话；元数据域最多检查20,000会话，分组最多返回1,000组，截断必须明确提示。

目录/原因过滤的记录读取和所有依赖这些依据的预览均要求完整元数据；不足时拒绝而非把字典外当missing。明确指定会话/记录可先聚焦其依据；普通分页补查当前页会话。状态分组省略未检查会话并标部分，全局待归属统计仍完整保留，不能将未检查当作已处理或实际缺日志。

预览只保留规范请求、三修订号与成员/元数据/规则摘要，不保存全体事实数组；最多24份，10分钟过期。提交在同一写事务中重查并冻结临时关系选择，更新关联、审核事件及受影响日/月投影，再推进分类 revision。响应丢失先查持久幂等重放，不因预览过期或进程重启重复应用。原事实/消费版本、claims、coverage 决策及旧原包保持。

### 历史目录恢复

仅当前非 matched、且保留唯一有效历史 `matched` 绝对目录的会话可恢复。检查版本内容哈希、规范化后是否唯一以及开放/曾明确否决的候选；多个有效目录不能简单取最新。恢复当前有效目录后按现有项目规则重建，并明确不是从未留存的旧项目快照。

新机已经 matched 但未绑项目的记录留在普通待归属集合，不混入“恢复旧目录”数量。唯一历史目录无项目规则时只恢复依据，仍待分配。一般工作/日报/临时目录不自动归某项目；无证据项可以批量人工确认。

### 项目统计与冻结说明

`analysis.assignment_coverage` 独立于原 `summary_complete`，后者继续表达时间粒度/业务核对。覆盖说明按同一期间和 available/all/目标占用豁免口径聚合：未归属 detail 行数、rollup 行数、代表请求量及精确金额；零代表量的未归属 rollup 仍属于未完成。

页面可显示待归属金额。新分享材料仅带覆盖状态/计数，不能带未归属金额、其他项目、目录或完整未归属明细。确定项目成员仍可正常报销，不因同期其他记录未归属而全局阻断。

覆盖对象跟随当次成功预览冻结，贯通 batch/详情/current/frozen/manifest/HTML。当前修订即使成员 business_hash 未变，只要完整规范化覆盖对象变化也需生成新版本；真正无变化仍复用。成员 identity/hash 算法保持。旧 frozen 缺字段为 null/未知，不能按当前库补；重下载旧 ZIP 仍为原字节。

### 升级与完整恢复

Store 打开 schema3 前先由只读一致事务生成 `backups/before-schema4-*.aha-backup`，校验原结构与原包成功后才进入迁移事务/修改日志模式。迁移保留原事实、当前归属/统计、指纹人工覆盖、占用及材料，新增有依据的基线关系，失败完整回滚。

备份分别按真实 schema3/4 的生产 DDL 校验表/字段/索引/触发器；manifest版本必须匹配DB版本。旧 schema3 完整包先独立校验，在新恢复 staging 受控迁移，原归档和历史包不改。schema1/2和未知版本仍拒绝，不误用试用资料重建。内部用量投影仍为23，应用库版本读 SCHEMA_VERSION，旧冻结值不回填。

## 4. 校验与错误矩阵

| 场景 | 结果 |
| --- | --- |
| 无效筛选/日期/原因、keys和session_ids同时指定 | invalid_assignment_filter / invalid_assignment，业务不变 |
| 超过记录/会话上限 | assignment_too_large，明确缩小或分批，不只处理可见页 |
| 目录/原因判断所需元数据未完整检查 | assignment_metadata_limit，409；精确聚焦或缩小会话，不将字典外当missing或误清原归属 |
| 游标依赖筛选或修订变化 | invalid_cursor，重新查询 |
| 预览未知/进程重启且无已提交重放 | association_preview_required |
| 时间过期、三修订号或成员/依据摘要变化 | association_preview_expired，409，无部分应用 |
| 同幂等 key 不同请求 | idempotency_conflict，已提交同请求原样重放 |
| 多历史目录/无依据/曾否决 | 保持待归属/需核对，不按时间或名称猜测 |
| schema3 结构/包损坏、升级失败 | 安全拒绝/事务回滚，原资料与恢复副本保留 |

## 5. 正常、基础、错误场景

- 正常：旧日志已无，留存历史目录可预览恢复；确认后项目费用可下钻到记录，再换机/刷新仍保留。
- 基础：没有目录证据的记录显示待办，可按筛选全量分配；会话可持续默认并保留逐条例外。
- 错误：把找不到文件当成业务归属无效、只恢复目录不核对项目合计、保存新规则顺带改历史、批量只处理当前页、覆盖说明改变却返回旧版本。

## 6. 必需验证

- `test_associations`：旧missing与本机matched无规则混合、唯一/多候选、全筛选80条跨页、整会话展开与未来继承、例外优先、普通保存与显式追溯、失效/回滚/幂等、汇总完整粒度与守恒。
- `test_assignment_migration/test_backup/test_migrations`：独立schema3夹具、包含WAL/原包的保护副本、成功迁移/坏DDL拒绝/失败回滚、旧包新目录恢复及归档SHA不变。
- `test_assignment_coverage/test_batches/test_time_ranges`：项目+未归属精确守恒、大整数/极小金额、部分日、目标豁免、零代表量rollup、新覆盖修订、真正no-op、旧unknown/原ZIP。
- `test_http/web_state`与原生浏览器：真实请求、动态项目、跨页/整会话、关闭/迟到成功409断连、已保存刷新失败重试、键盘焦点与窄窗口；Directory/OneFile与真实一致副本分别留证。
- 真实资料回归必须核对“有效项目归属数量/金额与逐笔关系”，不能只证明与接续前一样；接续前本来就失效的目录也必须被识别并恢复。

## 7. 错误与正确做法

```python
# 错误：本机扫描不到旧文件，就覆盖有效业务关系；或只改当前页。
session.cwd = observed_cwd  # None
assign(page_rows, project_id)

# 正确：本地依据与业务关系独立，选择/影响先预览，再权威重检应用。
preview = store.preview_associations({
    "action": "assign", "project_id": target,
    "filters": {"project_id": "unassigned", "directory": directory},
})  # keys/session_ids为空表示整个筛选，服务端有界流式选择
store.apply_associations(preview["preview_id"], reason, idempotency_key)
```

## 8. 已确认目录的整体归属合同

### 范围与决定

用户已明确一个aha项目汇集多个实际目录／Codex项目，目录内记录全部使用，不逐条排除。确认前展示影响，旧人工跨项目记录也统一迁入。模式只在明确确认后启用，升级和启动不能顺带转换旧项目。缺日志、换机或停用目录不得撤销已确认历史。

### 签名与数据合同

`Store.preview_project_binding(draft)`、`Store.apply_project_binding(preview_id, idempotency_key)` 位于目录领域模块，HTTP统一经过Store门面和原鉴权。draft仅含可选project_id、name、description、directories；每项目最多200目录。预览返回稳定目标project、summary、directories、changes、transfers、warnings及三修订号；金额始终十进制字符串。changes按原项目→目标项目聚合，summary含detail_count/session_count/total_cost_usd/changed_count/already_assigned_count/claimed_count/pending_count/recovered_sessions。零记录允许绑定。

settings键`directory_assignment_policy`存`{"version":1,"projects":["项目UUID"]}`；配置中每个项目返回directory_managed布尔值。schema4无DDL改变，旧备份无设置视为未纳管。逐笔关系basis=`directory_binding`留存依据，审计保留旧项目和确认操作；不能删除历史审核来冒充从来没有人工例外。

确认在一个写事务内核对预览三修订号、期限、规则／成员／元数据／旧例外摘要，冻结选择，再更新项目配置、同目录转移双方、模式、必要历史元数据、override和相反会话默认、持久成员、日/月统计与幂等结果。原事实、版本、claims、coverage和旧原包不改。取消或任一失败全部不生效。响应丢失先查持久幂等，即使重启／缓存过期仍可重放已成功结果。

### 目录与持续识别

复用平台规范化与包含关系，同项目重叠去重。同一规范目录可在预览明确后整体转移，不同项目严格父子重叠拒绝，不能最长前缀切割目录整体。新会话、旧会话新增及以后首次导入记录按目录识别；已留NULL基线的记录在依据迟到且命中已确认目录时也可补齐。唯一有效留存历史目录复用原恢复校验，目录冲突不猜。目录整体操作不展开整个会话到目录外。

未命中当前纳管规则时保留已确认成员以支持停用和换机；被停用的目录不得通过残留会话默认继续认领新记录。已有项目需点击确认目录关联，普通升级不重算。旧assignments及association写接口不得在已纳管目录写入相反项目，提示改为调整目录；无目录旧日汇总仍按完整行处理。

### 校验与错误矩阵

| 条件 | 结果 |
| --- | --- |
| 非法项目／目录／策略版本 | invalid_project / invalid_directory / invalid_directory_policy，业务不变 |
| 不同项目的父子目录重叠 | directory_overlap_conflict，先调整目录范围 |
| 目录范围超记录／会话上限或元数据不完整 | assignment_too_large / assignment_metadata_limit，不静默截断 |
| 缺少或过期项目绑定预览 | project_binding_preview_required / project_binding_preview_expired，重新预览 |
| 重复key相同请求／不同请求 | 持久重放／idempotency_conflict |
| 旧接口绕过目录整体确认／试图拆分 | project_binding_preview_required / directory_assignment_required，目录层处理 |

### 正常、基础、错误场景

- 正常：项目选择两个目录，预览旧人工跨项目成员与费用，确认后整体迁入；以后同步和迟到目录识别均自动归入。
- 基础：零历史目录确认后仍可接收新记录；无依据旧资料保持待处理。已有项目未确认前沿旧模式不变。
- 错误：先保存目录再问历史、迁移时保留有效旧override、下一次同步被相反会话默认改回、只迁当前页或展开整个混合会话。

### 必需测试

test_directory_bindings覆盖取消无写入、有效override整体覆盖、相反会话默认、跨页完整选择、零记录、转移双方、子目录冲突、迟到依据、目录停用、旧模式兼容、身份及修订、失效／故障回滚／重放和备份设置。HTTP和web_state覆盖真实边界及关闭／迟到成功409断连、提交与刷新分开；原生浏览器和Directory／OneFile覆盖完整目录选择到费用下钻。

### 错误与正确

```python
# 错误：先保存配置，再把当前页的记录逐条分配，且人工override仍然优先。
store.save_project(None, name, description, directories)
store.assign_keys(current_page_keys, project_id)

# 正确：完整目录范围先预览影响，再以同一提交原子采用整体规则。
preview = store.preview_project_binding({
    "name": name, "description": description, "directories": directories,
})
store.apply_project_binding(preview["preview_id"], idempotency_key)
```
