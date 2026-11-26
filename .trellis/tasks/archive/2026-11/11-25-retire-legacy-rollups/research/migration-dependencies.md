# 旧日汇总清理与旧材料兼容

- Query: 如何从活动台账移除旧 CC Switch 日汇总，保留逐笔明细、旧材料和历史占用事实，并兼容 3–5 版备份。
- Scope: internal
- Date: 2026-11-25

## Findings

### 版本和入口

- `migrations.py:14–15,150–201,231–270` 通过历史生产 DDL 检查每个版本的表、列、索引和触发器。当前 schema 5 的 DDL 应固定为 `SCHEMA_V5`，支持集显式含 3、4、5、6。先验证来源版本，逐步完成 3→4→5，再在同一事务内完成 5→6。新库直接创建 schema 6。同版重开不再执行清理或重复备份。历史 `batches.initialize_schema` 含允许两种 `usage_claims.kind` 的约束，改变其通用 DDL 会破坏对历史版本的严格比较。
- `storage.py:48–74,108–124` 已在迁移事务前生成一致的完整回退包，使用注册了十进制 SQL 聚合、开启外键的写连接执行 `BEGIN IMMEDIATE`。用既有入口升级实际台账。在 WSL 或旧应用进程占用目录时，通过既有实例退出、切换流程交接。将回退包和原始数据动作分开验证。
- `backup.py:540–567,630–660` 在恢复专用目录内验证后升级。把用 `current_schema == SCHEMA_VERSION` 判断物理游标的条件改为接受物理游标首次出现的 schema 5，否则 v5 备份恢复会保留旧机器游标。恢复迁移连接目前未注册 `decimal_sum`、`integer_sum`，使用现有汇总重建逻辑时需注册，按迁移代码访问方式设置行工厂。`backup.py:631,677–684` 的 `counts` 目前在升级前取得，恢复回执若表示新库状态，应在升级后重读计数，来源归档完整性仍在升级前验证。
- `migrations.py:132–145` 定义 `codex_history_rollup_day`；`reconciliation.py:99–108` 的 `INDEXED BY` 硬依赖必须随活动日汇总探测一起移除。`source_rollup_observations` 的活动调用全部来自 `sync.py:462–473,799–805`；可从新版 DDL 移除并迁移时删除该表，schema 3–5 验证仍保留其原定义。

### 事务内清理顺序

1. 捕获待退役的活动记录键、受影响的 coverage keys 和版本。`domain.py:172–191` 保证旧版本键为 `rollup:<hash>`，可同时使用版本键前缀捕获失去活动记录的旧版本和原生待发布数据之外的累积历史。用临时表或查询对子集操作，避免将几万条业务明细搬入 Python。
2. 识别要退役的核对事项。`ledger.py:181–245` 的 `coverage` 和 `sync.py:554–561` 的 `rollup_origin` 是旧汇总专用。旧汇总键本身的版本候选也须清理。`sync.py:456–487` 的 `source` 核对根据三项条件生成，同时读取 `info_json.observed.detail` 与 `previous.detail`，不能因为其中存了 rollup 计数就关闭真正的明细缩水问题。复核目标为逐笔的目录、版本、身份、来源质量仍保留。对直接删去的旧核对项，按收集到的 case id 定向清理 `reconciliation_events` 以及 `reconciliation_idempotency.result_json.id`；后者还存着与此无关的目录和归属操作，不能整表清空。若保留开放事项审计，将旧事项设置为 `superseded` 并换掉日汇总原因。
3. 处理已展示的历史重叠和抑制。`ledger.py:703–729` 在确认采用旧汇总时，把同组明细设为 suppressed，排除日汇总后须使这组有证据的逐笔明细重回统计。依据 `coverage_groups.basis='rollup'` 定位这类组，保留 `record_aliases` 和逐笔核对登记的独立抑制。旧组 `basis` 归回逐笔口径；留下有明细的组，因为 `ledger.py:369–385` 仍靠 coverage_groups 找出 scope 的日期/模型以重算。仅由被删除旧汇总占据的组可以清理。
4. 对 `native_overlap` 且 `info_json.pending_reason='historical_rollup'` 的开放逐笔事项重新核对。`native_sync.py:167–213` 先排除不确定原生证据，再针对同语义 legacy 明细、同日/模型旧汇总和同会话历史明细探测，可能几类同时满足且最终理由只记录汇总。移除纯汇总原因后，将仍有实际逐笔冲突的事项保留为明细重叠或具体身份事项，否则将旧事项退出开放状态。检查当前原生版本的 `codex_event_evidence` 和可能跨秒/跨日的 `snapshot_timestamp`，或用保守的同会话历史明细复核避免自动放行难以证实的双计。用户已确认的逐笔身份或独立抑制不能借迁移批量撤销。本次用户实际台账的开放 `historical_rollup` 数为 0。
5. `migrations.py:55–60,79–84,118–129,138–143` 定义外键依赖。先删该键的 `record_project_links`（引用活动行）、`overrides`、旧汇总归属事件及指向该键的 alias，再删 `usage_records.kind='rollup'`，清退对应的旧暂存行和来源观测。再找出所有未被 `revision_members.usage_version_id` 引用的旧 `usage_versions`，先删对应 `record_evidence` 和可能存在的 `codex_event_evidence`，再删版本。无需删除来源资料、全局同步历史、逐笔会话或项目。旧统计索引、来源观测表与新版约束 DDL 在同一事务调整。防止新版写回旧汇总可在活动入口只接纳明细，配合只约束活动记录的新触发器；触发器不能经简单 `split(';')` 拆开执行。
6. 按新规则重算 availability 和精确的日/月派生表，再推进 `settings.data_revision`。`ledger.py:320–432` 有整库入口 `refresh_availability(connection)`，会重新计算未决事项、占用与数字，并让已清空的日期从统计表消失，无需重算已有项目归属。没有旧汇总但存在需去除的残余派生状态时也要更新相应数据。最终校验 schema 6 和外键关系，失败使迁移事务整体回滚。

