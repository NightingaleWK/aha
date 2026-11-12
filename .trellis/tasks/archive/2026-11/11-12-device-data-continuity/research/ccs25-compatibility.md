# Research: CCS 25 上游兼容与换机来源边界

- Query: CCS 24→25 是否改变 aha 所用表、Token 语义、请求身份及日汇总；新电脑 CCS 如何重新发现本机用量；aha 兼容与验收应修改哪些位置。
- Scope: mixed，规划阶段只读研究；未访问真实用户数据库，未修改产品代码，未运行同步/恢复。
- Date: 2026-11-12（Asia/Shanghai）

## Findings

### 1. 上游版本和固定证据

通过 GitHub 插件读取官方 `farion1231/cc-switch`：

- 最新公开版本为 [v4.0.29](https://github.com/farion1231/cc-switch/releases/tag/v4.0.29)，发布于 2026-11-10T15:29:53Z；这是远端观测，不代替本机 EXE 版本实测。
- v4.0.29 为 annotated tag，tag 对象 `8ad4317a8e949b95457e7441ff1bc8421e0b584a` 指向固定提交 **`efbec38f0e1ecaee2a488d619190b7ec4075238b`**。
- 上一 aha 已核查固定提交为 **`c0189078aacdd80fd2462f59b345f55f62b41cf2`**（v4.0.24）。以下比较均对这两个固定提交，未把当前 main 当成已经核查的发布版本。

### 2. 24→25 仅增加 Copilot 应用开关

[schema.rs:684–696](https://github.com/farion1231/cc-switch/blob/efbec38f0e1ecaee2a488d619190b7ec4075238b/src-tauri/src/database/schema.rs#L684) 对 `mcp_servers` 和 `skills` 以缺失才添加方式增加 `enabled_copilot BOOLEAN NOT NULL DEFAULT 0`，随后设置 `user_version=25`。

[database/mod.rs:54–56](https://github.com/farion1231/cc-switch/blob/efbec38f0e1ecaee2a488d619190b7ec4075238b/src-tauri/src/database/mod.rs#L54) 的当前 schema 常量为 25；[上游迁移回归:4159–4190](https://github.com/farion1231/cc-switch/blob/efbec38f0e1ecaee2a488d619190b7ec4075238b/src-tauri/src/database/schema.rs#L4159) 覆盖 23/24 升级、原开关保留、新开关默认关闭和重复迁移。

没有在这段版本迁移中新增/修改 aha 的允许用量字段，也没有要求将旧用量清空。

### 3. 三张用量表定义一致

分别读取两个固定提交的完整 `schema.rs`，按各表第一处 `CREATE TABLE IF NOT EXISTS` 至语句结束提取比较，确认：

| 表 | 旧/新建表 SQL | v4.0.29 固定位置 |
| --- | --- | --- |
| `proxy_request_logs` | 字符串逐字相同，1127 字符 | [schema.rs:240–254](https://github.com/farion1231/cc-switch/blob/efbec38f0e1ecaee2a488d619190b7ec4075238b/src-tauri/src/database/schema.rs#L240) |
| `usage_daily_rollups` | 字符串逐字相同，968 字符 | [schema.rs:320–336](https://github.com/farion1231/cc-switch/blob/efbec38f0e1ecaee2a488d619190b7ec4075238b/src-tauri/src/database/schema.rs#L320) |
| `model_pricing` | 字符串逐字相同，346 字符 | [schema.rs:279–284](https://github.com/farion1231/cc-switch/blob/efbec38f0e1ecaee2a488d619190b7ec4075238b/src-tauri/src/database/schema.rs#L279) |

必要字段存在性仍应按 aha 自有白名单校验，不能仅凭 user_version=25 放行缺表/缺列库。建表相同不是对所有任意改写数据库的兼容承诺；本机原生只读 `table_info` 对比由主会话执行。

### 4. Token、写入身份和日汇总

- 两固定提交的 `services/sql_helpers.rs` Git blob 均为 `049db1c52158f71df95128a03022fc9b59c74b5e`。因此归一逻辑文件相同：[常量与归一:30–63](https://github.com/farion1231/cc-switch/blob/efbec38f0e1ecaee2a488d619190b7ec4075238b/src-tauri/src/services/sql_helpers.rs#L30) 仍为 0=legacy 扣缓存读、1=total 扣缓存读写、2=fresh 原样；保留原先不足扣除时回退原 input 的边界行为。
- 两固定提交的 `database/dao/usage_rollup.rs` Git blob 均为 `1ca576c5d5c7caf2b259bfc95d720971054f60cc`。日汇总与裁剪实现未变：[116–177](https://github.com/farion1231/cc-switch/blob/efbec38f0e1ecaee2a488d619190b7ec4075238b/src-tauri/src/database/dao/usage_rollup.rs#L116) 按完整本地日及 `app_type/provider_id/model/request_model/pricing_model` 聚合，合并已有汇总，写 FRESH 语义，随后清理过期明细。
- CCS 自己汇总历史费用时使用其保存/计算结果；aha 仍应读取其历史金额文本，不按当前价格重算。上游日汇总 SQL 自身有 REAL 运算不是 aha 可修改的对象，也不能据此放宽 aha 精确数值契约。
- `session_usage_codex.rs` 两版本不是整文件相同，但关键身份方案相同。旧固定提交已有 `codex_session:thread-v1` 常量（旧文件:49）及相同 request_id 构造（旧文件:2348）；**不能把 thread-v1 说成 schema25 新增迁移**。
- 新版以 `codex_session:thread-v1:{root_thread_id}:{suffix}` 构造请求身份，[新版:2340–2363](https://github.com/farion1231/cc-switch/blob/efbec38f0e1ecaee2a488d619190b7ec4075238b/src-tauri/src/services/session_usage_codex.rs#L2340)。双 UUID rollout 的 `session_id` 与请求去重所用 rollout/thread 标识有分工；不能凭 session_id 变化直接把请求当新消费。
- [新版:2514–2548](https://github.com/farion1231/cc-switch/blob/efbec38f0e1ecaee2a488d619190b7ec4075238b/src-tauri/src/services/session_usage_codex.rs#L2514) 仍写 `provider_id=_codex_session`、`app_type=codex`、`data_source=codex_session`，以 TOTAL=1 表示 input 已含缓存读写。
- [usage_stats.rs:732–745](https://github.com/farion1231/cc-switch/blob/efbec38f0e1ecaee2a488d619190b7ec4075238b/src-tauri/src/services/usage_stats.rs#L732) 只因已有 request_id 或匹配代理日志而跳过；[session_usage_codex.rs:2463–2473](https://github.com/farion1231/cc-switch/blob/efbec38f0e1ecaee2a488d619190b7ec4075238b/src-tauri/src/services/session_usage_codex.rs#L2463) 对不同 request_id 的疑似同用量只计警告，继续插入。因此 aha 不能将同秒同 Token 的不同请求无条件合并。

### 5. 新电脑、复制日志和 Windows/WSL 边界

- [codex_config.rs:270–275](https://github.com/farion1231/cc-switch/blob/efbec38f0e1ecaee2a488d619190b7ec4075238b/src-tauri/src/codex_config.rs#L270) 先读 CCS 设置的 Codex 覆盖目录，未设置时使用 CCS 所在环境的用户 home 下 `.codex`；[settings.rs:1346–1351](https://github.com/farion1231/cc-switch/blob/efbec38f0e1ecaee2a488d619190b7ec4075238b/src-tauri/src/settings.rs#L1346) 对应字段为 `codex_config_dir`。
- [session_usage_codex.rs:1049–1065](https://github.com/farion1231/cc-switch/blob/efbec38f0e1ecaee2a488d619190b7ec4075238b/src-tauri/src/services/session_usage_codex.rs#L1049) 使用上述唯一根目录收集会话并按本库游标读取。新 CCS 库没有原游标时，会重新扫描该根已有会话；只复制 aha 不会让 CCS 自动获得旧电脑日志。
- [收集规则:1097–1122](https://github.com/farion1231/cc-switch/blob/efbec38f0e1ecaee2a488d619190b7ec4075238b/src-tauri/src/services/session_usage_codex.rs#L1097) 扫 `sessions/YYYY/MM/DD` 及扁平 `archived_sessions`，支持 rollout 普通/压缩形态，并处理兄弟文件重复。Windows 和 WSL 各自的 `.codex` 不是天然同一根；Windows CCS 未指向 WSL 日志时不能据“Codex 在使用”断言 CCS 已收录这些用量。
- [游标继承:822–850](https://github.com/farion1231/cc-switch/blob/efbec38f0e1ecaee2a488d619190b7ec4075238b/src-tauri/src/services/session_usage_codex.rs#L822) 专门防归档/压缩换路径重导；其说明指出超出明细保留期后单靠 request_id 不足以防重复日汇总。aha 应保留自己的长期事实与来源观察，不能把 CCS 当前快照当完整全历史。
- [reset_codex_usage_on_conn:586–635](https://github.com/farion1231/cc-switch/blob/efbec38f0e1ecaee2a488d619190b7ec4075238b/src-tauri/src/services/session_usage_codex.rs#L586) 是独立的 CCS 重建操作，会删 CCS 的 codex_session 明细/日汇总及相关游标；它不是24→25必然迁移。aha 必须将这类来源缩水与自己的历史删除分开。

上述是上游实际读取逻辑。没有读取用户 CCS 配置、凭据或聊天正文，也没有替用户修改 CCS 设置。若主会话发现 Windows 新 CCS 明细很少，可最小化检查日期覆盖及使用环境；不能直接代改 Codex 根目录。

### 6. aha 当前阻断与影响文件

| 所有者 | 当前证据 | 实施方向 |
| --- | --- | --- |
| `src/aha/domain.py:15–17,86–92` | 外部支持集合仅 `(23,24)`，内部投影23独立 | 增外部25，未知版本仍拒绝；不改内部投影23 |
| `src/aha/sources.py:37–48,77–87` | SQLite 先校验版本再必要表/列，且事务只读 | 共用版本集合即可放行合法25；保留字段、事务、取消、限时边界 |
| `src/aha/sources.py:129–135` | 返回真实 `source_schema_version` | 25需贯通 run/HTTP/ledger，不能冒充历史所有成员都来自25 |
| `src/aha/sql_dump.py:298–316` | 唯一版本声明后共用校验，返回真实版本 | 接受唯一25；缺失/混合/伪造/未知仍拒绝，不执行SQL |
| `src/aha/domain.py:183–191,265–274` | 消费 key 基于请求身份/rollup维度，内部投影23 | 外部版本不加入身份/内容hash，无理由改schema23 |
| `src/aha/sync.py:668–689` | 适配异常进入失败清理，不到 `_publish` | 版本25报错本身不应删除事实；真实现状以主会话审计为准 |
| `src/aha/evidence.py:435–437` / `queries.py:475` | 内部投影版本有明确作用域 | 沿用23与manifest4；已有冻结包不重建 |
| `README.md:13,117` 与 CCS spec | 仅说明23/24及旧固定提交 | 更新支持范围及新的固定依据；不修改已经公开的历史版本说明 |

### 7. 需要扩展的回归与成品验收

现有“25为未知版本”的负例必须移为26或其他明确未知版本，不能删除拒绝测试：

- `tests/test_sources.py:207–253`：真实版本注释/PRAGMA、23/24投影同一性、25未知提示。
- `tests/test_sources.py:376–434`：SQLite23→24指纹/身份不变、未知 `(0,22,25)`、25坏输入负例。扩展23→24→25，字段缺失仍拒绝。
- `tests/test_storage.py:50–109`：结构升级保留归属、占用、原包SHA；25 SQL失败不发布。扩展25成功与26失败，保留 SQL 暂存失败清理。
- `tests/test_http.py:308–338`：SQL/SQLite真实版本元数据、未知25失败仍可查询旧资料。扩展三版本，26报实际未知值和完整支持范围。
- `tests/test_evidence.py:45–63`：外部来源版本与内部投影23/冻结材料作用域；可再以25验证旧协议未变。
- `scripts/verify_windows_artifact.py:331–343,382–383`：当前原生验收只运行23/24、SQL24，回执scope也硬编码。应实际增加25 SQLite/SQL成功及未知26失败恢复，更新scope与证据，不能仅改标签。
- 换机专项另外覆盖：旧库+空25源，旧库+新25源；同key同内容重导不增加；同key真实修订保留旧版本/冻结材料；疑似重建/缩水未确认不前进；不同设备日汇总相同维度不能当同一旧库修订；Windows/WSL来源读到的事实范围清楚。
- 本机真实源可只读投影写隔离验收库，不对原CCS切日志模式或写版本。原用户aha需一致副本回归；成品仍须目录版/OneFile/实际桌面副本各自验证。

## Related Specs

- `.trellis/spec/backend/ccs-source-compatibility.md`：外部版本与内部投影分离、SQL唯一声明、旧冻结内容不回填。
- `.trellis/spec/backend/database-guidelines.md`：只读来源、一致事务、双阶段同步、失败回滚与原生SQLite门禁。
- `.trellis/spec/backend/delivery-and-cleanup.md`、`release-contract.md`：最终源码一致的单文件成品、真实验收与中文变更片段。

## Caveats / Not Found

- 未访问真实用户数据库，未给本机CCS EXE版本、实际25字段、行数、Windows/WSL配置是否正确下结论；这些由主会话只读核实。
- 版本迁移和允许表/关键语义有证据兼容；Codex parser整文件有其他变化，不能声称所有重建/重扫结果必然与旧快照逐行相同。必须以真实投影差异和核对机制承接。
- 不使用未来版本 `>=23` 放行，不把25写回旧CCS库，不全局替换23或24，不把本次同步最新版本回填历史材料。
- 完整 aha 备份/还原、多设备来源/rollup隔离属于同任务另一研究主题，本报告只限定上游来源事实与兼容性，不替代其设计决策。
