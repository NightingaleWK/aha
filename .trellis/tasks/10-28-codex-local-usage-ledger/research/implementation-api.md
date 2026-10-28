# 实施接口合同

2026-10-28，核心/报销/HTTP 并行实施协调用。新 schema3，无旧业务兼容。

## Store 核心 API

- `ledger_status() -> dict`：`data_revision/classification_revision/claim_revision`、`counts{detail_count,rollup_count,record_count,pending_count}`、`coverage{start_date,end_date}`、`last_sync`、`last_attempt`、`last_successful_sync_at`、`directories`、`metadata_coverage`。最近成功时间仅取 completed，不随 failed/cancelled/needs_review 推进。
- `sync_sqlite(path: Path, metadata_roots: list[Path] | None=None, *, trigger="manual", startup_id: str | None=None, cancel: threading.Event | None=None) -> dict`：同步执行有限同步，返回 run 描述；HTTP 自己放单独 worker。`sync_status(run_id: str | None=None)` 返回指定/最近 run。
- `sync_sql(raw: bytes,name: str,metadata_roots=None,**kwargs) -> dict`：生产 SQL 导入入口，字面量解析直接流入 staging，避免先构造整份 SourceData。只解析允许子集，不执行 SQL。
- `sync_data(data, metadata=None, *, source_id=None, trust="backup", trigger="manual", startup_id=None, cancel=None) -> dict`：有界结构化输入/SQL 解析结果/历史输入共用入口；同源活库用 trust="live"，历史/旧SQL不自动覆盖已存在当前值。
- `config()/save_project(id,name,description,directories)` 保留签名；config 不返回全量 overrides。`assign(rows,project_id,grain="detail")` 兼容逐行输入；新增 `assign_keys(keys:list[str],project_id)`、`assign_sessions(session_ids:list[str],project_id)` 与 `assign_session(session_id,project_id)`。多个会话归属在一次事务中提交。
- `analyze(start_date,end_date,project_id="all", *, availability_mode="available",target_batch_id=None,expected_generation=None,expected_active_version=None) -> dict`：只返回条件、三个 revision、summary/availability/warnings、counts；无 details/rollups/members/daily/models 全量数组。HTTP 给 analysis_id 并缓存这个小对象。
- `analysis_details(analysis, *, cursor=None,size=50,kind="detail") -> dict`：`rows,total,next_cursor,previous_cursor`。kind 可选 detail/rollup/daily/models，cursor 绑定版本与筛选，size≤200；daily/models 的 total 为 None，以 next_cursor 判断继续翻页，避免额外全量 count。
- `iter_analysis_rows(analysis, connection=None) -> Iterator[dict]`：按稳定顺序有界迭代完整有效选择；提供 connection 时使用调用方事务，不另开事务。每行包括原允许字段、`kind/record_key/version_id/content_fingerprint/date/time/model/project_id/project_name/assignment_origin/cwd/fresh_input_tokens/total_tokens/pricing_status/usage_state/usage_reason/usage_owners/scope_key/semantic_key`。
- `validate_analysis(analysis, connection=None, *, check_claims=True)`：校验 data/classification/claim 修订；不校验 batch generation，billing 在自身事务校验。
- `revisions(connection=None)` 返回三个 revision；`refresh_availability(connection, scopes=None)` 在调用方 writer 事务中重算受影响 scope 的 availability与日/月统计。scope 是 set[str]，None 表示全部。
- `canonical_record_key(key,connection=None) -> str`：仅沿已人工确认的 record_aliases 解析稳定逻辑消费身份，检测循环。usage_versions 原始 key/payload 保留，usage_records 当前逻辑 key 可指向同消费别名的已核实新版本；billing 从原字段重算 key 后再调用此映射验证，冻结版沿用原冻结逻辑 key。
- `list_reconciliations()`；`resolve_reconciliation(case_id, choice,reason,expected_generation=None,idempotency_key=None)`：choice 为 `detail/rollup/current/candidate/same/independent`（具体 case 合法选择由返回的 choices 限定）。每案包含 generation/choices/message 与可读摘要，观察内容变化推进 generation，旧确认拒绝。确认同消费但金额等内容不同时另建事实修订核对，不以身份确认偷选版本。
- `refresh_metadata(metadata_roots)` 为显式目录更新；查询不读取源或 Codex。

