# v0.3.0 全范围检查与自修记录

检查角色：`trellis-check`；2026-10-28。范围为本任务 PRD/design/implement、check.jsonl 与当前相关规范；没有调度其他代理、操作用户资料、构建 EXE、修改 README/spec 或执行大规模基准。性能及成品验证由主会话独立完成。

当前收尾状态由主会话记录在[最终验收](../verification.md)：实际重建、桌面交付及原生验收已完成；剩余百万压力测试已按用户要求取消并释放空间。下文保留检查时的诊断和交接时间线，不表示仍有测试运行。

## Findings (fixed)

### 1. 深游标没有实际定位到游标时间

- 文件：`src/aha/queries.py`、`tests/test_analysis.py`。
- 证据：旧 SQL 虽含二元组比较，SQLite 仍以原日期起点 SeekGE，逐行过滤此前95%历史。
- 修复：next 收紧已有标量下界到游标秒，previous 收紧已有上界到游标秒后一秒；二元组继续保障同秒多 key 的严格次序。
- 回归：5000条合成事实的深页/反向页、同秒、日期边界，检查返回身份及 VM 指令上限，不用固定耗时或固定执行计划文本断言。

### 2. 精确统计与进程冷查询的成本

- 文件：`src/aha/decimal_sql.py`、`src/aha/queries.py`、`src/aha/ledger.py`、`src/aha/migrations.py`。
- 证据：百万预跑的全期统计涉及31万余日投影、225万整数 UDF 回调和31万金额 UDF 回调；冷查询超目标。
- 修复：精确向量聚合、最多六组的内部状态/粒度聚合，避免全期 GROUP BY sorter；规范固定小数直接拆系数与尺度，指数仍有精确路径。不降低金额或大整数精度。
- 经主会话批准加入月派生表 `monthly_usage_stats` 与项目/月索引。完整月份读月表，两端非完整月份读日表，两类范围互斥；每日视图继续读真实日表，模型汇总可使用月/日拼接。
- `refresh_daily` 与受影响月份的 `refresh_monthly` 同事务完成；去掉超过2000 scope 就重建全历史日统计的分支。显式全量重建仍可用。
- 回归：跨月、闰日、首尾整日、超 int64 Token、精确金额、available/all、目标修订、占用/作废、人工归属/成本修订与覆盖确认；年0001/9999统计边界。
- 这些修复不是性能验收结论；正式百万/千万、物理盘/NTFS、冷进程/RSS结果见主会话 verification。

### 3. 同幂等请求的冻结前竞争

- 文件：`src/aha/batches.py`、`tests/test_claim_concurrency.py`。
- 证据：首轮全套130项中，真实跨进程相同 key 竞争一方已成功，另一方偶发 availability_changed。
- 修复：初次重放读取与冻结开始之间，另一进程可能已经提交同请求；冻结抛 AppError 时重新读取持久幂等结果，存在匹配结果则校验原包并重放，否则保留原错误。最终事务重检不变。
- 回归：确定性地在重放检查后、冻结前提交竞争者；原有双进程测试继续通过。

### 4. 同一来源等量重建可绕过身份核对

- 文件：`src/aha/sync.py`、`tests/test_storage.py`。
- 证据：同一 source/live 先 old-key，随后相同会话/时间/Token 但仅 new-key，旧实现得到两条可用消费且无核对事项。
- 修复：保留不同来源候选判断；同源语义相同旧 key 已不在当前完整 staging 时，也生成身份候选。当前同轮同时存在旧/新 key 时保留两个真实请求，不自动合并。
- 回归：同源等量重建、同轮共存、备份/同源确认别名后补价与原 claim/ZIP、失败和取消不发布候选。原始事实均保留。

### 5. 日汇总退回未被识别

- 文件：`src/aha/sync.py`、`src/aha/migrations.py`、`tests/test_storage.py`。
- 证据：同源 rollup request_count 100降为10，旧实现仍 completed、推进成功时间并把当前值直接改为10。
- 修复：来源 rollup 行数减少，或同源同 key 的代表请求量减少，均走 needs_review，保留当前旧事实与成功时间并保存修订候选。仅成本下降且请求数不降仍是正常来源修订。
- 新增 `source_rollup_observations` 保存每个 source/key 最近已提交观察的代表量，仅数值变化写入。配合开放 source case 和明确确认基线，避免保留旧事实100后与已确认的新基线10永久重复核对；失败事务不会推进该观察。
- 回归：纯汇总、混合来源、等 key 代表量下降、行数减少、费用修正、确认新基线后的继续同步。

