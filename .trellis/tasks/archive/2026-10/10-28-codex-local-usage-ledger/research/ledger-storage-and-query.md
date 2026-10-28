# Research: 本地台账、旧资料迁移与查询性能

> 主会话范围更新（2026-10-28）：用户已选择历史用量安全并入、冲突待核对，随后明确尚未正式使用，除历史 CCS 来源资料外的试用业务数据均可删除。因此下文旧业务库串行迁移、旧报销/占用/ZIP 兼容、新旧 writer 共存方案仅保留为调研记录，**不纳入本次实施**。新库重建前只做一次性历史用量保全；查询、精确统计、行式冻结、性能与 WAL 运行时结论继续适用。当前范围以任务 PRD 和 design.md 为准。

- Query：如何把既有不可变 capture 转为可长期查询的本地台账，同时保持精确核算、占用和原报销材料，并验证百万/千万级性能。
- Scope：mixed；当前仓库代码与 SQLite/Python 官方文档。仅规划研究，未执行迁移或规模基准。
- Date：2026-10-28。
- 写入边界：仅本研究文件；未访问用户实际源库、SQL、正式应用资料或修改产品代码。

## Findings

### 1. 关键结论

1. SQLite 可以继续承担单机台账；必须同时改变查询、占用检查和导出路径，不能只增加一张用量表。
2. 当前 capture 不具备可靠的来源链或源修订顺序。观察时间、文件名、capture 创建时间不能自动决定冲突版本的胜者。
3. 建议把可确认无冲突的历史用量并入台账，重复内容复用，冲突保留待核对；这是尚待用户确认的迁移产品决策。
4. 新事实和修订采用行级存储，当前有效视图与可重建统计分开；旧 capture、旧报销 JSON、原 ZIP 保留原样。
5. 列表使用索引与游标；可用用量必须按 SQL 索引检索相关占用，统计不能通过读取全部 claims 实现。
6. 精确金额保留 TEXT，聚合使用精确十进制/大整数方案；SQLite 内建 SUM 不能直接代替当前 Python Decimal 口径。
7. WAL 与独立读连接能改善读取并发；发布前必须验证实际 SQLite 运行时已包含 WAL-reset 修复。
8. 下述性能门槛是建议值，没有现成实测结果，须纳入最终规划评审及目标 Windows 验收。

### 2. 文件与现状证据

| 文件与行号 | 已确认行为及影响 |
| --- | --- |
| `src/aha/storage.py:22` | 应用 schema 包含项目、overrides、capture 索引、报销版本和幂等；没有可索引的用量事实表 |
| `src/aha/storage.py:53`、`:104` | Store 持有单连接与 RLock，事务为 BEGIN IMMEDIATE；同进程长事务会阻塞其他 Store 读取 |
| `src/aha/archive.py:100`、`:162` | 来源只留 kind/name/fingerprint/observed_at，capture 身份还混合用量、目录依据和来源观察 |
| `src/aha/archive.py:119`、`:233` | 读取整个 gzip/JSON 并重新校验投影，不能作为长期台账的每次查询入口 |
| `src/aha/projects.py:46`、`:88` | 逐行分类遍历项目目录；config 读取全部 overrides，规模增长后应改为局部查询与派生索引 |
| `src/aha/analysis.py:248`、`:329` | 全量候选、成员、明细、日统计均在 Python 集合中构建并排序 |
| `src/aha/batches.py:175`、`:365` | 每次 claim_snapshot/保存检查都加载全部 claims/holds；已有 scope/semantic 索引尚未用于局部候选检索 |
| `src/aha/batches.py:351`、`:400` | 保存时重读整个 capture、复制完整 analysis，并在写事务内构建全量 ZIP |
| `src/aha/evidence.py:142`、`:317`、`:397` | CSV、逐成员 manifest、ZIP 都整份放入内存 |
| `src/aha/batches.py:763` | 下载读取整包并在 RLock 内校验；大包会阻塞其他 Store 操作 |
| `src/aha/server.py:252`、`:326` | analysis 缓存持有完整选中行；页面分页只是对内存列表切片 |
| `src/aha/web/app.js:444` | 当前分页为 page/size 与页数，改游标时须保留前后页体验，不能继续深 OFFSET |
| `src/aha/migrations.py:71`、`src/aha/storage.py:339` | 目前只认识 0/1/2；旧迁移已有写锁内重读版本、只读 backup 与失败回滚模式 |
| `src/aha/migrations.py:55` | 现有触发器阻止 v0.1.0 writer，不会自然阻止已经打开的 v0.2.0 writer |

