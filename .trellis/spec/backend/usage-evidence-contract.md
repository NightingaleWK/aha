# 本地台账、用量证据与运行契约

## 1. 范围与触发条件

修改来源、SQLite、查询、归属、报销、HTTP 或 Windows 打包时阅读。aha v0.3.0 是本机 Python3.12+ 工具；CCS 是只读输入，业务只访问 Store 的本地台账。实际 SQLite 必须通过 `migrations.sqlite_wal_safe`，不能仅凭 Python 版本启用多连接 WAL。

## 2. 签名与资料边界

[storage.py](../../../src/aha/storage.py) 是统一门面，关键签名如下；可选参数以实现为准：

```python
Store(data_dir: Path)
Store.sync_sqlite(path, metadata_roots=None, *, trigger="manual", startup_id=None, cancel=None)
Store.sync_sql(raw, name, metadata_roots=None, **kwargs)
Store.sync_data(data, metadata=None, **kwargs)
Store.sync_status(run_id=None)
Store.ledger_status()
Store.analyze(start_date, end_date, project_id="all", *, availability_mode="available",
              target_batch_id=None, expected_generation=None, expected_active_version=None)
Store.analysis_details(analysis, *, cursor=None, size=50, kind="detail")
Store.iter_analysis_rows(analysis, connection=None)
Store.iter_analysis_daily(analysis, connection=None)
Store.validate_analysis(analysis, connection=None, *, check_claims=True)
Store.resolve_reconciliation(case_id, choice, reason, expected_generation=None,
                             idempotency_key=None)
Store.create_batch(analysis, claim, idempotency_key, batch_id=None, **kwargs)
Store.download(batch_id, version) -> tuple[Path, str]
```

CCS schema23 与应用 schema3 独立。新库显式创建，旧 schema1/2 或未知资料拒绝自动打开/升级；试用资料经单独清单工具保全历史用量后重建，不接续旧报销。Windows 默认 `%LOCALAPPDATA%\aha`，Linux 为 `${XDG_DATA_HOME:-~/.local/share}/aha`。开发测试必须独立 data-dir。

CLI 为 `python -m aha [--data-dir PATH] [--port 0] [--no-browser] [--no-tray]`；同目录单实例，复用不新增启动同步。runtime.json 含本次 PID/run_id/私有启动地址，不能加入材料或公开记录；持久锁文件退出后保留。详见 [实例与生命周期契约](./runtime-lifecycle-contract.md)。

## 3. 数据、查询与业务合同

### 来源与长期事实

- [sources.py](../../../src/aha/sources.py) 在 `mode=ro/query_only/trusted_schema=OFF` 的同一读事务中分块提取允许字段；包含已提交 WAL，亦支持源 DELETE 模式。源事务有墙钟/锁等待/取消预算，不用 live immutable，不改源日志模式或索引。
- 仅采 `app_type=codex,data_source=codex_session` 明细，以及 Codex provider `_codex_session` 日汇总和必要价格依据。SQL 的生产入口是 `Store.sync_sql`，字面量流式解释到 staging，不执行输入 SQL、不加载无关配置。
- 每次完整核对来源当前允许投影，仅新增/变化写本地。created_at 是事件时间，不是变更水位；来源删除不删已存历史，导入旧备份的时间不能成为覆盖当前值的理由。
- `usage_records` 保存当前可索引事实，`usage_versions` 只追加实际内容修订，`record_evidence/record_aliases` 维护来源和经确认身份；来源 UUID/路径不能让同一消费变成新 key 绕过占用。
- 源事务一致不等于整轮 CCS 重建完成。空源、明显缩水/汇总回退、未知来源和疑似重建必须保留旧事实并提示核对；未核实变化不能推进最近成功时间。
- 同步按 run 暂存，一次发布事实、归属、可用状态、日/月统计与版本；失败不暴露半批次或清空旧本地数据。只在每次工具启动一次及手动同步，不增加定时采集、自启或关闭后的采集机制。

### 核算、覆盖与归属

- 金额始终是精确十进制字符串，使用 [decimal_sql.py](../../../src/aha/decimal_sql.py) 的 `decimal_sum/integer_sum/usage_groups` 支持大整数和极小金额；禁止 REAL SUM、按当前价格重算、再乘倍率或固定微美元截断。
- input_token_semantics 0 扣 cache read，1 扣 read+creation，2 已是 fresh；异常减成负数保留原 input 并标记。总 Token 对 fresh/output/read/creation 各计一次。
- 日期按北京时间含起止两日；原 rollup 日期与时区依据保留，不能假称备份验证了历史时区或把无记录当成零消耗证明。
- 明细/来源日汇总/本地日统计分层。数值匹配不是成员完整证明；部分/未知覆盖的双方可查且不可相加，不造差额明细、不比例拆分。核对选择要有原因、generation 和幂等，不能释放已占用成员。
- [projects.py](../../../src/aha/projects.py) 依次采用内容指纹绑定的人工覆盖、最长完整目录前缀、未归属。Windows 路径忽略大小写，Linux 保留；普通/zstd 会话头只提供目录依据，不读正文。

### 本地查询与冻结材料

