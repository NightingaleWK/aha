# CCS 23 / 24 兼容性核对

日期：2026-11-02。仅只读研究，未运行同步发布、迁移、清理或真实业务写入。

## 本机证据

- Git 基线：`main / f98df67`；任务创建前工作区干净。
- Windows 原生 `C:\Python315\python.exe`：Python 3.15.2 x64，SQLite 3.53.4；它用于只读探测，不等同于已确定发布解释器。
- Windows 已安装 `CC Switch / ProductVersion=FileVersion=4.0.24`。
- 数据库均以 `mode=ro`、`query_only=ON`、显式读事务打开，读取结束 rollback/close；未变更日志模式、数据或配置。
- 当前 `cc-switch.db` 为 user_version=24；备份 `db_backup_20261030_085703.db` 和 `db_backup_20261030_171915.db` 为 23，`db_backup_20261102_084551.db` 为 24。
- 对比当前源与 2026-10-30 17:19:15 备份，`PRAGMA table_info` 全元组（含列号、名称、类型、notnull、default、pk）对三个允许表完全一致：`proxy_request_logs` 27 列、`usage_daily_rollups` 15 列、`model_pricing` 6 列。两个其他备份的同表结构也已读到。
- 源库初次探测有 Codex/codex_session 明细 21,348 条、_codex_session 日汇总 117 条；明细 input_token_semantics 为 0 / 1。活源可自然增长，此计数不是最终验收数量。
- 用户应用库 `aha.sqlite3` 为 schema3：usage_records=usage_versions=19,713，其中 detail=19,598、rollup=115；projects=4，batches=revisions=0。最近 run 为 failed / unsupported_schema / “仅支持 CC Switch 结构版本 23。”。只读基线 `aha.sources.load_sqlite` 在当前原生 Windows 上复现同样错误。
- Windows 桌面接口返回 `C:\Users\djsyw\Desktop`，当时无 `aha.exe`、无运行中的 aha。最终交付时须重新识别桌面、同名文件及占用，不能沿用历史成品声明。

## 上游证据

通过 GitHub 插件读取官方仓库；版本 `v4.0.24` 的固定提交为 `c0189078aacdd80fd2462f59b345f55f62b41cf2`。

- [23→24 迁移](https://github.com/farion1231/cc-switch/blob/c0189078aacdd80fd2462f59b345f55f62b41cf2/src-tauri/src/database/schema.rs#L629)：给 mcp_servers/skills 增加 enabled_dsh，给 session_log_sync 增加 parser_state，再设置 user_version=24；不修改三个允许用量表。
- [Token 语义常量与归一](https://github.com/farion1231/cc-switch/blob/c0189078aacdd80fd2462f59b345f55f62b41cf2/src-tauri/src/services/sql_helpers.rs#L31)：0=legacy 扣缓存读、1=total 扣缓存读写、2=fresh 不扣。与 aha 当前 fresh_input 一致。
- [Codex 用量落库](https://github.com/farion1231/cc-switch/blob/c0189078aacdd80fd2462f59b345f55f62b41cf2/src-tauri/src/services/session_usage_codex.rs#L2502)：仍以 request_id、_codex_session/codex、codex_session、原金额文本和 TOTAL 语义入库。
- [来源日汇总](https://github.com/farion1231/cc-switch/blob/c0189078aacdd80fd2462f59b345f55f62b41cf2/src-tauri/src/database/dao/usage_rollup.rs#L116)：仍按原维度保留 request_count、金额文本，input 归一成 FRESH。aha 读取已保存金额，不重算上游价格或修改其精度。
- 与 aha 原固定提交 e55d8a21 的 compare 确认 Codex 解析器增加 bounded-reference fork 识别；aha 依赖已落库的身份/语义，不引入上游日志解析逻辑。compare 返回 300 文件上限，因此不把“某文件未列出”当作未变更证明；上面各文件已独立读取。

## aha 影响面

| 所有者 | 事实与约束 |
| --- | --- |
| `src/aha/sources.py` / `_validate_schema` | 精确版本 23 检查先于必要字段检查，直接导致当前故障；维持事务、只读、WAL/DELETE、超时/取消和允许投影边界。 |
| `src/aha/sql_dump.py` / `scan_sql_dump` | 最终版本声明集合必须恰为 {23}；需接受单一 23 或单一 24，混合、缺失、伪造声明仍拒绝；不执行输入 SQL。 |
| `src/aha/domain.py:14,260` | SCHEMA_VERSION=23 同时用作内部规范化投影版本；不能简单全局改成 24，否则旧投影及指纹兼容会受影响。 |
| `src/aha/sync.py:655` | sync_data 读取历史内部投影，保留版本 23。真实外部版本从 SQLite/SQL 适配器观察，并通过已有 sync_runs.result_json 持久化，无需应用 schema 迁移。 |
| `src/aha/queries.py:468` | 分析 schema_version=23 是规范化投影，不可改为“最近同步 CCS 版本”。 |
| `src/aha/evidence.py:428` | source_schema_version=23 是固定旧字段；新材料需明确其投影含义，不能用其声称来自 CCS 23。兼容保留旧字段并增加明确作用域/投影字段；不改已有冻结包字节。 |
| `scripts/rebuild_trial_data.py` | 校验 format_version/adapter_version/schema_version=23 的旧历史保全投影，维持既有协议；本任务不执行真实重建。 |

## 结论

已具备明确兼容 CCS 23、24 的证据。以共享外部版本集合和字段契约校验，保持内部投影 23/应用 schema3/身份内容指纹稳定；未知未来版本明确提示，不承诺字段同名即语义兼容。回归必须跨 SQLite、SQL、Store、HTTP 和材料链路，并原生构建桌面 OneFile。
