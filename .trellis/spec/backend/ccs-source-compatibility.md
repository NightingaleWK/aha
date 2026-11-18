# CCS 外部结构与内部投影版本

## 1. 范围与触发

修改 SQLite / SQL 适配器、历史保全投影、同步元数据、分析或材料版本标注时阅读。CCS 全库升级不必然改变 aha 的允许用量表，必须分别核查外部版本和内部协议，不能全局替换相同数字。

已核查 CCS 23→24：只增加其他应用开关和导入游标字段，三个允许用量表结构及 Token 0/1/2 语义兼容。依据为 [官方固定迁移](https://github.com/farion1231/cc-switch/blob/c0189078aacdd80fd2462f59b345f55f62b41cf2/src-tauri/src/database/schema.rs#L629) 和本机原生只读对比；新增支持版本前仍需独立核对字段、身份、金额和语义。

已核查24→25：只增加mcp_servers/skills的enabled_copilot开关，三个允许表定义不变，Token归一与日汇总实现保持兼容。依据为[官方固定迁移](https://github.com/farion1231/cc-switch/blob/efbec38f0e1ecaee2a488d619190b7ec4075238b/src-tauri/src/database/schema.rs#L684)，并与本机CCS4.0.29/结构25的必要字段只读核验一致。换机和来源重建仍按[恢复合同](./recovery-and-device-contract.md)保护历史，不因版本兼容跳过绑定/事实核对。

已核查25→26：迁移为mcp_servers/skills补齐WorkBuddy及早期开发版缺失的应用开关，三个允许表的建表语句与25基准逐字相同，Codex会话导入器和Token语义未变。依据为[官方固定迁移](https://github.com/farion1231/cc-switch/blob/d0da1349f9403da228dc12a8f0f812e14f624d10/src-tauri/src/database/schema.rs#L700)及本机结构26的必要字段只读核验。其他应用新增用量和价格种子不扩大aha采集范围，也不触发历史金额重算。

已核查 26→27：迁移为 `skill_repos` 增加 `host`，为 `skills` 增加 `repo_host`。三个允许表的建表语句和日汇总逻辑与 26 基准一致，本机 CC Switch 4.0.35 的 SQLite 必要字段及上游 SQL 导出格式兼容。上游会话导入器的独立改动仍按 aha 现有身份和来源核对规则处理。见 [官方固定迁移](https://github.com/farion1231/cc-switch/blob/61c43c036ec7eb3a6950b292729d6a7094abe716/src-tauri/src/database/schema.rs#L731-L746) 和 [SQL 导出](https://github.com/farion1231/cc-switch/blob/61c43c036ec7eb3a6950b292729d6a7094abe716/src-tauri/src/database/backup.rs#L704-L712)。

## 2. 签名与所有者

```python
domain.USAGE_PROJECTION_SCHEMA_VERSION = 23
domain.SUPPORTED_CCS_SCHEMA_VERSIONS = (23, 24, 25, 26, 27)
domain.validate_ccs_schema_version(version: int) -> int
sources._validate_schema(connection: sqlite3.Connection) -> int
sources.scan_sqlite(path, sink, *, cancel=None, timeout=None) -> dict
sql_dump.scan_sql_dump(data: bytes, name: str, sink) -> dict
Store.sync_sqlite(...) / Store.sync_sql(...) / Store.sync_data(...)
```

外部支持集合、版本提示文本和校验复用 domain；sources/sql_dump 观察真实外部版本，sync 将它写入既有 sync_runs.result_json。外部兼容本身不要求应用库迁移；当前应用schema4及schema3升级由[项目归属合同](./project-association-contract.md)管理，内部用量投影仍为23。

## 3. 数据合同

- SQLite 在同一只读事务中校验 user_version 为 23、24、25、26 或 27，并校验 proxy_request_logs / usage_daily_rollups / model_pricing 的必要字段。保留允许投影、WAL/DELETE 一致读取、墙钟/锁等待/取消和隐私边界。
- SQL 仅解释字面量，版本来自真实 `-- user_version: N` 注释或字面量 `PRAGMA user_version=N`；全部声明须收敛到单一受支持整数。不同声明不得按“最后一个取胜”，不执行输入 SQL。
- 两个 scan 返回的 source 均增加 `source_schema_version: int`；`load_sqlite/load_sql_dump` 仍产生内部 `schema_version: 23`。
- 本轮成功进入 `_publish` 的 Store 结果（含 needs_review）、HTTP job.result 和 ledger run 描述保留 `source_schema_version: 23 | 24 | 25 | 26 | 27`；本轮导入缺少此元数据的旧历史投影时为 null。失败或升级前的旧 run 可缺少该字段，不能从内部投影版本或最近一次成功推断。
- 外部版本不进入消费身份、行内容 hash 或规范化投影 hash。同源仅变更外部结构版本时，facts、content versions、归属和占用保持一致。SQL 原文件 hash 按原字节计算，版本声明变化可改变该原文件 hash；这不改变消费身份。
- 新分析的 `schema_version` 与 `usage_projection_schema_version` 都为 23。新材料维持 manifest4，并写 `usage_projection_schema_version=23`；保留旧兼容字段 `source_schema_version=23`，同时用 `source_schema_version_scope="normalized_usage_projection"` 明确它表示规范化投影。
- 不以最新同步版本或支持版本列表证明全部冻结成员的原始来源版本。旧 ZIP 与冻结 JSON 不回填、不重建；原包重下载保持 SHA。
- 无新增环境变量、周期同步、自启、其他应用用量统计或真实资料重建。

## 4. 校验与错误矩阵

| 输入/场景 | 可观察结果 |
| --- | --- |
| SQLite / SQL 唯一版本 23、24、25、26 或 27、必要字段完整 | 允许读取并记录真实外部版本 |
| 未支持外部版本（例如 28） | unsupported_schema，提示实际版本和当前支持 23、24、25、26、27 |
| SQL 无版本、字符串伪装声明或混合多个版本 | unsupported_schema；不按任意一个受支持版本放行 |
| 缺表/缺必要列 | incompatible_schema；不能因版本受支持忽略字段校验 |
| 内部历史投影 schema_version 非 23 | unsupported_schema，解释为投影格式不兼容 |
| SQL 暂存后才发现坏版本、解析/数值/发布失败 | 清除本轮 staging，保留旧事实、版本、原包和最近成功时间 |
| 源自然缩水/修订 | 沿用既有 needs_review / 候选核对，不能当成版本升级而自动确认 |

公开错误不含原始 SQL、个人路径、配置或凭证。

## 5. 正常、基础与错误场景

- 正常场景中，同一允许投影依次读结构 23–27，各轮记录实际版本，内容指纹、facts 数量和原占用相同。
- 基础：导入旧内部历史投影，只知道投影版本 23，真实外部版本保持未知；旧材料仍原字节下载。
- 错误：把支持范围改成 `version >= 23`；把 domain 投影版本整体改为 24；用本轮 CCS24 标注全部历史成员；把 CCS source user_version 写回 23 绕过校验。

## 6. 必需测试

- `test_sources` 覆盖 23–27 的 SQLite 与 SQL 内容一致和来源版本准确、缺失/混合/伪造/未知声明拒绝、27 缺表/缺列仍拒绝、23→24→25→26→27 的投影指纹和消费身份一致。
- `test_storage`：结构升级保留归属、占用、原包 SHA；未知版本/SQL 暂存失败保留旧成功时间和事实；旧内部投影的外部版本为未知。
- `test_http`：真实有限同步 job.result 和 ledger 传递实际源版本；失败状态与旧台账保持可查询。
- `test_evidence/test_time_ranges`：新分析/材料投影字段明确，manifest4 内容精确；独立旧 manifest3 包及冻结数据不因新版写入被改写。
- 原生 Windows 的 Directory 和 OneFile 分别验收 27 启动同步、23–27 手动同步、SQL 27 导入、未知 28 拒绝后恢复至 27、保存下载和原包重下、重开和退出。真源只读同步写入隔离资料，原用户 aha 用一致副本回归。

## 7. 错误与正确做法

```python
# 错误：把外部 CCS 版本当作持久内部协议，破坏历史指纹和旧保全读取。
projection["schema_version"] = current_ccs_user_version

# 正确：独立说明外部观测与规范化投影。
source = sources.scan_sqlite(path, sink)
assert source["source_schema_version"] in domain.SUPPORTED_CCS_SCHEMA_VERSIONS
projection = sources.load_sqlite(path)
assert projection["schema_version"] == domain.USAGE_PROJECTION_SCHEMA_VERSION
```