同步 run 终态为 completed/failed/cancelled/needs_review；源缩水且未确认时为 needs_review，保留原成功时间与本地事实。HTTP worker 同样把 needs_review 作为顶层终态，前端仅 running 继续轮询，不能显示同步成功。确认来源后以该次观察作为新已确认基线，后续同样的空源不反复创建缩水事件。

## Billing 接口与核心依赖

核心 fresh initialize 调用 `batches.initialize_schema(connection)`，billing 提供自己的 DDL；其中 usage_claims 由 billing 建，列固定为 `record_key TEXT PRIMARY KEY,batch_id TEXT,owner_version INTEGER,kind TEXT,scope_key TEXT,semantic_key TEXT,member_json TEXT`，并建 key/scope/semantic/owner 索引。

核心委托 `create_batch/list_batches/batch_detail/set_status/withdraw_batch/void_batch/replay_create/download/overlaps` 保留现有参数形状；`download` 改返回 `(Path, filename)`，HTTP 分块下载。核心不提供旧 capture/legacy API。

核心的 `_db` 为 writer，`_transaction()` 管 BEGIN IMMEDIATE；`read_connection()` 提供一个已开启只读事务的上下文，短读使用独立连接。`_now/_encode/_decode/_ensure_open/_file_path/_write_immutable` 保留；`_file_path` 允许 packages/objects/temporary，新增 `publish_file(relative,temporary_path)` 原子登记前发布文件。

核心当前事实表 `usage_records`：`record_key TEXT PRIMARY KEY,kind,version_id INTEGER,content_hash,day,event_time INTEGER,scope_key,coverage_key,semantic_key,model,session_id,project_id TEXT NOT NULL DEFAULT '',assignment_origin,cwd,availability_state ('available'|'claimed'|'pending'),usage_reason,suppressed INTEGER,request_count TEXT,fresh_input_tokens TEXT,output_tokens TEXT,cache_read_tokens TEXT,cache_creation_tokens TEXT,total_tokens TEXT,total_cost_usd TEXT,pricing_status`。

`usage_versions(id INTEGER PRIMARY KEY,record_key,content_hash,payload_json,created_at,source_id, UNIQUE(record_key,content_hash))` 为不可变原字段。行式冻结优先使用 version_id。`suppressed=1` 是已选其他覆盖基准的参考资料；不纳入统计或申请。

`settings(key,value)` 包含 `data_revision`、`revision`（classification）、`claim_revision`。billing 变更占用后推进 claim_revision，并调用 refresh_availability(conn, affected_scopes)。核心不假定 billing 的其他表结构；所有者解释可只按 usage_claims 返回 batch_id/version，展示编号由 billing 或 UI补充。

## 变更纪律

接口差异先更新此文件并通知其他代理。接口已实现；当前验证结果记录在 verification.md，本文件本身不代替性能与原生交付验收。

## 最终检查后的新增内部合同

- fresh schema3增加monthly_usage_stats(month,project_id,model,kind,state,精确指标)和monthly_stats_project_month索引。summary/模型聚合对完整自然月读月表，两端不完整月份读日表；每日视图保持日表。refresh_daily同事务刷新受影响月份。benchmark早期隔离夹具仅通过--query-only --refresh-derived显式补建，用户旧库仍不自动升级。
- source_rollup_observations保存source/key最近提交观察的request_count，仅数值变化写；来源确认基线与内容修订选择独立。日汇总代表量/行数回退进入needs_review。
- staging有界事务：Python RLock总250ms，SQLite临时busy上限100ms且随源剩余期限缩短，检查取消，之后恢复原busy_timeout。一般业务_transaction不变。源游标异常路径显式关闭。
- sync run.timings_ms包括source_projection_and_staging_ms、metadata_ms、compare_current_versions_ms、derived_refresh_ms、publish_before_commit_ms；最后项不含COMMIT耗时，比较项含本机发布锁等待。
- 目标修订的matched/available/excluded按同一上下文，精确差分并查询实际不可用说明，目标自身占用不再重复计为排除。