### 3. schema 2 到新版本的建议边界

建议新应用 schema 采用下一串行版本（例如 3），来源 schema 仍按独立适配器管理。表名是设计建议，主会话可统一命名。

| 层 | 建议职责 |
| --- | --- |
| `ledger_sources` / `sync_runs` | 本地来源登记、来源代际、同步结果、成功发布序号；不把路径或文件哈希当成稳定业务身份 |
| `usage_records` | 一条逻辑记录与兼容旧 `record_key` 的映射、当前事实版本指针、当前可查询字段 |
| `usage_versions` | 只在内容变化时增加的不可变允许投影；唯一约束至少覆盖记录身份和内容指纹 |
| `session_versions` / `usage_classification` | 目录依据及派生项目归属；人工覆盖继续绑定原始内容指纹，变化后不得无声继承 |
| `coverage_groups` / `reconciliation_candidates` | 明细/来源日汇总的覆盖依据、冲突及确认事件；不能混入本地统计表冒充普通事实 |
| `daily_usage_stats` | 按日期/项目/模型维护精确派生统计及可用/排除分类；只重算受影响范围，可从事实重建 |
| `legacy_capture_imports` | 旧 capture 回填状态、内容校验、来源确认与冲突结果；旧对象仍为原依据 |
| `analysis_selections` / `revision_members` | 分页查询的选择依据及新报销冻结成员版本，避免完整成员 JSON 成为所有路径的载荷 |

应保持原始事实与项目/可用状态分层，不能把当前项目名纳入记录身份。来源身份、逻辑消费身份和原 `record_key` 也不能合成一个新主键后丢弃旧映射，否则旧占用可能被绕过。

新同步只新增实际变化的事实/修订；未变化同步可增加少量 run 元数据或临时 staging，不应为每行持久增加一条重复版本或每次复制整份本地台账。临时 staging 的写入与业务事实增长要分别计量。

### 4. 旧 capture 的自动合并边界

- `safe_source` 没有保存稳定来源链，SQL 文件哈希与 SQLite 投影哈希也不是同一种身份（`archive.py:100`）。
- 新导入的 SQL 可能是旧备份；`observed_at` 代表读取时刻，不证明其中的金额比既有资料更新。
- `captures.created_at`、`observations` 的最大时间、文件名排序及“更大的金额”都不能用于选定冲突事实。
- 同一原始记录键、同一内容指纹可复用同一事实存储；这本身不证明多个来源属于同一台账。只有符合已确认来源关系、覆盖约束的候选才自动生效。
- 不同键但 semantic 相同只能进入疑似重建候选，不能自动合并或当作独立消费；见 `claims.py:35`、`tests/test_claims.py:42`。
- 同键不同内容、会话目录依据冲突、日汇总覆盖不明时，保留所有版本和原 capture 关联，显示待核对；不能自行取最后观察值。
- 对无法确认的候选，提供独立数量/范围和原因，不以零消耗或“完整合计”掩盖。原报销版本仍引用原依据。
- 已有原始对象/ZIP 缺失或损坏时，明确阻止相应迁移或恢复，不重建、跳过并报成功；参考 `tests/test_migrations.py:119`、`:167`。

最高价值产品问题：是否将可确认无冲突的旧 capture 用量并入新台账（建议），有冲突的保留待核对；另一方案是只从当前 CCS 开始累计，旧 capture 仅查档。前者覆盖历史更好，需核对冲突；后者迁移更简单，但过去只存在于旧 capture 的明细不进入新查询合计。两者均保留原件与原报销材料。尚未替用户作出选择。

### 5. 迁移、旧 writer 与回退

