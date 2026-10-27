# Research: 用量独占、版本生效与旧资料迁移

- Query: 基于现有 SQLite、批次冻结和证据包机制，实现跨连接/进程独占、同批次单一有效版本、v1 资料升级及旧客户端写入防护。
- Scope: mixed；仓库代码与合成内存实验，外部仅核对 SQLite / Python 官方文档。
- Date: 2026-10-27
- 边界：未访问正式 SQLite、CCS/Codex 原件或个人材料；仅写本研究文件。本文是建议，不是已经实施的产品行为。

## Findings

### 1. 文件与现有模式

| 文件 | 已有行为及本次影响 |
| --- | --- |
| `src/aha/storage.py:19` | 应用 schema=1；只允许全新库或相同版本，尚无升级链。 |
| `src/aha/storage.py:33` | 批次只有编号/时间；版本各自保存状态，没有有效版本指针。 |
| `src/aha/storage.py:118` | `_transaction()` 使用进程内 RLock 与 `BEGIN IMMEDIATE`，失败显式 ROLLBACK；可扩展为占用原子提交边界。 |
| `src/aha/storage.py:154` | 不可变文件通过临时文件、fsync、原子落位保存；事务失败允许留下未索引对象，但不会冒充成功版本。 |
| `src/aha/domain.py:171` | 明细身份由 app_type/data_source/request_id 构成；汇总由来源复合键构成，均不含项目、金额或 capture。 |
| `src/aha/analysis.py:119` | 已生成冻结成员、粒度、日期、来源、Token、session/time 与语义特征，可回填占用索引。 |
| `src/aha/analysis.py:196` | 明细/汇总在同一处筛选和汇总；可用过滤应放入这一计算路径，避免后删行而不重算金额。 |
| `src/aha/analysis.py:252` | 同日同模型明细+汇总目前只提醒，仍相加；独占版必须另挡住单张材料内部的覆盖冲突。 |
| `src/aha/batches.py:26` | `_scope()` 按 app/source/provider/date/model 识别汇总覆盖；`_semantic()` 用 session/time/Token 提示请求键重建。 |
| `src/aha/batches.py:53` | 当前从所有历史版本扫描重叠，并排除本批次全部版本；提醒不构成占用。 |
| `src/aha/batches.py:192` | 幂等查询、版本创建、原 ZIP 与索引写入已在同一写事务内。 |
| `src/aha/batches.py:321` | 列表以 MAX(version) 为当前版本；不能直接沿用为有效版本规则。 |
| `src/aha/batches.py:359` | 当前状态可任意来回改；更新 SQL 只写 status/status_updated_at，旧连接不会重复检查 schema。 |
| `src/aha/batches.py:378` | 下载只读已保存 ZIP 并校验哈希，适合继续服务过时/作废版本。 |
| `src/aha/server.py:161` | 缓存分析只检查本进程 generation 与归属 revision，缺少跨进程占用 revision。 |
| `src/aha/server.py:301` | API 调用单一分析器后保存 opaque analysis_id；新建可用预览和创建请求可继续绑定同一结果。 |
| `src/aha/__main__.py:29` | runtime.json 为启动信息，不是互斥锁；后启动可替换描述符，不能据其缺失宣称没有旧连接。 |
| `tests/test_batches.py:119` | 当前测试明确允许再次创建重叠批次；需改为独占验收。 |
| `tests/test_batches.py:176` | 只覆盖一个 Store 上的线程幂等；不证明独立连接/进程互斥。 |
| `tests/test_storage.py` | 已有失败写入、重启、损坏、版本拒绝测试，可复用其合成资料模式。 |

旧设计边界见 `.trellis/tasks/archive/2026-10/10-27-codex-usage-evidence/design.md:118`：每版本状态独立、重叠可继续。因此本次属于显式业务契约变更，不应只替换提示文案。

### 2. 已由主会话传达的产品决定