### 6. 本地 writer 等待和异常游标可延长 CCS DELETE 读锁

- 文件：`src/aha/storage.py`、`src/aha/sync.py`、`src/aha/sources.py`、`tests/test_storage.py`。
- 修复：staging 使用单独的有界事务入口，Python writer RLock 轮询不超过20ms、配置总等待250ms，并以来源剩余期限进一步缩短。SQLite busy_timeout 在剩余预算内进一步设100ms保守上限，给Windows busyhandler/调度留余量，结束后恢复；普通业务事务的等待方式不变。循环检查取消/来源期限。
- 确定性测试还发现：异常 traceback 可持有未结束的 SELECT cursor，connection.close 后仍保留 SQLite 读锁。来源每个 cursor 现通过 closing 显式关闭，再 rollback/close 连接。
- 回归：真实 DELETE 模式源+被占用的本地 Python writer，超时和取消均释放源读锁；独立 SQLite writer 阻塞也在预算内退出、恢复原 busy_timeout。保持异常对象及后台清理等待时，源 writer 设置1000ms busy_timeout，仍在本地writer持锁期间成功提交，旧账和上次成功时间不变。测试分别观测staging等待及writer成功，不将writer自身刷盘时间当作读锁等待。

### 7. 目标修订的可用/排除摘要包含自身占用

- 文件：`src/aha/queries.py`、`tests/test_analysis.py`。
- 证据：原 matched1/available1/excluded1，把目标自身的可用成员又显示成排除。
- 修复：排除摘要按目标上下文精确差分，说明组使用实际不可用补集，行式权威选择和保存防重不变；补全目标统计的 unpriced_count。自豁免使全局 pending 重叠可用时，只把该已可用部分补入目标 matched，避免负排除。all 只读与 available 采用同一可用性依据。
- 回归：全自身占用排除0、自己与他人混合仅排别人、精确成本/大整数、未定价，以及自豁免全局重叠无负数。

### 8. 基准适配和安全计时

- 文件：`scripts/benchmark_ledger.py`、`src/aha/sync.py`。
- `--query-only --refresh-derived` 仅在已有隔离 marker 的夹具补建月表与来源观察表，并使用生产 refresh_monthly；不重播事实或运行期迁移用户库。
- run 的 timings_ms 包含来源投影/暂存、元数据、当前版本比较、派生、提交前发布。比较时间包含取得发布锁的等待，publish_before_commit 明确不含 COMMIT；不是精确到操作系统级别的追踪。
- unchanged_sync 保留阶段 P50/P95；incremental.run 保留阶段原值。
- 1000条脚本 smoke：查询/冷进程、重复2次无新版本、新增10+修订10、30成员真实导出与SHA通过；显式补建入口通过。这仅验证脚本链路，不代表大规模门槛。

### 9. 实际 HTTP 冷入口仍扫描全期日统计

- 主会话的实际 OneFile/NTFS百万样例首个全5年分析为2516.6ms，而核心冷探针约660ms；代码审查确认状态入口仍有三次全期日统计扫描，排除说明虽LIMIT100仍全范围GROUP/sort。本项按R9实际失败证据继续优化。
- 文件：`src/aha/queries.py`、`src/aha/migrations.py`、`scripts/benchmark_ledger.py`、`tests/test_analysis.py`、`tests/test_migrations.py`。
- `ledger_status` 现用月投影一次按kind聚合真实行数、已核实代表量及待核对数；覆盖起止日分别用日表索引首/尾seek，不用带SUM的MIN/MAX全扫描。
- 新增排除态部分索引 `stats_excluded_day_model_state`、`stats_excluded_project_day_model_state`；谓词为state!='available'，GROUP/ORDER对齐day/model/state。100个说明组按日期优先流式聚合，保留状态/模型分组含义及精确整数计数；目标修订仍查实际不可用补集，保持自身豁免语义。
- fresh初始化及benchmark --query-only --refresh-derived均调用initialize_query_indexes补建，不重播事实；保留主会话对cold_definition测量范围的文字修正。
- 65,772条日投影/2,160条月投影回归：状态54,600 VM指令，结果与独立参考一致；100组排除说明在全5年与首月范围工作相同（全项目10,800，单项目/未归属5,200指令），包含超int64代表量。不固定毫秒或某版本的计划文本。
- 147项全套当前源码通过：Linux16.415s、Windows45.907s(skip1)。小夹具显式补建入口通过；真实EXE冷HTTP复测仍由主会话执行，VM回归不代替成品性能结论。

