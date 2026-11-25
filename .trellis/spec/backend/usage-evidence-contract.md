# 本地台账、用量证据与运行契约

## 1. 范围与触发条件

修改来源、SQLite、查询、归属、报销、HTTP 或 Windows 打包时阅读。aha 是本机Python3.12+工具，版本以包内 `__version__` 为准；Windows 和 WSL 的 Codex 会话是只读输入，业务只访问 Store 的本地台账。实际 SQLite 必须通过 `migrations.sqlite_wal_safe`，不能仅凭 Python 版本启用多连接 WAL。版本、打包身份和GitHub正式发版遵循 [发布合同](./release-contract.md)。

## 2. 签名与资料边界

[storage.py](../../../src/aha/storage.py) 是统一门面，关键签名如下；可选参数以实现为准：

```python
Store(data_dir: Path)
Store.sync_codex(source, source_id, *, trigger="manual", startup_id=None, cancel=None, since=None)
Store.sync_data(data, metadata=None, **kwargs)
Store.sync_status(run_id=None)
Store.ledger_status()
Store.analyze(start_date, end_date, project_id="all", *, availability_mode="available",
              target_batch_id=None, expected_generation=None, expected_active_version=None)
Store.analyze_time_range(time_range, project_id="all", **kwargs)
Store.analysis_details(analysis, *, cursor=None, size=50, kind="detail")
Store.iter_analysis_rows(analysis, connection=None)
Store.iter_analysis_daily(analysis, connection=None)
Store.validate_analysis(analysis, connection=None, *, check_claims=True)
Store.reconciliation_summary()
Store.reconciliation_page(filters, *, cursor=None, size=50)
Store.reconciliation_detail(case_id)
Store.preview_reconciliation_batch(request)
Store.apply_reconciliation_batch(request)
Store.resolve_reconciliation(case_id, choice, reason, expected_generation=None,
                             idempotency_key=None)
Store.create_batch(analysis, claim, idempotency_key, batch_id=None, **kwargs)
Store.download(batch_id, version) -> tuple[Path, str]
```

内部用量投影版本 23 与应用 schema 6 独立。schema 3 至 5 升级前先生成一致完整备份。Windows 默认资料位于 %LOCALAPPDATA%\aha，Linux 为 ${XDG_DATA_HOME:-~/.local/share}/aha。完整备份和来源重绑见 [恢复合同](./recovery-and-device-contract.md)。

CLI 为 `python -m aha [--data-dir PATH] [--port 0] [--no-browser] [--no-tray]`；同目录单实例，复用不新增启动同步。runtime.json 含本次 PID/run_id/私有启动地址，不能加入材料或公开记录；持久锁文件退出后保留。详见 [实例与生命周期契约](./runtime-lifecycle-contract.md)。

## 3. 数据、查询与业务合同

### 来源与长期事实

- Codex 来源按端只读。原生会话和压缩归档先提取最小用量投影，再分批暂存，本地发布事务同时提交事实、证据、进度与派生统计。仅启动和手动操作触发采集。
- `usage_records` 保存当前可索引事实，`usage_versions` 追加实际内容版本。`record_evidence`、`codex_event_evidence` 和 `record_aliases` 保存来源和经确认身份。源文件移动或消失不更改既有金额、归属、占用和旧包。
- 事件身份用于跨端去重。物理游标只用于续读。证据不足时展示待核对依据，曾保存的历史继续可查。
- `Store.sync_data` 用于受控的已归一化 aha 历史投影。旧来源观测和数据语义参见 [历史 CCS 兼容记录](./ccs-source-compatibility.md)。

### 核算、覆盖与归属

- 金额始终是精确十进制字符串，使用 [decimal_sql.py](../../../src/aha/decimal_sql.py) 的 `decimal_sum/integer_sum/usage_groups` 支持大整数和极小金额；禁止 REAL SUM、按当前价格重算、再乘倍率或固定微美元截断。
- input_token_semantics 0 扣 cache read，1 扣 read+creation，2 已是 fresh；异常减成负数保留原 input 并标记。总 Token 对 fresh/output/read/creation 各计一次。
- 新时间入口使用北京时间半开秒区间，固定结束分钟整分钟计入。旧日期入口包含起止两日。所有当前选择采用真实事件时间，详见 [时间合同](./time-range-contract.md)。
- 逐笔明细是活动用量事实。本地日统计按所选明细生成，旧来源日汇总随台账升级删除。冻结材料使用登记的原版本和原包。
- 归属对已明确确认的目录采用目录整体权威，确认时覆盖旧人工跨项目例外并统一历史，后续和迟到依据自动接续；未纳管旧模式以有效内容指纹人工覆盖和持久逐笔关系为权威。未确定项进入待归属清单。普通配置草稿或本机缺日志不能抹去关系，目录整体保存/转移先预览影响再一次原子确认。Windows 路径忽略大小写，Linux 保留；普通/zstd 会话头只提供线索，不读正文。优先级、批量和恢复见[项目归属合同](./project-association-contract.md)。