- 新建报销只预览并导出剩余可用用量，显示被排除的数量。
- 占用归属于 batch，不归属于 capture；同批次仅一个当前有效版本。
- 只有草稿可直接修订；已提交先显式撤回到草稿；已报销纠错先作废，再新建。
- 用户允许已报销批次手动作废释放，必须填写原因；保留原批次、金额、状态历史及原 ZIP。
- 普通状态操作不释放；作废是终态，不可再标为有效。

保存草稿即占用、迁移冲突处理等最终措辞仍以主会话 PRD/最终评审为准，研究不代替用户决定。

### 3. 建议数据结构：增加独占索引与批次控制，不改旧 ZIP

应用 schema 建议升级至 2。保留原 `batches/revisions/status_events/idempotency` 及冻结内容，增加：

| 对象 | 建议字段/约束 |
| --- | --- |
| `batch_control` | `batch_id PRIMARY KEY`、`active_version`、`lifecycle=active/voided/legacy_review`、`generation`、作废时间/原因；复合 FK 指向 revisions；active 时 active_version 非空。 |
| `usage_claims` | `record_key TEXT PRIMARY KEY NOT NULL`、`batch_id`、`owner_version`、`kind`、`scope_key`、`semantic_key`、必要 member_json；关联批次/版本。 |
| `legacy_holds` | 旧冲突/多有效候选的保留集合，键含 record_key/batch_id/version，允许保存多个待裁决候选；持有同样的 scope/semantic 索引，不能与可报销记录混同。 |
| 索引 | `(scope_key,kind)`、非空 semantic_key 索引；保证覆盖查询无需遍历全部历史版本。 |
| `claim_events` | append-only 操作记录：批次、版本、动作、原因、时间、前后有效版本；与原 financial status_events 分工。 |
| `settings.claim_revision` | 每次占用成员、有效版本或作废改变时单调递增；不复用目录归属 revision。 |
| 旧 revisions 增列 | `claim_protocol INTEGER NOT NULL DEFAULT 0`、`write_generation INTEGER NOT NULL DEFAULT 0`，用于旧客户端防护。 |

有效/过时/作废是版本生效关系，不应覆盖旧版本原 financial status。返回 `is_effective`、`lifecycle`、`active_version`、`generation`，界面据此限制动作；列表读取控制指针，不再把 MAX(version) 自动视为有效。

`usage_claims` 的唯一键保证明确身份只有一个持有批次；跨粒度与疑似重建由同一写事务中的覆盖检查补充。不要给整个 date/model scope 设置普通唯一键，那会把同一天两条互不相交的明细也错误互斥。

### 4. 明细、重建与汇总的身份契约

1. **明确明细**：沿用 `record_key`。金额、项目、capture、source文件名均不能参与占用键。相同 request key 跨重读/改价/改归属继续被占用。
2. **不同 request key、相同 session/time/规范化 Token 特征**：属于“疑似同一用量”，不能伪称确定相等。严格版可以以“无法确认独立”阻止直接使用，明确原因；不能自动删掉其中某条并静默改总额。
3. **完整旧日汇总**：其复合键之外，还需检查 date/model/source/provider 覆盖。汇总与另一份同覆盖汇总、汇总与明细覆盖都可能重复；按完整记录阻止，不做按比例扣除。
4. **同一分析内部**：同 scope 的 detail+rollup 或不同键 rollup+rollup 也要检测。未能证明互不重叠时阻止这份材料生成，不可只检查跨批次，也不可任意选择一个粒度当作真实费用。
5. `_member.semantic_key` 与当前 `_semantic()` 的字段集合并不相同：前者包含 total_tokens、不包含 provider_id，后者相反。应建立唯一的纯函数辅助层，让迁移、可用过滤、保存检查共用同一键和理由计算。

没有上游稳定请求身份且会话/时间/Token也被同时改写时，本地不能证明两行实为同一调用。这里的可执行保证是：明确来源身份互斥，已知覆盖/疑似重建不直接放行；不要宣传可识别任意人为重写后的真实消费。

### 5. 保存、版本切换与释放的事务顺序

以现有 `Store._transaction()` 为边界：