### 10. 密集scope的刷新、目标修订与owner说明出现二次扫描

- 主会话报告旧ff版原生千万库大导出结束阶段异常耗时；检查代理未访问该运行库或任务备份，先在独立小型真实Store中复现。旧ff/旧脚本长跑的进度、ZIP和耗时不作为新代码的性能结论。
- 同日/模型、30% detail claims时，200/400/800事实的refresh VM为163900/562100/2064400；原动态kind OR只能按scope检索，逐行遍历同scope的全部detail claims。
- 再加40/80/160个同source revision案例并ANALYZE，VM为478900/1846500/7250800，pending相关OR计划改成逐行SCAN x。
- 修复：coverage/record各走自己的EXISTS；source只预计算open source-case ID集合，并在无open source case时常量短路，避免每行扫描无关revision cases或读取版本来源。保留pending先于identity、再判overlap的优先级。
- overlap等价拆为scope+kind=rollup、当前行为rollup时scope任意kind、semantic精确三个分支；target自身豁免对每个相关分支分别排除目标owner；owner说明以精确关系UNION ALL后做DISTINCT/LIMIT20。
- 首轮仅拆分OR仍未通过密度测试：无/有背景案例refresh200→400为146300→493000、153000→506400，target为81000→305800。实测ANALYZE在单scope/全detail的偏斜下把空rollup范围误估为全表并选择SCAN c。因此只在固定scope分支要求现有`INDEXED BY usage_claim_scope`，不加DDL，不固定测试中的计划文字。
- 最终有意义VM回归使用真实来源/报销/背景备份候选、不同source待核对和额外semantic重叠：200→400事实的refresh无背景案例45600→90100、有背景案例52300→103400；target9200→18300；50行owner说明2600→2600。逐行结果对照既有纯claims.evaluate，并验证双向跨粒度、自身豁免、record/source pending优先与原claim仍保留。
- 本轮相对ff只改ledger.py/queries.py及新增test_availability_scaling.py。batches._refresh的分批调用/日月刷新经隔离检查不呈现这次同scope密度的二次增长，没有无证据重构或扩大写入范围。
- 150项全套通过：Linux21.600s、Windows61.418s(skip1)。Ruff、mypy18源码、diff检查通过。实际千万库的最终完整同步/导出性能仍由主会话以新包验证。
- 证据位于任务私有运行目录：`check-refresh-quadratic-before.json`、`check-refresh-cases-before.json`、`check-queries-density-before.json`、`check-density-split-plan.json`、`check-availability-scaling.log`（首轮失败保留）、`check-availability-scaling-final.log`、`check-density-vm-final.json`和`check-unit-*-dense-final.log`。

## Findings (not fixed)

没有留待主会话裁决的本轮功能问题。AC9 大规模正式数据、AC10 Directory/OneFile/浏览器/Excel/打印，以及实际试用资料重建仍由主会话独立验收；这些不由检查代理的测试通过替代。

### 原生千万库百万成员发布阶段只读诊断及延期实验

- 主会话在最终950版本的原生千万库百万成员导出中观察到ZIP已落位、create尚未返回；py-spy精确定位在`batches.py:863`的`INSERT INTO usage_claims ... SELECT ... FROM billing_candidate.members`。本次检查仅用main及已冻结candidate的`mode=ro/query_only`连接做元数据和EXPLAIN，未执行全量COUNT/ANALYZE/更新，连接约2.335秒后关闭。
- 现场计划为候选单次扫描，逐成员执行claims表和4个索引维护、record_key唯一检查及父revision复合主键外键查询；没有对背景claims的连接或INSERT触发器。此前revision_members同样单次扫描候选并维护表和2个索引/外键。冲突detail_scope计划有一次背景claims扫描并筛选rollup，但位于已通过的落位前阶段，不是当前栈；当前INSERT未发现背景占用数乘选中成员数的SQL遍历。`_revision_result`只读小摘要和主键头信息，不在这里全量计算差异。
- 探针连接默认cache_size=-2000、page_size=4096；源码writer也未主动扩大cache。索引维护与小缓存写放大是待验证解释，不能由EXPLAIN当成实际I/O归因或提速结论。进程累计逻辑I/O不等于物理盘吞吐。只读证据：任务私有`/tmp/aha-ledger-runtime-01a18012/check-live-publish-explain-ro.json`。慢批处理的最终耗时与完整发布/释放仍由主会话记录，不据ZIP存在宣布完成。
- 主会话一度批准NTFS隔离cache配对试验，后为避免主测磁盘竞争要求延期。新建owner目录`C:/Users/djsyw/AppData/Local/Temp/aha-build/20261028-local-ledger-01a18012/check-cache-pair-950-20261028`保留计划脚本及部分夹具；最后准备日志100000背景行/250.709秒，尚未开始默认/32MiB的任何INSERT/DELETE测量。核对完整命令行和解释器后仅停止自有准备PID41964（exit255），主压测PID34196未触碰。`deferred-result.json`、`preparation.log`、`DEFER-TRIALS.json`明确未完成/无缓存结论，不用这次播种耗时充当缓存基准，不再扩量或修改产品。

