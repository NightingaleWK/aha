# CCS 26 兼容核查

- 日期：2026-11-13（Asia/Shanghai）。
- 范围：规划阶段只读研究；未修改产品源码、真实资料或来源版本，未执行同步/构建。
- 查询：25→26 是否改变 aha 依赖的字段、消费身份、Token/金额语义，以及必须修改的兼容与验收位置。

## 官方固定依据

使用 GitHub 插件读取 `farion1231/cc-switch` 并比较：

- 既有 25 基准：`efbec38f0e1ecaee2a488d619190b7ec4075238b`。
- 26 迁移提交：[`d0da1349f9403da228dc12a8f0f812e14f624d10`](https://github.com/farion1231/cc-switch/commit/d0da1349f9403da228dc12a8f0f812e14f624d10)，提交标题为 `feat(workbuddy): add WorkBuddy support with official account switching (#8757)`。
- [固定迁移 schema.rs:700–727](https://github.com/farion1231/cc-switch/blob/d0da1349f9403da228dc12a8f0f812e14f624d10/src-tauri/src/database/schema.rs#L700) 对 `mcp_servers` 补缺失的 `enabled_omp`，对 `mcp_servers/skills` 补 `enabled_dsh/enabled_copilot/enabled_workbuddy`，保留已有值，最后设置 26。
- [固定版本常量](https://github.com/farion1231/cc-switch/blob/d0da1349f9403da228dc12a8f0f812e14f624d10/src-tauri/src/database/mod.rs#L54) 从 25 变为 26。

## 三张允许表逐字比较

从两个固定提交完整 `schema.rs` 中各取第一次 `CREATE TABLE IF NOT EXISTS <table> (` 至建表语句结束，直接比较字符串：

| 表 | 26 固定源码行 | 两侧字符数 | 结果 |
| --- | --- | --- | --- |
| proxy_request_logs | 242 | 1126 / 1126 | 相同 |
| usage_daily_rollups | 322 | 967 / 967 | 相同 |
| model_pricing | 281 | 345 / 345 | 相同 |

比较范围内共有 29 个提交、209 个文件；`session_usage_codex.rs` 未改变，未见 rollup/prune 实现文件变更。`session_usage.rs` 只新增 WorkBuddy 同步分支，`usage_stats.rs` 只增加 `_workbuddy_session` 显示名，代理 Token parser 的变化仅为 Gemini 数字字符串读取；均不改变 aha 选取的 Codex 会话记录语义。`schema.rs` 还新增其他模型种子价格，但 aha 沿用已保存金额，不重算历史。

结论：将外部支持白名单显式增加 26 有依据；无须改变用量投影版本 23、应用 schema4、消费身份或材料 manifest4。不能据此放行 27 或未来版本。

## 本机最小只读核查

通过 `mode=ro`、`query_only=ON`、`trusted_schema=OFF` 和同一读事务核查 Windows 默认 CCS，仅查询 `PRAGMA user_version/table_info`：

- 当前 `user_version=26`。
- `proxy_request_logs/usage_daily_rollups/model_pricing` 的必要列缺失集合均为空。
- 未执行 INSERT/UPDATE/DELETE/ALTER、版本重写或同步；未读取配置/凭据/正文/用量行。

Windows 系统桌面接口返回 `C:\Users\djsyw\Desktop`；成品交付前仍需核实同名文件归属、SHA 和运行占用。

## 改动所有者与回归边界

| 所有者 | 已确认现状 | 所需变化 |
| --- | --- | --- |
| `src/aha/domain.py:17,86` | 外部集合为 23/24/25，共用错误提示 | 显式增加 26；内部投影常量不变 |
| `src/aha/sources.py:37`、`src/aha/sql_dump.py:304` | 共用校验、必要列检查和实际来源元数据已有 | 优先无需生产改动，复用既有逻辑 |
| `tests/test_sources.py:231,248,376,407,426` | 26 仍作为未知版本，升级链只到25 | 增26成功，将未知负例移至27，保留字段、事务、隐私与版本声明检查 |
| `tests/test_storage.py:55–105` | 升级链保护归属/占用/原包，SQL26拒绝 | 扩到26，错误用27；保留失败状态断言 |
| `tests/test_http.py:361–395` | 来源版本贯通job，SQLite25成功/26失败 | 增26成功/27失败；核对ledger及本地历史 |
| `tests/test_evidence.py:45–63` | 外部25与内部23作用域区分 | 用26覆盖同一合同，保留旧包兼容 |
| `scripts/verify_windows_artifact.py:503–560` | 原生升级链到25，SQL25成功，26被拒绝 | 实际执行26成功/27失败恢复，更新scope；不能只改描述 |
| README、后端CCS兼容/主契约/index | 支持范围到25 | 更新到26及固定官方证据，旧历史任务/已发布片段不回写 |
| `.release/changes/` | 每项可感知修复提供独立中文片段 | 新建 ccs26-compatibility fix 片段，不手工升号 |

## 构建运行时事实与限制

- 当前可执行基础解释器：原生 Windows x64 CPython 3.15.2，SQLite 3.53.1；主解释器不修改。
- 既有公开成品验收记录为 CPython 3.15.2 / SQLite 3.53.4，并固定构建依赖；上一任务自有环境已清理。本次必须新建有归属标记的隔离环境。
- 优先按既有来源和 SHA 核验流程恢复同一生产运行时；无法维持运行时一致时须按发布合同重新全面本机验收。规划阶段没有构建或声明任何专项通过。
- WindowsApps `python.exe` 别名本次退出49，无需依赖它；上面 uv 管理的真实基础解释器已实际探测成功。

## 相关规范

- `.trellis/spec/backend/ccs-source-compatibility.md`
- `.trellis/spec/backend/database-guidelines.md`
- `.trellis/spec/backend/usage-evidence-contract.md`
- `.trellis/spec/backend/quality-guidelines.md`
- `.trellis/spec/backend/delivery-and-cleanup.md`
- `.trellis/spec/backend/release-contract.md`
