# 用量证据与本机运行契约

## 1. 范围与触发条件

修改 `src/aha/*.py`、来源结构、持久化、HTTP 或 Windows 打包前阅读。aha 是独立 Python 3.12+ 本机工具；CCS 是只读来源，`Store` 管理另一份应用数据库，两者不得混用。

## 2. 签名与资料边界

以下是当前公开调用摘要；参数类型细节以实现为准：

```python
load_sqlite(path: Path) -> dict[str, Any]
load_sql_dump(data: bytes, name: str) -> dict[str, Any]
scan_metadata(session_ids: set[str], roots: list[Path]) -> dict[str, Any]
analyze(data, metadata, config, start_date, end_date, project_id="all", *,
        claim_snapshot=None, availability_mode="all", target_batch_id=None,
        expected_generation=None, expected_active_version=None) -> dict[str, Any]
Store(data_dir: Path)
Store.retain(data, metadata) -> dict[str, Any]
Store.config() -> dict[str, Any]
Store.save_project(project_id, name, description, directories) -> dict[str, Any]
Store.claim_snapshot(exclude_batch_id=None) -> dict[str, Any]
Store.claim_revision() -> int
Store.create_batch(analysis, claim, idempotency_key, batch_id=None, *,
                   expected_generation=None, expected_active_version=None,
                   request_signature=None) -> dict[str, Any]
Store.replay_create(idempotency_key, request_signature) -> dict[str, Any] | None
Store.withdraw_batch(batch_id, expected_generation, reason, idempotency_key)
Store.void_batch(batch_id, expected_generation, reason, idempotency_key)
Store.resolve_legacy(batch_id, selected_version, expected_generation, reason, idempotency_key)
Store.download(batch_id, version) -> tuple[bytes, str]
```

来源字典有 `schema_version/details/rollups/pricing/source`，CCS schema 为 **23**；应用 `aha.sqlite3` schema 为 **2**。[storage.py](../../../src/aha/storage.py) 管连接、事务、备份与 Store 门面，[migrations.py](../../../src/aha/migrations.py) 管串行结构步骤。原表保留，新增 `batch_control/usage_claims/legacy_holds/claim_events/action_idempotency`。

CLI：`python -m aha [--data-dir PATH] [--port 0] [--no-browser]`。Windows 默认 `%LOCALAPPDATA%\aha`；开发测试必须指定隔离目录。[__main__.py](../../../src/aha/__main__.py) 的 `runtime.json` 记录本次 PID、run_id 和私有 bootstrap URL；清理只删除属于当前 run 的描述符。

## 3. 核心契约

### 来源、核算与归属

- [sources.py](../../../src/aha/sources.py) 使用 URI `mode=ro`、`query_only` 和内存 backup，包含已提交 WAL；不能对活库用 `immutable=1` 或只复制主文件。SQL 导入解析有界字面量子集并投影允许字段，绝不执行导入 SQL。
- 仅统计 `app_type=codex`、`data_source=codex_session` 的明细和 provider 为 `_codex_session` 的 Codex 日汇总；原始记录身份和内容指纹不包含派生项目名。
- 金额跨 JSON/CSV 时使用精确十进制**字符串**。用 Decimal 加总保存的 `total_cost_usd`，不能再次乘倍率或按当前价格重算。[analysis.py](../../../src/aha/analysis.py) 是预览与导出共同的计算入口。
- `input_token_semantics`：0 扣除 cache read，1 扣除 read 和 creation，2 已是 fresh input；若会减成负数，保留原 input 并标记异常。总 token 对 fresh input、output、read、creation 各计一次。
- 日期区间为北京时间起日零点含、结束日次日零点不含；日汇总保留实际粒度和 request_count，不制造逐请求明细，也不把缺少某天记录当作零消耗证明。
- [projects.py](../../../src/aha/projects.py) 先按内容绑定的人工覆盖，再按最长完整目录前缀，最后未归属。Windows 路径忽略大小写，Linux 保留；允许父子目录规则，跨项目重复规范目录拒绝。分类变化通过 `config.revision` 使分析失效。
- `retain` 保存不可变压缩允许投影和元数据，来源观察与内容身份分开；每次分析选择**一个 capture**，重复读取不重复计费、不跨 capture 拼账。历史文件缺失或损坏必须明确失败。
- `save_project` 返回更新后的 config 加 `project`，不能把整个结果当成单个 project。元数据 `errors` 是安全的 `{code,count}` 列表。

### 用量、版本与原子写入