1. `BEGIN IMMEDIATE` 后再读取当前状态、占用和 revision；不要只依赖之前的界面预检。
2. 优先查询幂等键。同一请求重试返回原版本与当前生效关系，不重新占用；即便后来已作废，也不能因重试复活。
3. 验证本批次未作废、修订基于当前有效草稿，expected generation/active_version 与数据库一致。
4. 对实际待保存成员做内部覆盖及其他有效批次占用检查；同批次自己的成员允许复用。
5. 生成并校验新的不可变 ZIP；不改旧 ZIP。
6. 插入新版本，取得新增成员占用，更新保留成员 owner_version，切换有效指针；仅在允许修订的草稿路径释放被删除成员。原旧版变为历史关系，不改其原金融状态或材料。
7. 保存事件、幂等结果，递增 claim_revision，COMMIT。

任一步失败：版本、有效指针、占用、事件、幂等索引一并回滚。可能留下孤立的新 ZIP 文件，但不能成为成功版本；原有效版和占用仍在。

独立进程的 RLock 不互通；跨进程安全来自 SQLite 同库写事务串行性与唯一约束。并发竞争后一个应得到可操作的 409，刷新得到剩余可用记录，不能保存时偷偷删掉冲突部分再沿用旧申请总额。

### 6. 可用预览与 API 建议

建议稳定门面（名称可由实现阶段收敛）：

```text
Store.availability(members, exclude_batch_id=None)
  -> {claim_revision, available_keys, excluded, conflicts}
Store.create_batch(analysis, claim, idempotency_key, batch_id=None,
                   expected_generation=None)
Store.withdraw_batch(batch_id, expected_generation, reason)
Store.void_batch(batch_id, expected_generation, reason)
Store.resolve_legacy(batch_id, selected_version, expected_generation, reason)
```

- `POST /api/analysis` 增加明确的新建/修订用量模式（或 exclude_batch_id 上下文），结果含 claim_revision、实际可用 summary、排除计数/金额与理由。修订仅免除本批次自己的占用。
- 修订分析必须绑定真实目标批次、当前有效版本及 generation；新建请求不能借用任意 exclude_batch_id 的“免占用”结果。保存时再次验证相同目标。
- 可用过滤要在 `analysis.py` 的唯一汇总路径中执行，或者重用一个抽出的聚合函数；不能在返回结果上只删 details/members，而留下 daily/models/summary 原值。
- `_analysis()` 校验数据库 claim_revision，创建保存仍在事务内重查冲突。其他程序刚占用后，旧预览应 409 `availability_changed` / `usage_claimed`，再刷新预览；不得自动减掉并直接提交。
- `POST /api/batches/preview` 返回 blocking conflicts；界面移除“仍然继续”路径。普通下载仍走历史 ZIP 路由。
- 新增撤回/作废 API，携带原因、expected_generation 与幂等标识。作废重试不得删除其他批次后来取得的占用；DELETE 必须同时限定 owner batch。
- 普通 status API 只作用于有效版本并按新生命周期校验；不能继续任意 draft/submitted/reimbursed 来回切。
- 新增暂态 `claim_revision` 不宜直接进入 `_analysis_hash()` 的可重用业务内容，否则别的批次变化也会让完全相同的修订被当成新版本；成员、实际金额与冻结选择依然进入业务 hash。

建议错误：`usage_claimed`、`usage_ambiguous`、`usage_internal_overlap`、`availability_changed`、`stale_batch`、`batch_voided`、`inactive_revision`、`migration_conflicts`、`store_busy`，均返回安全的批次编号/计数/日期范围，不泄露原路径。

### 7. 旧活跃 v0.1.0 连接：不能只加新表

旧 Store 只在启动时读 user_version。升级后已经打开的旧连接仍能执行旧 INSERT 和状态 UPDATE；新增 claims 表本身不会让它自动维护占用。

建议小防护：