### 本地查询与冻结材料

- [queries.py](../../../src/aha/queries.py) 是 SQL 选择/核算入口，analysis.py 只再导出该入口。分析只保存条件、摘要和 data/classification/claim 依据，不保存全体行数组。
- 逐笔、按日和按模型视图支持游标分页，size 为 1 至 200。完整日月使用聚合表，部分日按事件秒读明细。分析、预览和保存使用同一选择。
- summary 仅合计已核实依据；pending_count/summary_complete 和核对入口说明未核实部分。available/all 区分申请与只读；all 或空选择不得保存报销。
- assignment_coverage 单独说明同期未归属，不能混成时间/核对完整性；确定项目仍可报销。覆盖随预览冻结、分享只带计数不带未归属金额；覆盖变化时 current 修订不能当原 business_hash 无变化返回旧版，见[项目归属合同](./project-association-contract.md)。
- 保存草稿即占用，单有效版本，lifecycle 为 active/voided；有效草稿可修订，已提交带原因撤回，已报销纠错先作废，作废终态仅释放自身。独占、版本、generation、幂等、事件及统计在权威事务内重检/提交。
- current 修订使用专用目标预览，不能借给新建自身豁免；frozen_basis 保留目标有效版原成员，只改用途也不能被无关全局 data_revision 永久阻断。
- revision_members 按行冻结材料。新材料 manifest 5，包含使用明细.csv、每日汇总.csv、费用说明.html 和导出信息.json。历史材料按原 ZIP 字节下载，冻结依据缺失的信息显示未知。
- CSV、逐成员 manifest、ZIP、校验和下载全链路分块。物理包名与用户下载名分开，深 Windows 资料目录必须可保存；已存包重下原字节，来源修订仅通过 current_difference_count 提示差异。

## 4. 校验与错误矩阵

| 条件 | 行为 |
| --- | --- |
| SQLite 未含必要 WAL 修复 | unsupported_sqlite；创建应用库前拒绝 |
| 旧/未知应用资料 | unsupported_store，保留原件，要求受控重建 |
| 来源文件不可达或记录不完整 | 按端不可达或部分覆盖，保留旧历史和未完成的读取位置 |
| 源忙/预算超时/取消/超限 | source_busy / sync_cancelled / source_too_large，旧数据和成功时间保留 |
| 本地回放/暂存预算超时 | sync_processing_timeout，不能误报来源读取超时，旧数据和成功时间保留 |
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

- test_codex_sessions/test_native_sync/test_storage：有界增量、两个端独立提交、压缩回放、候选、成功时间、历史合计和冻结原包。
- test_analysis/test_projects/test_session_meta：精确金额和超 int64 Token、北京时间、四视图游标/自豁免、内容绑定归属、普通/zstd 元数据和查询无外部读取。
- test_claims/test_batches/test_claim_concurrency/test_evidence：相关索引候选、行式冻结/完整选择、并发竞争/失败原版、成本变化后frozen修订、深路径、流式四文件与原包。
- test_http/test_http_cli/test_rebuild_trial_data：认证、有限同步状态、已打开修订失效、持久重放、源保护/清单完整性/删除失败恢复、退出与原生平台资源关闭。
- benchmark_ledger：百万/千万规模、固定来源窗口、首/深页和统计、冷热/P50/P95/RSS/磁盘/EXPLAIN；理论容量和少量用例不能替代实测。Windows Directory与OneFile每版独立检查，首次全面本机验收和以后相关Excel/打印、托盘专项按发布合同分别留证。

## 7. 错误与正确做法

```python
# 错误：事件时间水位遗漏补录，整包内存和前端分页掩盖全量成本。
rows = [row for row in all_history if row["created_at"] > last_time]
zip_bytes = Path(package).read_bytes()

# 正确：显式同步一次，查询只访问本地索引，下载使用路径分块。
store.sync_codex(source, confirmed_source_id, trigger="manual")
preview = store.analyze(start_date, end_date, availability_mode="available")
page = store.analysis_details(preview, size=50)
package_path, filename = store.download(batch_id, version)
```

保存仍经 create_batch 的事务内权威重检；上面的预览/分页不构成占用授权。资料方法详见 [SQLite 规范](./database-guidelines.md)，HTTP/页面详见 [页面契约](../frontend/local-web-contract.md)。

## 实施检查补充约束

