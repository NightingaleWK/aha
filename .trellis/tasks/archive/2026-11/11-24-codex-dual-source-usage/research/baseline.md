# 规划依据

## 已核对的本机行为

- 2026-11-24 从配置或默认位置抽样，两端均有独立的 Codex 会话目录。随后按用户刚跑的会话复核，两端均新增可解析的会话目录、模型和非零 Token 证据。抽样会话未发现跨端 ID 重合。这只验证了落点和可读性。
- Windows 调用 `wsl.exe` 后可在当前发行版内打开一份真实会话日志。持续新增、归档压缩、回读去重和写入中断还要在隔离台账中验收。
- 同日取证时 Windows CCS 默认库中还没有这批会话的 `codex_session` 明细。该结果是一次只读快照。
- 扩展规划时只读确认本机默认 aha 台账为 schema 4，已含逐笔用量、历史日汇总、项目和价格依据。这里只留存在性和类型，真实业务数量、项目名称、会话 ID、路径、金额和正文不随任务提交。

## 现有实现依据

| 位置 | 相关行为 |
| --- | --- |
| [README](../../../../../../README.md#历史保留与核对) | aha 自有台账独立查询，旧历史、已确认项目和冻结报销材料随完整备份保留 |
| [session_meta.py](../../../../../../src/aha/session_meta.py#L59) | 已支持读取普通与 Zstandard 压缩日志头，当前从 `session_meta` 取会话、目录和父会话依据 |
| [projects.py](../../../../../../src/aha/projects.py#L17) | Windows 与 POSIX 各自规范化路径，现有归属合同可复用 |
| [domain.py](../../../../../../src/aha/domain.py#L183) | 旧明细按应用、来源类型和请求标识派生记录键，已入账记录有持久身份 |
| [sync.py](../../../../../../src/aha/sync.py#L399) | 使用分批暂存及单写入发布，并处理记录版本、证据、核对和派生统计 |
| [sources.py](https://github.com/NightingaleWK/aha/blob/dc41d0d68b93f118839f82f8a02c1da6d339dc8d/src/aha/sources.py#L51) 和 [sql_dump.py](https://github.com/NightingaleWK/aha/blob/dc41d0d68b93f118839f82f8a02c1da6d339dc8d/src/aha/sql_dump.py#L250) | 当前两个 CCS 原始入口分别为 SQLite 和 SQL 投影读取 |
| [server.py](../../../../../../src/aha/server.py#L471) 和 [app.js](../../../../../../src/aha/web/app.js#L342) | 启动、手动同步、SQL 导入和本机来源绑定的入口 |
| [migrations.py](../../../../../../src/aha/migrations.py#L135) 和 [backup.py](../../../../../../src/aha/backup.py#L130) | 现有 schema 3/4 兼容依赖版本对应的结构和 DDL 校验 |
| [backup.py](../../../../../../src/aha/backup.py#L648) | 完整还原先在独立目录校验数据库、清单与冻结包，再受控升级和发布 |
| [evidence.py](../../../../../../src/aha/evidence.py#L474) | 新材料现有版本和成本来源说明需适配，已冻结原包由既有原字节下载链保护 |

## 日志与重叠证据

- 当前样本的统计投影来自 `session_meta`、`turn_context` 和 `event_msg/token_count`。样本有 `last_token_usage`、`total_token_usage` 与缓存字段。累计快照、重复快照、续写和分叉须按已有形态建立测试后再选择计量规则。
- CCS 历史明细中的标识由旧导入器生成。上游 4.0.40 的本地键按根会话及后缀生成，而且物理分卷会参与序号语义。早期版本的标识和归一方式可能不同。对账需核验来源算法及同一事件依据，时间、模型或 Token 值相同只用于发现候选。 [CCS 4.0.40 写入依据](https://github.com/farion1231/cc-switch/blob/v4.0.40/src-tauri/src/services/session_usage_codex.rs#L2538-L2570)
- 既有上游研究还记录了远程压缩用量、缺父分支、旧日汇总与参考价格等边界。实现使用原生文件与合成回执验证这些边界。 [既有来源研究](../../../2026-10/10-27-codex-usage-evidence/research/source-findings.md)
- 高频从 Windows 扫 WSL UNC 已有实际性能故障报告，所以先验证在 WSL 内按需读取和增量成本。 [CC Switch #6180](https://github.com/farion1231/cc-switch/issues/6180)