1. 在隔离副本实施演练；升级前退出旧程序。备份库采用独立只读 SQLite backup，校验 user_version/quick_check，记录不可变对象和 ZIP 清单及校验值。
2. 写锁内重读 schema；空库显式建新 schema；旧 schema1 沿用既有 v1→v2 契约再串行升级；未知版本拒绝。
3. 保留 `projects/overrides/captures/observations/revisions/status_events/idempotency/batch_control/usage_claims/legacy_holds/claim_events` 的既有含义及原索引关系。
4. 旧库回填应按 capture 顺序有界读取、校验、登记已处理对象；不要在内存同时展开所有历史 capture。超大单对象需验证流式解析/资源预算，不能用“单对象处理”假称内存恒定。
5. 结构、回填和校验全部成功后才发布可用台账；失败不将部分结果当作完整迁移。业务上待核对的候选是显式状态，与迁移损坏分开。
6. 旧 schema2 已打开连接不会再次执行 initialize；仅修改 user_version 或保留旧 protocol=2 触发器不足以阻止旧写入。
7. 新协议门禁需覆盖项目/人工归属/来源留存/claims/报销状态等所有会影响派生数据的写入口，包括 DELETE。可研究新写连接专属协议 UDF + 持久触发器，验证 trusted_schema 与运行时支持；未注册该能力的旧连接必须失败。不要只保护 revisions INSERT。
8. 旧 JSON、冻结哈希、ZIP 字节和原财务状态不重写。新报销可新增明确协议版本与关系化成员；旧协议读取/下载保留兼容适配器。
9. 回退恢复升级前库及配套不可变材料，不能把新库交给旧程序继续写；迁移失败与旧连接拒绝须有双连接/双进程测试。

### 6. 精确金额和 Token 聚合

当前金额可带指数，允许输入指数绝对值到 100、较长有效位（`domain.py:97`）；测试明确保留 `1.234567891234567891e-10`（`tests/test_sources.py:270`）。固定微美元或纳美元会丢精度；单行 INTEGER 能容纳也不代表汇总不溢出。

建议：

- 原金额和修订金额仍保存规范十进制 TEXT；不经过 REAL，不按当前价格或倍率重算。
- SQL 条件、关联、分页由 SQLite 完成；使用注册于 Store 所有读取连接的精确聚合函数，只对命中范围或受影响日重算。
- 可用十进制系数/指数对齐后的 Python 大整数累加来避免 Decimal context 舍入，输出再经领域格式与范围检查；或者使用足够精度且能检测 Inexact/Rounded 的 Decimal 实现。
- Token/代表记录数的多行总和也可能超过 int64：汇总层需大整数聚合/文本保存，或经过证明的范围守卫，不能在溢出后改用浮点。
- 统计表保存精确结果；月/年汇总只合并较少日统计。Python 自定义聚合存在每行回调成本，不能对每次年度查询调用千万次回调。
- 明细、统计、报销材料须用不同数量级、超小金额、边界 Token、修订撤销等样例逐项对账；超出约定范围明确失败，不截断或舍入后继续。