```sql
-- 示意，完整触发器需补当前批次/版本条件并由迁移建立。
BEFORE INSERT ON revisions
WHEN NEW.claim_protocol IS NOT 2
  -> RAISE(ABORT, 'aha_upgrade_required');

BEFORE UPDATE OF status,status_updated_at ON revisions
WHEN NEW.write_generation IS NOT OLD.write_generation + 1
  OR 目标不是当前有效版本 OR 批次已作废
  -> RAISE(ABORT, 'aha_upgrade_required');
```

新代码插入版本显式写 protocol=2；状态更新在同条 SQL 内 `write_generation=write_generation+1`。旧 SQL 省略这些字段，连已缓存、已打开的旧连接也会被拒绝。触发器只校验，不在 BEFORE 触发器中自行改同一行。新代码仍需验证允许的状态转换与原因，不把 generation 当业务授权。

本轮纯内存共享 SQLite 两条始终打开的连接已实测：旧 INSERT 拒绝、旧缓存 UPDATE 拒绝、新 generation+1 更新有效版成功、过时版即使+1也拒绝。该合成实验未涉及正式库或文件；实现仍要补实际文件数据库和 Windows 连接测试。

升级仍应要求用户退出旧实例；runtime.json 只能提示，不能当成完整进程互斥。schema=2 会阻止旧版重新打开；触发器覆盖迁移前已活跃旧连接。新版本还可用独占运行锁限制同一 data-dir 的多实例，但数据库互斥不能因此省略。

### 8. v1 迁移、备份与历史冲突

1. 在写锁内重新读 user_version，保证两个新程序并发启动不会各跑一次迁移。
2. 建议在任何 schema 变更前，以 SQLite backup API 保存唯一命名的完整 v1 数据库快照并校验可读；原 objects/packages 不改。若需在 BEGIN IMMEDIATE 保护下备份，使用另一条只读源连接；不要对同一条正持有写事务的连接调用 backup（会遇到锁）。实施阶段用真实文件测试该顺序及超时。
3. DDL、回填、约束、触发器和 user_version=2 在同一显式事务逐句 execute。**不要在已 BEGIN 后调用 executescript**：Python LEGACY_TRANSACTION_CONTROL 下它会先提交已有事务，本轮内存实验已确认。
4. 所有旧版本先扫描，验证 members_json 的形状/键/粒度与已冻结分析一致；损坏、缺失或无法确定的资料不得当作空成员放过。不得为迁移重建或覆盖原 ZIP。
5. 对每批次找候选有效版时，不能只取 MAX(version)：旧版已报销、后面出现不同成员草稿时，直接取新草稿会静默释放已报销的旧成员。多个已提交/已报销版本或跨批次重复必须明确列为待处理冲突；同成员但不同申请金额也不能自行推断哪笔申请真实有效。
6. 无冲突的现有单版本草稿可直接回填占用；项目、旧状态和材料不改。
7. 按主会话收敛方向，旧冲突批次进入 `legacy_review`，没有有效版本但其所有候选成员仍通过 `legacy_holds` 阻止新使用。不能只保留交集键而放掉同批次尚未裁决的其他旧成员，更不能自动选一个 owner。原版本/状态/ZIP 可查。用户先显式作废不保留者，再确认保留批次的具体有效版本；每一步需原因和 generation。确认时重新检查其他有效占用/legacy hold，仍冲突则拒绝。
8. 作废旧待处理批次只删除该批次自己的 hold；其他待处理者对同一键的保留仍生效。确认有效版后，在同一事务内建立唯一 usage_claims、切换有效指针并移除该批次 holds，记录被明确替代的旧候选。不得因一个冲突解除而全局清空保留集合。
9. 备份失败/DDL失败/损坏成员回填失败均退出原 schema1；备份及恢复说明保存到独立位置。恢复旧版本必须在所有实例退出后恢复完整备份与配套资料；不能让旧 exe 直接读取已升级库。

旧正式库现状来自主会话只读结论（1 个草稿，无跨批次重复），本研究未再次访问；不能把这一点当作省略通用迁移校验的理由。

### 9. 最小受影响文件与验收测试