- 日/月派生统计按相同project/model/kind/state精确口径，在事实、分类、覆盖和占用变更的同一事务更新。完整自然月读月表，首尾非完整月份读日表，段间不能重叠。聚合不经过REAL；冻结主体仍按其完整成员。
- keyset除tuple严格比较外，还须显式收紧event_time标量范围。执行计划和VM工作量应证明直接seek，不能仅凭SQL中存在游标断言深页恒定。
- 源读取后再做本地 staging；本机写者等待与应用退出取消皆有界。详见 [原生提交合同](./database-guidelines.md#原生同步事务)。
- 同源重建仅在旧语义成员缺席于当前完整暂存时提示身份变化。同批已观察到的不同请求仍分别记录。


## 分页核对与批量确认同一消费

### 1. 范围

修改待核对事项的筛选、证据投影、批量确认或派生统计时，核对 [核对模块](../../../src/aha/reconciliation.py) 和 [页面状态](../frontend/state-management.md#数据核对弹窗)。

### 2. 入口

读走 `reconciliation_summary`、`reconciliation_page`、`reconciliation_detail`；写走 `preview_reconciliation_batch` 和 `apply_reconciliation_batch`。来源修订和单笔选择继续使用 `resolve_reconciliation`。HTTP 字段见 [本机接口](../frontend/local-web-contract.md#2-http-入口)。

### 3. 事实和事务

- 批量资格使用当前 `codex_session` 历史明细、当前 `codex_native` 原生明细，以及原生当前版本的非待核实事件和参考价依据。核对关联须一对一，App、提供方、会话、模型、请求数和四类规范化 Token 均相同。历史时间可对应原生事件秒，也可对应当前原生响应已保存的唯一配对快照秒。按原生解析器规范化 UTC 和截取事件秒，并以北京时间识别历史日。历史候选及活跃原生事件在两种时间及快照身份上均须唯一。任一方已有别名、存在竞争事项、候选已占用或合并会改变项目归属时，交给单笔核对。
- 十进制参考成本相同时沿用已入账历史。成本不同时，历史依据可用且新旧范围无占用、覆盖与来源冲突的事项在用户批量确认后采用实际原生事件时间和参考成本。预览展示采用候选的数量及这些事项的两个精确参考成本合计。
- 全筛选以服务端同一选择范围展开，预览签名绑定采用政策、逐项采用决定、筛选、显式 ID、data/classification/claim revision、事项 generation、两边当前事实版本及采用的配对快照身份和时间。批准后的批量在单一写事务内重检签名、状态和资格。
- 共享单笔的身份确认、历史占用保护和逐项审计。采用候选时通过已确认别名在历史逻辑身份上投影原生版本，保留旧事实及逐项原生采用决策。活跃项目归属随已核实的同一消费接续。批次汇集新旧受影响 scope，一次推进数据版本、刷新可用性和日月统计。操作签名及结果与事实一并持久化。来源、用量版本及历史报销原包作为证据保留。
- 来源复读用原生事件身份续接已采用的版本，重读精确的历史前版只追加来源证据。历史导入重建记录标识时，保留的旧语义依然参加重复检测，身份未决的记录进入核对。
- 资格与数量用集合查询和索引处理。页面最多返回 size 条简要记录。完整依据按事项读取，入口只请求待办总数。首页时间段内待核对用量数以分析结果为准。

### 4. 校验与错误矩阵

| 场景 | 结果 |
| --- | --- |
| 类型、状态、日期或分页无效 | 400，显示安全参数提示 |
| 请求过期游标、预览的证据或资料发生变化 | 409，清理旧选择后重新查询和预览 |
| 当前筛选没有符合批量规则的事项 | 409，展示当前筛选状态 |
| 同幂等 key 再发同一请求 | 返回第一次提交结果 |
| 同 key 对应不同说明或范围 | 409，已提交结果保持原值 |

### 5. 场景

精确且唯一的历史重复以批量「确认为同一消费」应用。未占用且只有参考成本不同的重复采用可核实的原生版本。已有占用且成本不同、用量或缓存存在差异、时间缺少可验证配对、或存在多个候选的事项在页面展开单独确认。已经占用的历史报销继续使用冻结金额和占用。

### 6. 验证

覆盖已入账历史与原生采集的真实候选、响应和快照跨秒、配对缺失或冲突、同秒不同原生事件、同旧记录多个候选、成本差异预览和采用、历史与原生复读、跨日统计、归属、范围跨过 1,000 条、单批一次重算、签名过期、幂等重放、已保存报销原 ZIP 和占用。用真实浏览器验证分页、全选、成本影响、说明、单笔和刷新失败。

### 7. 提交示例

逐次调用单笔入口会为相同 scope 多次重建派生统计。一批确认共享一个预览和提交，事务末尾统一刷新。

```python
page = store.reconciliation_page(filters)
preview = store.preview_reconciliation_batch({"filters": filters, "version": page["version"]})
store.apply_reconciliation_batch({
    "filters": filters, "preview_hash": preview["preview_hash"],
    "reason": reason, "idempotency_key": key,
})
```