- 保存草稿立即占用用量。`usage_claims.record_key` 在本资料库唯一；[claims.py](../../../src/aha/claims.py) 为预览、迁移、保存提供同一身份/覆盖评估。同日互不重叠明细可独立申请；疑似重建 key、跨粒度覆盖、内部重叠组的每个成员都要带原因排除，不按比例扣减或静默合并。
- 纯 `analyze` 默认 `all`，HTTP 用当前 Store 快照默认 `available`；先过滤，再汇总各行、每日/模型与 Decimal 金额。`availability` 有 `matched_summary/available_summary/excluded_summary/excluded_groups`；all 视图的行带 `usage_state/usage_reason/usage_owners`。all 或空分析不能创建申请。
- 每个批次只有一个 `active_version`，`lifecycle=active|voided|legacy_review`。仅有效草稿可修订；已提交须带原因撤回，已报销须显式作废再新建。作废原因必填、仅释放自己的 claims/holds、且为终态。普通状态变化、撤回、下载和重启均不释放；保留历史财务状态、事件和原 ZIP。
- reserve/swap/release/resolve 都在 `BEGIN IMMEDIATE` 内完成 generation、claim revision、冲突、不可变包索引、事件及幂等变更。RLock 不能替代跨进程锁。换版失败保留旧有效版和占用；竞争返回 409，不能静默缩小成员或改变人工金额。
- 分析绑定 `claim_revision/availability_mode/target_batch_id`、expected generation/active version；只有专用修订预览可排除自身批次占用，新建不能借用豁免。HTTP 持久化规范 JSON 请求签名，先查重放再校验临时预览，缓存清空/重启后也有效。重放已作废创建或旧作废请求不能复活旧记录或删除新所有者用量。
- 同 key 重放复用原版本；有效草稿业务内容不变时，新 key 也可复用版本。业务哈希只纳入冻结事实、source/capture/selection/classification/claim，排除 availability、权威计数、UI 行状态和 warning 措辞，避免无关账本或文案变化制造新版本。

### 迁移与不可变材料

- v1 库迁移前在 `backups/` 获得已校验 SQLite 备份；使用独立只读连接 backup、单个显式迁移事务、逐条 execute，不能用可能隐式提交的 executescript。写锁内重读 schema；备份/DDL/回填失败保留 schema1 和原数据。
- 不能用 MAX(version) 丢弃旧已提交/已报销候选。不安全旧批次进入 `legacy_review`，所有候选成员保留在 holds；带原因 void/resolve 时重检其他 claims/holds，不能自动选赢家或全局清除共享 holds。冻结成员或原包损坏时拒绝，不能重建。
- 新版本 INSERT 使用 `claim_protocol=2`；状态 UPDATE 递增 `write_generation` 且目标必须是有效 active 行。持久触发器也拒绝已经打开的 v0.1.0 连接的旧 INSERT/UPDATE。升级前停旧程序；回旧版须恢复升级前库和配套不可变材料。
- ZIP 恰有 `使用明细.csv`、`每日汇总.csv`、`费用说明.html`、`导出信息.json`。CSV 为 UTF-8 BOM 且保护公式，HTML 转义。manifest version2 加入允许投影的 availability 和 `effective_basis`；旧包字节不变。manifest 哈希覆盖其他三文件，库内 ZIP 哈希覆盖整包；下载始终返回原校验字节，不受后续生命周期影响。

### 分享、HTTP 与错误

- 分享包不含凭证、完整源路径、目录规则、正文、IP 或全库 SQL；人工填写的项目名、用途、金额说明会进入材料。申请金额可空或最多两位小数的非负十进制字符串，非空金额须依据；不分摊订阅或换汇。
- [server.py](../../../src/aha/server.py) 只绑定 `127.0.0.1`，随机启动凭证换 HttpOnly、SameSite Cookie，名为 `aha_session_<实际 server_port>`。Cookie 按 host 作用，常量名称会使同浏览器双实例冲突；变更请求检查 Host/Origin/CSRF，资源内置且 CSP 严格限制。公开错误是安全 AppError，不含 SQL/路径/token/traceback。

## 4. 校验与错误矩阵

