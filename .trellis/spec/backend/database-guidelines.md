# SQLite 与持久化

## 所有权与连接

本地应用 schema4，外部 CCS 支持结构版本 23、24、25、26，内部规范化投影仍为 23；版本与指纹合同见 [CCS 来源兼容](./ccs-source-compatibility.md)。职责分别在 [storage.py](../../../src/aha/storage.py)、[migrations.py](../../../src/aha/migrations.py)、[sources.py](../../../src/aha/sources.py)。schema3 先完整备份再无损升级，结构、失败回滚与旧备份独立恢复见[项目归属合同](./project-association-contract.md)。旧试用schema1/2仍须单独保全再重建，不能对schema3/4误用试用清理工具。

Store 检查实际 sqlite3.sqlite_version_info：3.51.3+，或核实的3.50.7/3.44.6回补分支。不要放宽为“所有大于3.44的版本”。测试和打包使用任务隔离运行时，不修改全局 SQLite。

应用库由一个序列化 writer 与 Store.read_connection 的短时只读连接组成，外键约束与自定义精确聚合在每个连接配置。RLock 只管理同进程 writer，跨进程依靠 SQLite 事务/约束；不能仅设置 WAL 就宣称读请求不再被 Python 锁阻塞。

来源用同一 `mode=ro/query_only/trusted_schema=OFF` 读事务分块读取允许表；DELETE 模式可能延迟源写提交，WAL 中仍可能 busy。墙钟、锁等待、progress handler、块间取消均有界。不用 live immutable，不复制主文件忽略 WAL，不替源库切 journal_mode 或加索引。

## 查询、金额与派生表

- 数值用参数绑定，动态表/列仅来自代码允许集合。
- 原成本与 Token 文本保持精确；decimal_sum/integer_sum 返回规范字符串，避免 SQLite SUM 溢出/浮点误差和自定义聚合返回超 int64。
- 当前事实是 usage_records，内容修订是 usage_versions；新旧指针、来源观察和候选核对分开。未变化同步只增加必要 run 摘要。
- 可用性存当前事实派生列，日统计在 daily_usage_stats；生效归属、覆盖、成本或占用变化更新受影响范围。旧模式的普通配置保存不重写已接受历史关系；新的目录整体预览确认在同一事务保存配置、模式、已有成员归属和统计，不能先写目录再部分迁入。显式追溯、人工归属和恢复与统计同事务提交。
- 列表使用 event_time/record_key 组合游标与项目/可用性索引；claims 按 key/scope/semantic 查相关候选，不读全表构建 Python 字典。
- 先检查 EXPLAIN 与返回行/访问范围，再优化；基准播种可以延迟二级索引，但测量前须恢复完整生产索引与连接设置，不能以删除索引后的不同模型冒充产品。

## 暂存、事务与文件发布

Store._transaction 使用 BEGIN IMMEDIATE，并对 BaseException 回滚。来源读取、暂存准备、大文件生成不长期占据全局 writer 锁。一次发布关联事实、统计、data/classification/claim 依据和成功状态；未核实缩水 needs_review 不推进最近成功时间。

create_batch 在最终事务内重检目标 generation/active_version、数据/归属/claim、冲突、幂等与完整冻结选择。失败保留原有效版/占用，不从原预览静默扣掉冲突成员。frozen_basis 以有效冻结成员为依据，不能被无关数据版本变化误阻断。

revision_members 与 batch_events 有不可变保护。候选成员和四文件流式生成，publish_file 原子落位；数据库只登记成功材料。物理文件名保持短，用户下载名独立；已有材料损坏拒绝，不重新生成。文件与数据库异常须有回滚/未登记材料清理测试。

## 试用资料重建

[scripts/rebuild_trial_data.py](../../../scripts/rebuild_trial_data.py) 只有 inspect/extract/apply/import-history 四种明确动作。inspect 默认只读；extract 验证历史压缩对象的内容、版本、允许投影并保全；apply 需要匹配平台/data-dir 的清单、全量校验备份、完整历史输入和停止的旧进程。