### 旧材料和旧占用

- `batches.py:89–125` 对 `revision_members.usage_version_id` 设外键，并禁止更新或删除冻结成员。旧材料必须保留冻结成员、被它引用的精确版本、所有 `revisions` 字段及原 ZIP。`batches.py:1122–1136` 的下载路径只读原文件并复验 hash，不依赖当前 `usage_records`，无需重建任何旧 ZIP。`backup.py:156–175,312–325,636–640` 随完整备份逐一验证所有历史和作废版本引用的原材料。活跃账本中被旧成品引用的冻结证据作为既有成品的一部分留存；本机台账旧汇总的报销引用为 0。
- `usage_claims` 不引用活动行，已有有效记录的 `kind='rollup'` 占用可以作为旧材料的防重复事实保留。`ledger.py:340–357` 和 `batches.py:637–669` 通过 scope 和语义键检查其他报销；不能删除旧占用来解除冲突。`batches.py:1023–1067` 作废时按批删除自己的占用、重算可用性；撤回不释放。清理旧汇总不会作废报销。维持旧状态变更和原包下载的同时，旧汇总冻结依据不能进入新材料。`server.py:689–751` 是修订入口，`batches.py:316–341,739–751,794–799,854–862` 还要保证 Store 直调和最终写事务不能绕过；UI 可复用 `can_edit` 展示退役依据的限制，原版幂等重放可继续交付既有包。
- 仅保留原 `scope_key` 检查对原生来源不够。`claims.py:31–34,65–99` 的 scope 含 `data_source`，旧汇总写 `codex_session`，正常原生明细为 `codex_native`。当前原生采集另外按日期与模型探测活动旧汇总（`native_sync.py:187–213`）。退役时应根据仍有效的旧报销冻结成员检查其同日/模型范围，或给出等效的已报销防重约束，而无需让普通未报销汇总留在当前台账。关联 `usage_claims` 和对应 `revision_members`，从 `member_json` 取得验证过的日期、模型和计价模型。迁移后的既有原生明细和后到的原生明细都应覆盖测试，作废该旧报销则只释放其相关阻挡。

### 验证用例

- 用独立构造的完整 v5 DDL 验证实时升级与 v5 备份恢复；把有旧汇总的 v3、v4 包也走实际验证和升级入口。检测恢复后无旧游标、归档完整 SHA 原样、逐笔数量与十进制金额不变、日/月统计无空余旧金额、同版重启不再新增迁移备份，以及故意中途失败回滚 schema 和数据。`tests/test_assignment_migration.py:84–245`、`tests/test_backup.py:118–119,240` 已提供可靠模式，固定历史定义或独立 fixture，避免用改后的最新 DDL 伪造旧版。
- 混合 v5 夹具至少含未占用旧汇总、已经被明细替代的旧汇总、被旧覆盖压住的未占用逐笔、逐笔 alias、一对纯汇总/仍有逐笔候选的 native overlap，以及一笔含旧汇总的冻结材料。验证未归档的旧版本和证据删除、逐笔禁用/通过判据，以及备份中旧成员和原 ZIP hash 可复核。另测旧报销防重跨来源和作废释放，测试冻结 `current` / `frozen_basis` 修订不会从归档重新引入旧汇总。
- 回归新日视图、趋势、项目归属、部分日时段和新报销材料全部从逐笔生成。真实台账验收记录清理前后活动旧汇总数、受影响未冻结版本数、完整备份内容以及逐笔差异汇总，不记录私人会话日志或源数据正文。

## Caveats / Not Found

- 研究只读工作区代码和规范；未查看或修改真实账本和材料。利用内存数据库复核了 schema 3、4、5 都有来源汇总观测和冻结成员触发器，只有 schema 5 有物理游标与旧汇总日期索引。未运行迁移，因为实现尚未产生。主任务提供本机的 117 / 0 / 0 背景计数。
- 审计回执中的日期、原因与冻结包属于已发生的历史。逻辑删除活动行不等于抹除旧备份、SQLite 空闲页或文件系统痕迹；本次目标是退役当前台账数据，并按用户同意保留回退包。
- 相关规范见 `.trellis/spec/backend/{usage-evidence-contract,recovery-and-device-contract,database-guidelines,delivery-and-cleanup,codex-native-source-contract}.md`。本次研究以仓库实现和内存 DDL 验证为据，无外部依赖。