用户随后明确要求停止百万测试并释放空间。本检查代理再次核对owner及原生进程（PID41964不存在、匹配实验进程0），仅删除自有cache-pair目录的`baseline.sqlite3`（177782784字节）、`baseline.sqlite3-wal`（19644192字节）、`baseline.sqlite3-shm`（65536字节）和`candidate.sqlite3`（16384字节），合计197508896字节（188.359MiB）。保留小型脚本、marker、只读EXPLAIN副本、延期说明、日志及`cleanup-result.json`路径清单；因此上述部分夹具现已移除。未接触root的千万库、任务venv/release、用户aha/CCS及历史保全，也不再运行大规模试验。

## Verification

- Ruff：`src tests scripts` 通过。
- TypeCheck：mypy strict，18个源码文件通过。
- compileall、Node脚本语法、git diff --check通过。
- HTTP入口修复147项全套通过：Linux16.415s、Windows45.907s(skip1)，新增VM与索引补建回归通过。
- 当前密度修复150项全套通过：Linux21.600s、Windows61.418s(skip1)，Ruff全量、mypy18源码、diff检查通过；详见第10项。
- 145项全套已通过：Linux17.253s；Windows65.477s，1项因Windows符号链接权限条件跳过。
- 新增独立SQLite busy回归后146项Linux15.570s通过。Windows最初146项中两项writer总COMMIT时间2.26/2.33秒超过测试自加的1.5秒，诊断记录保留；改为直接验证busy锁生命周期后Windows storage26项4.747s通过。
- 原生最初等待探针：Python锁0.24849秒、取消0.02272秒、SQLite busy分支0.34439秒（配置250ms，有Windows busyhandler/调度开销），三次独立源writer均成功。主会话批准改为SQLite busy上限100ms，Python总250ms及来源5秒预算不变。
- 修正后原生探针：Python锁0.244576秒、取消0.031106秒、SQLite busy分支0.166561秒；三次源writer均在本地writer仍持有时成功提交，原busy_timeout恢复5000。该证据对应当前平台的测量，不承诺硬实时。
- 146项r2全套通过：Linux15.388s、Windows53.669s(skip1)。最后仅进一步缩短staging SQLite等待上限；相关26项存储测试双平台及原生锁探针重新验证：Linux1.199s、Windows8.216s，全部通过。此后Ruff/mypy/compileall/diff检查仍绿。
- 原始日志位于任务私有 `/tmp/aha-ledger-runtime-01a18012/`，包括 `check-unit-*-final-146.log`（保留最初Windows失败）、`check-unit-*-final-146-r2.log`、`check-storage-*-final-cap.log`、`check-source-lock-native-timings-final.json`、`check-benchmark-monthly.json`、`check-benchmark-refresh-derived.json`；HTTP入口后续证据为`check-unit-*-http-entry-final.log`、`check-http-entry-vm.json`、`check-benchmark-refresh-query-indexes.json`。

## 产品交接指纹

最后产品语义写入时间不晚于 `2026-10-28T06:14:41.015Z`；之后只运行验证并更新本记录。`src/aha` 下22个文件（不含 __pycache__）按排序仓库相对路径UTF-8（包含`src/aha/`前缀）、NUL、原文件字节逐项串联计算 SHA-256：

`950468553e90d8cc319dc25e43a9ca670a6ef1660b76d724adf5cacf66966dc7`

该指纹仅标识当前源码，不是 EXE 校验和，也不包含 editable 安装生成的 egg-info。主会话完成成品及性能证据前，不据本文件宣称全任务交付完成。