- [queries.py](../../../src/aha/queries.py) 是 SQL 选择/核算入口，analysis.py 只再导出该入口。分析只保存条件、摘要和 data/classification/claim 依据，不保存全体行数组。
- 明细、来源汇总、每日、模型四个视图均游标分页，size1–200；游标绑定筛选与版本。日视图从 `daily_usage_stats` 读取，全月范围摘要使用 `monthly_usage_stats`，可用性在 `usage_records` 派生列中维护；不把全部 facts/claims/overrides fetchall 到 Python。
- summary 仅合计已核实依据；pending_count/summary_complete 和核对入口说明未核实部分。available/all 区分申请与只读；all 或空选择不得保存报销。
- 保存草稿即占用，单有效版本，lifecycle 为 active/voided；有效草稿可修订，已提交带原因撤回，已报销纠错先作废，作废终态仅释放自身。独占、版本、generation、幂等、事件及统计在权威事务内重检/提交。
- current 修订使用专用目标预览，不能借给新建自身豁免；frozen_basis 保留目标有效版原成员，只改用途也不能被无关全局 data_revision 永久阻断。
- `revision_members` 行式冻结；manifest_version3，四文件仍为使用明细.csv、每日汇总.csv、费用说明.html、导出信息.json。CSV BOM/公式保护、HTML 转义、允许分享投影、精确金额和哈希对账均保留。
- CSV、逐成员 manifest、ZIP、校验和下载全链路分块。物理包名与用户下载名分开，深 Windows 资料目录必须可保存；已存包重下原字节，来源修订仅通过 current_difference_count 提示差异。

## 4. 校验与错误矩阵

| 条件 | 行为 |
| --- | --- |
| SQLite 未含必要 WAL 修复 | unsupported_sqlite；创建应用库前拒绝 |
| 旧/未知应用资料 | unsupported_store，保留原件，要求受控重建 |
| CCS 版本/字段不兼容 | unsupported_schema / incompatible_schema，不发布 |
| 源忙/预算超时/取消/超限 | source_busy / sync_cancelled / source_too_large，旧数据和成功时间保留 |
| 源缩水、覆盖/修订未核实 | needs_review 或核对候选，不冒充完整同步成功 |
| 同时同步 | sync_in_progress 或复用有效运行，不产生重复事实 |
| 预览/游标依据变化 | analysis_expired / classification_changed / availability_changed / invalid_cursor，409，刷新 |
| case generation/选择不合法 | stale_case / invalid_choice / invalid_candidate，不能提交旧确认 |
| 消费冲突/内部重叠 | 索引查相关候选，保存阻断，不缩小选择冒充原预览 |
| 重试 key 不同内容 | idempotency_conflict |
| 包缺失或损坏 | artifact_missing / package_damaged，不重建掩盖 |
| 非法生命周期/过期批次 | invalid_transition / stale_batch / inactive_revision / batch_voided |

公开错误只用安全 AppError；不含源 SQL、路径、正文、凭证或 traceback。来源错误不能解释成零用量。

## 5. 正常、基础与错误场景

- 正常：重复同步不增长内容版本；占用后只查询余量，成本修订保留新旧版本/原包，撤回保持占用、作废释放自身。
- 基础：没有项目或目录依据时未归属；仅汇总按整条来源粒度处理；源不可用仍能查询本地历史。
- 错误：把部分重建当完整、按观察时间选旧备份赢家、跨粒度相加、全历史拉进内存、写事务外信任预览、关闭反馈后继续后台定时采集。

## 6. 必需测试与证据

- test_sources/test_storage：DELETE 写提交等待及 WAL 清理交错，跨表一致/有界取消、源移除后重启、修订/候选/无变化、失败保留成功进度。
- test_analysis/test_projects/test_session_meta：精确金额和超 int64 Token、北京时间、四视图游标/自豁免、内容绑定归属、普通/zstd 元数据和查询无外部读取。
- test_claims/test_batches/test_claim_concurrency/test_evidence：相关索引候选、行式冻结/完整选择、并发竞争/失败原版、成本变化后frozen修订、深路径、流式四文件与原包。
- test_http/test_http_cli/test_rebuild_trial_data：认证、有限同步状态、已打开修订失效、持久重放、源保护/清单完整性/删除失败恢复、退出与原生平台资源关闭。
- benchmark_ledger：百万/千万规模、固定来源窗口、首/深页和统计、冷热/P50/P95/RSS/磁盘/EXPLAIN；理论容量和少量用例不能替代实测。Windows 目录包、真实浏览器、Excel/打印与 OneFile 分别验收。

## 7. 错误与正确做法

```python
# 错误：事件时间水位遗漏补录，整包内存和前端分页掩盖全量成本。
rows = [row for row in all_history if row["created_at"] > last_time]
zip_bytes = Path(package).read_bytes()

# 正确：显式同步一次，查询只访问本地索引，下载使用路径分块。
store.sync_sqlite(source_path, trigger="manual")
preview = store.analyze(start_date, end_date, availability_mode="available")
page = store.analysis_details(preview, size=50)
package_path, filename = store.download(batch_id, version)
```

保存仍经 create_batch 的事务内权威重检；上面的预览/分页不构成占用授权。资料方法详见 [SQLite 规范](./database-guidelines.md)，HTTP/页面详见 [页面契约](../frontend/local-web-contract.md)。

## 实施检查补充约束

- 日/月派生统计按相同project/model/kind/state精确口径，在事实、分类、覆盖和占用变更的同一事务更新。完整自然月读月表，首尾非完整月份读日表，段间不能重叠。聚合不经过REAL；冻结主体仍按其完整成员。
- keyset除tuple严格比较外，还须显式收紧event_time标量范围。执行计划和VM工作量应证明直接seek，不能仅凭SQL中存在游标断言深页恒定。
- 源事务内staging等待本机writer必须有界并检查取消；SQLite progress handler不能中断Python RLock等待。双线程测试需证明本机长写不延长CCS DELETE读锁。
- 同源新key的旧语义成员缺席当前完整staging时才提示身份重建；本轮并存的同秒同Token不同key请求不能误合并。rollup代表量下降单独以已确认观察基线核对，不将降价误判为重建。
