# SQLite 与持久化

## 所有权与连接

本地应用 schema3，来源 CCS schema23，职责分别在 [storage.py](../../../src/aha/storage.py)、[migrations.py](../../../src/aha/migrations.py)、[sources.py](../../../src/aha/sources.py)。新库创建，不运行旧试用业务迁移；旧资料须按清单工具先保全用量再重建。

Store 检查实际 sqlite3.sqlite_version_info：3.51.3+，或核实的3.50.7/3.44.6回补分支。不要放宽为“所有大于3.44的版本”。测试和打包使用任务隔离运行时，不修改全局 SQLite。

应用库由一个序列化 writer 与 Store.read_connection 的短时只读连接组成，外键约束与自定义精确聚合在每个连接配置。RLock 只管理同进程 writer，跨进程依靠 SQLite 事务/约束；不能仅设置 WAL 就宣称读请求不再被 Python 锁阻塞。

来源用同一 `mode=ro/query_only/trusted_schema=OFF` 读事务分块读取允许表；DELETE 模式可能延迟源写提交，WAL 中仍可能 busy。墙钟、锁等待、progress handler、块间取消均有界。不用 live immutable，不复制主文件忽略 WAL，不替源库切 journal_mode 或加索引。

## 查询、金额与派生表

- 数值用参数绑定，动态表/列仅来自代码允许集合。
- 原成本与 Token 文本保持精确；decimal_sum/integer_sum 返回规范字符串，避免 SQLite SUM 溢出/浮点误差和自定义聚合返回超 int64。
- 当前事实是 usage_records，内容修订是 usage_versions；新旧指针、来源观察和候选核对分开。未变化同步只增加必要 run 摘要。
- 可用性存当前事实派生列，日统计在 daily_usage_stats；规则、元数据、覆盖、成本或占用变化都更新受影响范围。
- 列表使用 event_time/record_key 组合游标与项目/可用性索引；claims 按 key/scope/semantic 查相关候选，不读全表构建 Python 字典。
- 先检查 EXPLAIN 与返回行/访问范围，再优化；基准播种可以延迟二级索引，但测量前须恢复完整生产索引与连接设置，不能以删除索引后的不同模型冒充产品。

## 暂存、事务与文件发布

Store._transaction 使用 BEGIN IMMEDIATE，并对 BaseException 回滚。来源读取、暂存准备、大文件生成不长期占据全局 writer 锁。一次发布关联事实、统计、data/classification/claim 依据和成功状态；未核实缩水 needs_review 不推进最近成功时间。

create_batch 在最终事务内重检目标 generation/active_version、数据/归属/claim、冲突、幂等与完整冻结选择。失败保留原有效版/占用，不从原预览静默扣掉冲突成员。frozen_basis 以有效冻结成员为依据，不能被无关数据版本变化误阻断。

revision_members 与 batch_events 有不可变保护。候选成员和四文件流式生成，publish_file 原子落位；数据库只登记成功材料。物理文件名保持短，用户下载名独立；已有材料损坏拒绝，不重新生成。文件与数据库异常须有回滚/未登记材料清理测试。

## 试用资料重建

[scripts/rebuild_trial_data.py](../../../scripts/rebuild_trial_data.py) 只有 inspect/extract/apply/import-history 四种明确动作。inspect 默认只读；extract 验证历史压缩对象的内容、版本、允许投影并保全；apply 需要匹配平台/data-dir 的清单、全量校验备份、完整历史输入和停止的旧进程。

保护路径不可从 manifest 移除。只处理已识别且指纹未变化的 aha 试用文件；未知文件、CCS 原件/sidecar、未保全用量保留。拒绝穿越、符号链接、嵌套输出/备份、新业务 schema、文件集合变化；删除失败从校验副本恢复。不递归删除父目录或按数据库扩展名清扫。

## 检查

覆盖 test_storage/test_sources 的一致读取、成功进度和重启；test_migrations 的新库/旧库拒绝/回滚；test_claim_concurrency 的独立连接/进程竞争；test_rebuild_trial_data 的清理边界及失败恢复。Windows 必须显式关闭 SQLite/文件句柄，不能依赖 GC 才释放临时目录。

## 实施检查补充约束

- 日/月派生统计按相同project/model/kind/state精确口径，在事实、分类、覆盖和占用变更的同一事务更新。完整自然月读月表，首尾非完整月份读日表，段间不能重叠。聚合不经过REAL；冻结主体仍按其完整成员。
- keyset除tuple严格比较外，还须显式收紧event_time标量范围。执行计划和VM工作量应证明直接seek，不能仅凭SQL中存在游标断言深页恒定。
- 源事务内staging等待本机writer必须有界并检查取消；SQLite progress handler不能中断Python RLock等待。双线程测试需证明本机长写不延长CCS DELETE读锁。
- 同源新key的旧语义成员缺席当前完整staging时才提示身份重建；本轮并存的同秒同Token不同key请求不能误合并。rollup代表量下降单独以已确认观察基线核对，不将降价误判为重建。

源查询游标必须在异常/取消路径显式关闭（例如`contextlib.closing`）；只关闭Connection不保证异常traceback持有的活动Cursor立刻释放DELETE读锁。测试应观察独立源writer实际提交，不只检查connection.close被调用。

状态卡的全局计数/代表量/待核对数从monthly_usage_stats聚合，日期上下界用日表索引首尾各seek一条；不要在一个MIN/MAX/SUM查询中隐式扫描全日表。排除说明的前100组应使用排除态partial索引及一致的day/model/state分组顺序；LIMIT不等于只访问100组，要用VM工作量对比全范围与前缀范围。

相关子查询还要验证同一scope内的密度增长。将`c.scope_key=r.scope_key AND (c.kind='rollup' OR r.kind='rollup')`写在一个分支，可能使明细也扫描该scope的全部明细占用；应按粒度拆成可精确使用`(scope_key,kind)`的分支。覆盖、记录及来源核对也分别使用其索引范围，避免对每条事实扫描全部开放事项。可用性刷新、目标报销重选及列表占用说明须检查同类路径；用同日/同模型的密集事实和占用/核对事项翻倍对比VM工作量，不能只测试均匀分散的小样本。