保护路径不可从 manifest 移除。只处理已识别且指纹未变化的 aha 试用文件；未知文件、CCS 原件/sidecar、未保全用量保留。拒绝穿越、符号链接、嵌套输出/备份、新业务 schema、文件集合变化；删除失败从校验副本恢复。不递归删除父目录或按数据库扩展名清扫。

`ensure_not_protected(path, protected)` 在判断相等或父子关系前，必须将被检查路径和每一条保护路径都规范化为resolve后的路径；不能只规范化一侧。`trial/../trial` 等等价写法仍属于同一个保护目录，必须在备份或删除前以ValueError拒绝。回归应同时断言原文件指纹未变且备份尚未创建，不只观察异常类型。

## 检查

覆盖 test_storage/test_sources 的一致读取、成功进度和重启；test_migrations 的新库/旧库拒绝/回滚；test_claim_concurrency 的独立连接/进程竞争；test_rebuild_trial_data 的清理边界及失败恢复。Windows 必须显式关闭 SQLite/文件句柄，不能依赖 GC 才释放临时目录。

## 实施检查补充约束

- 日/月派生统计按相同project/model/kind/state精确口径，在事实、分类、覆盖和占用变更的同一事务更新。完整自然月读月表，首尾非完整月份读日表，段间不能重叠。聚合不经过REAL；冻结主体仍按其完整成员。
- keyset除tuple严格比较外，还须显式收紧event_time标量范围。执行计划和VM工作量应证明直接seek，不能仅凭SQL中存在游标断言深页恒定。
- SQLite 来源先写白名单临时投影，释放源连接后再进行本地规范化/暂存；本机 writer 争用和取消仍有界。双线程测试须证明本地慢暂存开始前 CCS DELETE writer 已可提交，详见下方两阶段合同。
- 同源新key的旧语义成员缺席当前完整staging时才提示身份重建；本轮并存的同秒同Token不同key请求不能误合并。rollup代表量下降单独以已确认观察基线核对，不将降价误判为重建。

源查询游标必须在异常/取消路径显式关闭（例如`contextlib.closing`）；只关闭Connection不保证异常traceback持有的活动Cursor立刻释放DELETE读锁。测试应观察独立源writer实际提交，不只检查connection.close被调用。

状态卡的全局计数/代表量/待核对数从monthly_usage_stats聚合，日期上下界用日表索引首尾各seek一条；不要在一个MIN/MAX/SUM查询中隐式扫描全日表。排除说明的前100组应使用排除态partial索引及一致的day/model/state分组顺序；LIMIT不等于只访问100组，要用VM工作量对比全范围与前缀范围。

相关子查询还要验证同一scope内的密度增长。将`c.scope_key=r.scope_key AND (c.kind='rollup' OR r.kind='rollup')`写在一个分支，可能使明细也扫描该scope的全部明细占用；应按粒度拆成可精确使用`(scope_key,kind)`的分支。覆盖、记录及来源核对也分别使用其索引范围，避免对每条事实扫描全部开放事项。可用性刷新、目标报销重选及列表占用说明须检查同类路径；用同日/同模型的密集事实和占用/核对事项翻倍对比VM工作量，不能只测试均匀分散的小样本。

## SQLite 同步两阶段合同

### 1. 范围

修改 SQLite 同步、临时投影、超时或取消时适用。本地处理耗时不得挤占源库短时读取预算，也不得继续持有源 DELETE 读锁。

### 2. 签名与所有者

`sources.scan_sqlite(path, sink, *, cancel=None, timeout=None)` 保持来源唯一适配入口；`sync.sync_sqlite` 编排快照与本地回放，`_Stager` 负责规范化/暂存，`Store._staging_transaction(check, processing_deadline=None)` 管理有界本地写事务；`sync._recover_failed_runs(store)` 在开始新run前独立提交失败/过期运行的恢复。

