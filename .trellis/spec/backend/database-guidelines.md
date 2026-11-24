# SQLite 与持久化

## 所有权与连接

本地应用 schema 5，内部规范化用量投影仍为 23。职责分别在 [storage.py](../../../src/aha/storage.py)、[migrations.py](../../../src/aha/migrations.py) 和 [native_sync.py](../../../src/aha/native_sync.py)。schema 3/4 升级前先完整备份，应用 schema 1/2 仍需单独保全后受控重建。运行时实际 SQLite 必须通过 `sqlite_wal_safe`。

连接统一开启 foreign keys、trusted schema 保护并注册精确聚合。正常运行采用 WAL，Store 管理同进程写者，跨进程依靠 SQLite 事务和约束。读连接只读，使用独立快照。

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

覆盖 test_native_sync/test_storage 的原生发布、一致进度和重启；test_migrations 的新库/旧库拒绝/回滚；test_claim_concurrency 的独立连接/进程竞争；test_rebuild_trial_data 的清理边界及失败恢复。Windows 必须显式关闭 SQLite/文件句柄，不能依赖 GC 才释放临时目录。

## 实施检查补充约束

- 日/月派生统计按相同project/model/kind/state精确口径，在事实、分类、覆盖和占用变更的同一事务更新。完整自然月读月表，首尾非完整月份读日表，段间不能重叠。聚合不经过REAL；冻结主体仍按其完整成员。
- keyset除tuple严格比较外，还须显式收紧event_time标量范围。执行计划和VM工作量应证明直接seek，不能仅凭SQL中存在游标断言深页恒定。
- 原生日志分块只读解析，暂存允许投影后进入本地写入。写者争用和取消仍有界。
- 同源新key的旧语义成员缺席当前完整staging时才提示身份重建；本轮并存的同秒同Token不同key请求不能误合并。rollup代表量下降单独以已确认观察基线核对，不将降价误判为重建。

SQLite 查询游标和连接在异常、取消时显式释放，Windows 不依赖 GC 清理临时文件。

状态卡的全局计数/代表量/待核对数从monthly_usage_stats聚合，日期上下界用日表索引首尾各seek一条；不要在一个MIN/MAX/SUM查询中隐式扫描全日表。排除说明的前100组应使用排除态partial索引及一致的day/model/state分组顺序；LIMIT不等于只访问100组，要用VM工作量对比全范围与前缀范围。

相关子查询还要验证同一scope内的密度增长。将`c.scope_key=r.scope_key AND (c.kind='rollup' OR r.kind='rollup')`写在一个分支，可能使明细也扫描该scope的全部明细占用；应按粒度拆成可精确使用`(scope_key,kind)`的分支。覆盖、记录及来源核对也分别使用其索引范围，避免对每条事实扫描全部开放事项。可用性刷新、目标报销重选及列表占用说明须检查同类路径；用同日/同模型的密集事实和占用/核对事项翻倍对比VM工作量，不能只测试均匀分散的小样本。

## 原生同步事务

1. 本轮每端将允许字段写入独占暂存连接，源文件、解压和 WSL 资源作业结束即关闭。物理游标和逻辑事件分别暂存。原始行不存本地。
2. `_Stager` 复用 120 秒本地暂存预算和分批心跳。`Store._staging_transaction` 对 Python 写锁和 SQLite busy 的等待总计有界，检查显式取消与程序退出两种信号。源读取时间和本地 staging 时间独立记录。
3. 发布事务重新检查租约和取消，一次提交事实、观察证据、游标、核对、归属、日/月统计和同步终态。物理增量行数不参加历史全量快照缩水判定。
4. 本库可写时失败标记和 staging 清理同事务完成。另有写者占用时立即返回本轮安全错误，同一 Store 记下待清理意图。下一次先独立恢复失败及过期租约，再检查有效作业，不能被随后拒绝新作业回滚。活动租约不得被误回收。
5. `test_sync_timeout`、`test_native_sync` 检查 writer 等待、退出和显式取消、失败不发布进度、清理、过期回收以及重试后的原历史和合计。