官方依据：[SQLite aggregate functions](https://www.sqlite.org/lang_aggfunc.html#sumunc) 说明 SUM/total 的浮点与整数溢出行为；[Python 3.12 create_aggregate](https://docs.python.org/3.12/library/sqlite3.html#sqlite3.Connection.create_aggregate) 支持以 step/finalize 实现聚合，返回 SQLite 支持的类型。精确字符串输出可避免 Python int 直接返回超 int64。

### 7. 查询、可用用量与缓存一致性

- 列表索引建议覆盖 `(project_id,event_time,record_id)` 与 `(event_time,record_id)`，按真实过滤与排序选择；按 session_id 的归属更新另有索引。索引命名与最终 schema 统一。
- 用稳定 `(event_time,record_id)` 游标进行前后页查询，游标绑定 ledger/classification/claim 依据；依据改变应明确要求刷新，避免翻页遗漏或重复。
- 可用性要按原规则查询：record_key 同一身份、scope_key 跨粒度、semantic_key 疑似重建、legacy_holds 及内部重叠；保留原因优先级与专用自身批次豁免（`claims.py:175`）。
- 当前 `scope_key` 不含 request_model/pricing_model（`claims.py:29`），迁移不能擅自收窄旧占用覆盖来释放用量；事实覆盖分组可更细，旧占用仍保守接续。
- 利用既有 claims 的 key/scope/semantic 索引，用 EXISTS/NOT EXISTS 或候选键临时表查询相关项；不要每次全表 fetchall 后在 Python 建字典。
- 所有权一对多关联可能使一条用量重复出现：先按用量唯一身份确定可用/排除集合再汇总；所有者解释只为当前页或受影响组展开。
- 常规统计使用日/项目/模型派生表；事实修订、目录/人工归属、覆盖确认和 claim 变化都必须更新对应范围。不能只在同步后更新统计。
- 修改当前批次的“排除自身占用”属于独立查询上下文；不能把全局 available 统计直接复用为编辑预览，也不能把自身成员简单全加回。
- 配置读取只拉项目/目录及当前候选的 overrides。目录规则改动重算受影响 session/路径范围，大范围重算可 staging 后发布，不在每次列表请求遍历全部目录。
- 预览只缓存条件、版本依据、结果摘要和选择标识，不缓存全量行列表；需要冻结时通过本地索引验证并保存成员版本。
- 新占用检查的 SQL 实现应与纯 `claims.evaluate` 用随机/边界夹具做语义对照；后者可保留为小规模参考，不作为生产全量入口。

### 8. 读写连接、发布和运行时门禁

当前整个 Store 的单连接/RLock 会串行化读取（`storage.py:55`、`:104`），单纯设置 WAL 不会自动解除这层阻塞。

建议 Store 继续统一管理一个序列化写入口、请求级只读连接和关闭生命周期。读取使用短事务；同步 staging 与大文件生成不长期持有写锁。事实、派生统计、成功 run 及发布序号在提交点一致生效，旧读取继续看到旧已发布状态。

新报销可先冻结成员版本并在写事务外流式构建临时包，提交前在 BEGIN IMMEDIATE 中重检 ledger/classification/claim/generation，原子登记原包与占用；失败丢弃未发布尝试，不能替用户静默缩小选择。相同幂等 key 重放和双进程争用规则仍成立。

WAL 的 checkpoint 由同一写协调入口管理，限制长读事务，退出时显式关闭所有连接。数据库保存在本机资料目录，不设计网络共享读写。

必须先验证实际 `sqlite3.sqlite_version` 含 WAL-reset 修复，再启用多连接 WAL。官方记录修复为 3.51.3+，部分回补为 3.44.6/3.50.7；需按具体修复分支核对，不能仅看“Python 3.12+”。主会话只读探测的 host SQLite=3.46.1 不能作为这项发布的安全基线。Linux 与原生 Windows 分别记录运行时，必要时只调整任务隔离构建运行时，不修改全局环境。

依据：[SQLite WAL](https://www.sqlite.org/wal.html) 的并发、checkpoint 与第 11 节 WAL-reset 说明。本段是实施前技术门禁，不是已完成的修复或新的产品范围问题。

### 9. 流式新报销材料与兼容

- 当前 `_validate_capture` 会重读全量旧快照，新的台账报销入口应改为按选中事实版本验证；旧依据仍可复查。
- 新报销成员行式冻结，保存每条事实版本/归属依据、来源/同步依据及选择摘要；新 manifest 应明确格式版本，不伪造单一原 capture 身份。
- CSV、manifest 的 members 数组、ZIP 和 HTTP 下载都需流式写读；只改 CSV 但仍构造完整成员 JSON/ZIP bytes 不能通过内存验收。
- 仍保留四文件、BOM、公式保护、HTML 转义、精确金额与文件哈希；流式计算摘要及冻结哈希必须有确定顺序和格式版本。
- 旧 ZIP 下载分块校验并回传原字节，不重新生成。旧 frozen_hash 与业务幂等结果按原协议核对。
- 原报销与当前事实差异可按冻结成员版本和当前版本关联查询，不加载全部历史报销 JSON 扫描；差异提示不释放占用或修改旧金额。

### 10. 性能工作负载与建议验收门槛

以下是供最终评审的建议，不是已有性能承诺或测量值。

合成数据采用固定 seed，规模 10 万/100 万/1000 万，时间跨度 5 年，至少 100 项目、20 模型，另有 50% 数据集中单项目的倾斜组、同秒多记录、未归属、1% 修订、30% 已占用和少量 holds。正确性另设极端金额、Token、粒度覆盖与重建样例，不依赖随机碰撞。

| 工作负载 | 建议门槛与必须记录的条件 |
| --- | --- |
| 首/中/深位置游标页，50 行，全部及可用视图 | 热态 P95：百万级 ≤300ms、千万级 ≤500ms；进程冷启动后查询 ≤1.5s |
| 项目月统计、全年统计及全部项目月统计 | 热态 P95 ≤1s；使用统计表，不随全库明细数量直接线性增长 |
| 固定来源窗口的不变重同步 | 新事实/修订行增加数为 0；不生成整库重复材料；区分 staging/run 元数据开销 |
| 本地台账 100 万变 1000 万，来源窗口不变 | 同步耗时比目标 ≤1.5，记录来源读取、比对、写入、派生、发布各段时间 |
| 追加 1 万明细、修订 1000 行并同时查询 | 前台查询 P95 ≤1s；无静默漏行、重复和未发布数据可见 |
| 导出选中 10 万/100 万条，含 manifest 与下载 | 额外峰值 RSS 目标 ≤128MiB；完整对账且不构造完整 ZIP bytes |
| 相同查询在 100 万/1000 万台账运行 | 查询额外峰值 RSS 差值目标 ≤64MiB；记录数据库、索引、修订、WAL、旧对象、证据包各自大小 |

固定来源窗口模拟 CCS 当前可保留的数据；千万级台账可以由多次历史采集累积生成，不能把合成台账播种成功描述为单次来源导入支持千万行。上游来源限制与本地容量分开验收。

每项先预热 10 次，再至少测 100 次报告 P50/P95/max；新进程/新连接测量单独标为“进程冷”，没有受控清除 OS 缓存就不称为磁盘冷。记录 Windows 版本、CPU/RAM/磁盘、本地 SQLite/Python/程序版本、页大小、缓存、WAL/synchronous 设置、数据分布和数据库体积。不能通过清除宿主全局缓存影响用户其他工作。

保存 EXPLAIN QUERY PLAN，确认限定列表与相关占用检查使用有效索引，记录读取/返回行数；统计查询只访问派生范围。不要只检查“存在索引”，也不要硬编码某个 SQLite 版本的计划文本。首次回填、全范围规则重算另测耗时/资源，不与日常热查询混为一项。

### 11. 相关规范与验证映射

- `.trellis/spec/backend/usage-evidence-contract.md`：金额、Token、归属、独占、生命周期、冻结材料与本机安全。
- `.trellis/spec/backend/database-guidelines.md`：连接所有权、BEGIN IMMEDIATE、迁移、备份和不可变对象；本次新连接策略须在实施后同步规范。
- `.trellis/spec/backend/quality-guidelines.md`：Ruff、strict mypy、自动测试及 Windows 原生交付门禁。
- `.trellis/spec/frontend/local-web-contract.md`、`state-management.md`：新分页、预览失效、同步失败后继续本地查询和下载状态。
- 延续 `tests/test_storage.py:26`、`:41`、`:55` 的复用/修订/移除原件恢复，增加行级台账与跨 capture 候选验证。
- 延续 `tests/test_claims.py`、`test_claim_concurrency.py:151` 的规则及失败原占用保留，加入 SQL 候选路径与并发同步/保存。
- 延续 `tests/test_migrations.py:57`、`:119`、`:154` 的旧 writer、损坏回滚及 WAL 备份，增加 schema2 已打开连接和原包字节核对。

## Caveats / Not Found

- 尚待用户决定历史 capture 是否并入台账；不应由技术实现默认选定所有冲突版本。
- 本研究未读取真实应用资料，未知实际旧 capture 的来源链、冲突数量、材料大小与目标 Windows 硬件；这些不影响保守契约，但不能声称迁移已验证。
- 未实施新表、读连接、精确聚合或流式导出；性能表仅为建议验收门槛，不能作为发布结论。
- 新报销协议、单个超大旧 capture 的有界解析和多连接协议守卫需在实施前完成小型技术验证，失败应回到设计处理，不以降低精度或放松占用通过验收。