### 3. 数据与时间合同

- 源阶段仍在同一只读事务扫描三张允许表，5秒预算、每表行数与512MiB允许投影上限保留；sink仅写本轮独占临时文件，不做规范化或应用库写入。
- 使用资料目录 `temporary` 下的 `TemporaryFile`，逐行写入和回放表标识及允许字段；不读配置、不执行SQL/pickle、不构造全量列表。封装开销受有限表数/行数约束。
- scan完整返回并关闭源连接后，才设置独立120秒本地回放/暂存预算。最后一批flush与结束检查均在预算内，随后清除该预算再进入既有元数据/原子发布。
- 250ms本地writer等待上界、精确数值与身份计算不变；SQL备份/历史导入不套用SQLite源快照限制。
- 源progress handler、块间及本地行/批检查须同时观察Store退出和显式cancel；传入显式Event不得屏蔽程序退出。
- `source_projection_and_staging_ms`保留总计，`source_scan_ms`和`local_staging_ms`说明分段耗时；不以临时路径替代来源身份/指纹。
- 临时文件在成功、异常和取消路径关闭并删除；失败不发布半批次或推进成功时间，不改旧事实/占用/原包。
- 本地库可写时在有界写事务内将本轮标failed并清stage/pricing；库被占用时立即返回原安全错误，在Store独立小锁保护的内存保存run→安全错误，不能无限等待或谎称持久清理完成。只有恢复事务提交后才移除内存意图。
- 下次同步先独立恢复已知失败及过期租约，再做active检查和新run创建，两次取得writer均有界。恢复提交不能被后续active拒绝回滚；先固定过期run集合，再精确标记和清两张表，保护未过期的其他有效运行。
- 跨重启缺少内存失败依据时，继续沿用120秒租约；未过期可能暂时sync_in_progress，到期回收stage/pricing。当前HTTP job优先显示已经知道的失败，不用暂时未能更新的数据库running覆盖它。无需额外持久文件、schema或后台服务。

### 4. 错误矩阵

| 条件 | 结果 |
| --- | --- |
| 源锁忙或真正源读取超预算 | `source_busy` |
| 本地回放/暂存超120秒 | `sync_processing_timeout`，明确本地处理超时 |
| 两种取消信号任一置位 | `sync_cancelled` |
| 本地writer争用 | `store_busy`，等待有界 |
| 失败清理也遇到writer争用 | 先返回原错误，解除占用后同Store下次同步前恢复；重启遵守既有租约 |
| 临时文件创建、写入、回放或空间失败 | 安全同步失败，不误报源库忙，不泄露路径 |

### 5. 正常、基础、错误场景

- 正常：源扫描在5秒内结束，本地处理超过5秒仍成功；源writer在本地处理期间可提交。
- 基础：重复读取同一投影不增长事实/内容版本，未成功同步仍可查询旧资料。
- 错误：只把源限时调大、在源事务内等待应用库、未纳入尾批预算、取消时留下临时文件。

### 6. 必需验证

真实独立源writer在慢暂存期间成功提交，且本轮仍使用原快照；覆盖DELETE/WAL一致性、真源超时、本地超时、双取消信号、创建/短写/回放失败、末批失败、临时文件清理和旧成功时间/事实/原包不变。另需覆盖本进程/外部writer一直持锁时有界失败、解除占用立即重试、恢复回滚不丢内存意图、过期租约清两表且不误清有效run、恢复提交不被后续竞争拒绝回滚。原生当前规模测试须记录实际阶段耗时，不能只使用mock推定成品性能。

### 7. 错误与正确做法

错误：`scan_sqlite(path, stager.add)`将本地规范化和FULL提交计入源预算。正确：源扫描只写受限临时投影，关闭源连接后，逐行调用同一`stager.add`并在独立本地预算内完成最终flush。