建议 `storage.py` 继续唯一拥有 schema/迁移；`batches.py` 拥有有效版本与生命周期；可新增 `claims.py` 集中身份/覆盖/可用规则。`analysis.py`、`server.py`、`web/app.js`、`web/index.html`、README、版本号、构建交付及两份实际 spec 随契约更新。

必须的测试点：

- 两个独立 Store / 两进程 / 不同幂等键并发报同一明细，仅一个成功；同幂等键重试始终同一原版本。
- 同 source 重读、改价、改项目、改 metadata/capture 不绕过；同日不相交明细可分别报销。
- 疑似重建、rollup→detail、detail→rollup、rollup→rollup覆盖冲突，以及单分析内部 detail+rollup 冲突。
- 混合可用/已占用过滤后的 details、rollups、daily、models、所有 Token 和 Decimal 金额一致；分页不影响导出。
- 草稿修订保留本批次占用，移除成员只按允许路径释放；失败文件写入/索引提交后，旧有效版和占用不丢。
- 已提交先撤回；已报销不能直接改草稿/修订；有原因作废后释放，旧状态历史和 ZIP 不变，作废批次永不复活。
- 作废后其他批次取得用量，再重试旧作废请求/旧创建幂等请求，不释放新 owner、不重新占用。
- v1 单草稿正常迁移；legacy 已报销旧成员不被 MAX(version) 丢弃；旧跨批次重复与多已报销版本明确冲突。
- legacy_review 的所有候选成员持续保留；逐项作废/确认时重查其他 holds，不能误释放其他待处理批次；有效版本选择和原包哈希均可审计。
- schema1→2 故障注入回滚、备份不可写、同时迁移、未知版本、损坏 members 均保留原资料。
- 迁移前始终打开的旧连接执行原 v0.1.0 INSERT / UPDATE SQL 被拒绝；新代码协议写入正常。
- 浏览器未刷新时其他进程占用/作废，旧分析失败并要求刷新；后台直接调用不能绕过界面。
- 原生 Windows 升级副本、退出重启、旧包 SHA-256、CSV/HTML 实际范围验证。

## External References

- [SQLite Transactions](https://www.sqlite.org/lang_transaction.html)：多个连接可同时读，仅一个写事务；BEGIN IMMEDIATE 先取得写事务，可能返回 SQLITE_BUSY。本文据此建议统一事务，不依靠线程锁。
- [SQLite CREATE TRIGGER / RAISE](https://www.sqlite.org/lang_createtrigger.html)：持久化触发器可校验 NEW/OLD，RAISE(ABORT, literal) 拒绝当前语句；本文触发器是校验型，不修改原行。
- [Python 3.12 sqlite3](https://docs.python.org/3.12/library/sqlite3.html)：明确事务/backup API 与 executescript 的隐式提交边界。实施沿用项目 Python 3.12+，不要求升级解释器。
- [SQLite Backup API](https://www.sqlite.org/c3ref/backup_finish.html)：源/目标连接必须不同；备份源正被同一连接写入会遇到锁，备份失败要明确处理。

## Related Specs

- `.trellis/spec/backend/usage-evidence-contract.md`：现有事务、身份、冻结、幂等、原包与精确金额契约；其中“可重叠继续”和任意状态修正条款将被本任务的已批准方案替换。
- `.trellis/spec/frontend/local-web-contract.md`：现有分析失效、页面状态与四文件下载；需增加占用变化失效、有效版本动作与 blocking conflicts。

## Caveats / Not Found

- 无现成占用表、迁移框架、取消/作废、有效版本或跨进程占用测试；需要真实实现，不能只改按钮。
- 本研究按主会话收敛方向记录 legacy_review 隔离及显式处理；最终产品/API 名称以最终评审方案为准。
- 未实现或测试任何产品补丁。仅完成内存级触发器/executescript 行为验证；真实文件备份锁顺序、Windows 升级与并发必须作为实施验收。
- 直接编辑本地数据库文件、把应用数据复制到两个互不通信目录各自运行，不在单一数据库独占保证范围内；程序不能替代财务系统实际付款核对。