| 条件 | 结果 |
| --- | --- |
| CCS 版本不支持或缺字段 | `unsupported_schema` / `incompatible_schema`，不成功留存 |
| SQL 超 128 MiB、数据库或行数超限 | 明确超限错误，HTTP 413 |
| 非有限/负金额、非法整数 token、重复源 key | 拒绝导入，不默默转换或去重 |
| 非法日期或逆序区间 | `invalid_date` / `invalid_date_range` |
| 分类版本改变 | HTTP `classification_changed` / `analysis_expired`，409；Store 保存可返回 `stale_analysis` |
| 留存/原包缺失损坏 | `artifact_missing/capture_damaged/package_damaged`，409；不可变写碰撞可能 `artifact_damaged`，不重建旧材料 |
| 未知应用库版本 | `unsupported_store`，409，保留资料 |
| 重试 key 对应不同内容 | `idempotency_conflict` |
| Host/Origin/CSRF 不合法 | HTTP 403 |
| 他人占用、模糊身份或内部重叠 | 可用预览带原因排除；保存拒绝 `usage_claimed/usage_ambiguous/usage_internal_overlap` |
| 占用版本或批次 generation 已变 | `availability_changed` / `stale_batch`，409，更新后再保存 |
| all 或无可用成员 | HTTP 预检 `read_only_analysis/empty_analysis`；Store 保存 `readonly_analysis/empty_usage`，无新占用 |
| 历史版本、已作废或非法状态迁移 | `inactive_revision/batch_voided/invalid_transition`，409 |
| 不安全旧候选 | `legacy_review` 和全部候选 holds，须显式带原因消解 |

## 5. 正常、基础与错误场景

- 正常：占用一个项目用量后只预览其余成员；带原因作废后可重用释放成员；重启后原 ZIP 哈希不变。
- 基础：缺元数据时明细未归属，仍可按日期导出；完整日汇总可人工分配，但不能按比例拆分。
- 错误：绕过重叠提示、事务外信任旧预览、不限定所有者释放、用新草稿丢掉旧已报销成员，或重建损坏原包。来源、成本和隐私约束仍适用。

## 6. 测试要求

在隔离环境运行 unittest、Ruff、strict mypy 和 compileall，命令见 [质量要求](./quality-guidelines.md)。以下文件均位于 `tests/`：

| 测试 | 关键断言 |
| --- | --- |
| `test_sources.py` | 已提交 WAL 包含、来源原字节不变、SQL 无执行副作用 |
| `test_analysis.py` | 三种 token 语义、Decimal、北京时间、混合粒度、项目分区、无分页截断 |
| `test_session_meta.py` | 普通/zstd 有界头、缺失冲突、无正文留存；Windows 夹具显式关闭连接 |
| `test_storage.py`、`test_storage_helpers.py` | 重复留存、原子失败、原件移除后重启、损坏/版本拒绝 |
| `test_claims.py`、`test_batches.py` | 精确/模糊身份、内部组、有效版、限定所有者释放、原包、释放重用后的旧请求 |
| `test_claim_concurrency.py` | 独立连接/进程竞争、并发迁移、同 key 同一版本 |
| `test_migrations.py` | 真实文件/WAL 备份、全部 holds、旧活连接拒写、损坏及事务/提交回滚 |
| `test_evidence.py` | 精确可用成员与三份合计、manifest2/effective_basis、BOM/公式/HTML/隐私，不重建旧包 |
| `test_http.py`、`test_http_cli.py` | 过期可用量、修订主体、持久重放、双服务器共享 CookieJar、原字节、所属服务退出重启 |

Windows launcher PID 可能不同于服务 PID，须核对描述符指向的服务和关闭端口。发布先 Windows 目录包，再实际 EXE/浏览器导入下载、目标 Excel 打开 CSV、HTML 打印，之后 OneFile 及重启冒烟；Linux 测试不能替代。原生检查触发与历史证据边界见 [质量要求](./quality-guidelines.md)。

## 7. 错误与正确做法

```python
# 错误：用当前价格改写历史成本，或漏掉活库 WAL。
cost = float(tokens) * current_price
connection = sqlite3.connect("file:cc-switch.db?immutable=1", uri=True)

# 正确：使用来源快照读取和唯一核算器。
data = load_sqlite(source_path)
result = analyze(data, metadata, config, start_date, end_date, project_id)
cost_text = result["summary"]["total_cost_usd"]
```

```python
# 错误：预检与写入分离会在另一进程抢占后继续保存。
if not store.overlaps(result):
    insert_revision(result)

# 正确：Store 仍在写事务内重检权威和成员。
result = analyze(data, metadata, config, start_date, end_date,
                 claim_snapshot=store.claim_snapshot(), availability_mode="available")
result["capture_id"] = capture_id
saved = store.create_batch(result, claim, idempotency_key)
```

上述正确流程可对照 [analysis.py](../../../src/aha/analysis.py)、[storage.py](../../../src/aha/storage.py) 和 [batches.py](../../../src/aha/batches.py)；示例变量代表调用方已有的隔离来源与表单。
