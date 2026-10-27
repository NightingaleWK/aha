# CC Switch 用量数据与报销证据研究

研究日期：2026-10-27。状态：规划依据；不是实现完成或财务验收结论。

## 研究范围与来源

- 上游：`farion1231/cc-switch`，固定研究提交 `e55d8a21b3897b595b746e9f2139716b2931641d`，避免后续默认分支变动影响引用。
- [上游数据库定义](https://github.com/farion1231/cc-switch/blob/e55d8a21b3897b595b746e9f2139716b2931641d/src-tauri/src/database/mod.rs#L54)：`SCHEMA_VERSION = 23`；与所提供 SQL 的 `user_version: 23` 一致。这是数据库版本，不是客户端版本。
- 输入备份：`/mnt/c/Users/djsyw/Desktop/cc-switch-export-20261027_090026.sql`。
- 原件大小：4,184,464 字节；SHA-256：`1c19a1b1c0da4355bcb4b98c6a47d909619b92507cebf9ad2c8f5eb8e3c7042b`。研究结束复算一致。
- SQL 头生成时间为 `2026-10-27 01:00:30`，未携带时区；文件名为 `090026`。不能仅凭两者认定导出的准确北京时间。最新明细事件时间可单独确认。
- 用户截图：`/mnt/c/Users/djsyw/AppData/Local/Temp/codex-clipboard-45863a3c-76b7-43b6-80cf-2d2377b52980.png`。图中“当天”总成本为 5.86 USD、122 条记录，供应商为会话日志；截图与备份截点不同，不作同截点对账。
- 现有证据目录：`/mnt/c/Users/djsyw/OneDrive/知识库/工作/AI 费用记录`。只读取文件清单、CSV 表头和行数；未输出 API Key、账号、IP 或完整对话。

## 上游源码确定的行为

### 1. 成本是估算值，数据可以不经过 CCS 代理

[用量说明](https://github.com/farion1231/cc-switch/blob/e55d8a21b3897b595b746e9f2139716b2931641d/docs/user-manual/zh/4-proxy/4.4-usage.md#L12)说明用量来自路由请求日志或本地会话日志；会话导入不要求开启本地路由。[总成本定义](https://github.com/farion1231/cc-switch/blob/e55d8a21b3897b595b746e9f2139716b2931641d/docs/user-manual/zh/4-proxy/4.4-usage.md#L54)是按模型定价配置估算的费用。

[Codex 记录写入](https://github.com/farion1231/cc-switch/blob/e55d8a21b3897b595b746e9f2139716b2931641d/src-tauri/src/services/session_usage_codex.rs#L2297)按模型查价，以 `CostCalculator::calculate_for_app("codex", ...)` 计算成本，写入四项金额和总额。`provider_id` 固定为 `_codex_session`，`data_source` 固定为 `codex_session`。

这类数据可证明本地记录的使用与参考价值，不能单独证明每次请求实际扣款，也不能仅凭其供应商列区分官方订阅与历史中转使用。需要用户选择实际订阅使用的时间段并说明归属。

### 2. 输入 Token 有三个历史语义，归一后才能合计

[统一 SQL 规则](https://github.com/farion1231/cc-switch/blob/e55d8a21b3897b595b746e9f2139716b2931641d/src-tauri/src/services/sql_helpers.rs#L30)：

| `input_token_semantics` | Codex 新增输入的计算 |
| --- | --- |
| `0`（历史） | 当输入不少于缓存读取时，输入减缓存读取；否则保留输入原值 |
| `1`（包含缓存的输入） | 当输入不少于缓存读取与写入之和时，输入减缓存读取与写入；否则保留输入原值 |
| `2`（已归一的新增输入） | 直接使用输入原值 |

CCS 展示的总 Token 为新增输入、输出、缓存读取和缓存写入之和。[成本计算器](https://github.com/farion1231/cc-switch/blob/e55d8a21b3897b595b746e9f2139716b2931641d/src-tauri/src/proxy/usage/calculator.rs#L70)使用 Decimal，并分别按百万 Token 单价计价，倍率作用于最终合计。展示归一规则与当前计算器对异常值的处理不完全相同，工具不能把旧行一概套用新行规则。

建议导出同时保留原始输入、语义标记和归一后的新增输入；总额默认沿用备份内已保存金额，避免无意重定价。

### 3. 旧记录转成日汇总并删除明细

[启动流程](https://github.com/farion1231/cc-switch/blob/e55d8a21b3897b595b746e9f2139716b2931641d/src-tauri/src/database/mod.rs#L156)调用 `rollup_and_prune(30)`。[汇总逻辑](https://github.com/farion1231/cc-switch/blob/e55d8a21b3897b595b746e9f2139716b2931641d/src-tauri/src/database/dao/usage_rollup.rs#L116)按本地日期、应用、供应商和模型等维度汇总，保存为新增输入语义 `2`，随后删除旧明细。

因此旧日期仍可导出每日费用和用量，但无法从该备份还原逐次时间、会话 ID 或请求 ID。不能伪造逐次记录，也不能将整日汇总任意按小时拆分。

[统计期间规则](https://github.com/farion1231/cc-switch/blob/e55d8a21b3897b595b746e9f2139716b2931641d/src-tauri/src/services/usage_stats.rs#L865)仅将筛选完整覆盖的本地日纳入日汇总；[总额查询](https://github.com/farion1231/cc-switch/blob/e55d8a21b3897b595b746e9f2139716b2931641d/src-tauri/src/services/usage_stats.rs#L943)组合有效明细与日汇总。

备份日汇总只有日期，没有原始时区字段。首版建议以 `Asia/Shanghai` 为用户默认时区，并记录日汇总来源时区的假设；未知时区不能描述为已从备份验证。

### 4. 原始会话日志直接解析有较多边界

[Codex 解析器](https://github.com/farion1231/cc-switch/blob/e55d8a21b3897b595b746e9f2139716b2931641d/src-tauri/src/services/session_usage_codex.rs#L1229)处理累计快照、逐次 `last_token_usage`、重复限额快照、远程压缩记录、线程分页和父历史重放。[分支处理](https://github.com/farion1231/cc-switch/blob/e55d8a21b3897b595b746e9f2139716b2931641d/src-tauri/src/services/session_usage_codex.rs#L2074)识别父历史前缀；无法可靠解析的文件可能暂缓导入。

[跨来源过滤](https://github.com/farion1231/cc-switch/blob/e55d8a21b3897b595b746e9f2139716b2931641d/src-tauri/src/services/usage_stats.rs#L479)避免路由记录与会话导入双计。所给备份明细均为 `codex_session`，本次没有混合代理明细，但这并不证明历史解析本身绝无漏记或重复。

建议首版消费 CCS 已整理的数据；原生 Codex JSONL 导入与项目路径推断作为后续能力，避免为 CSV 导出重新实现整套采集器。

### 5. 会话导入中的状态码与请求 ID 是本地生成字段

[写入代码](https://github.com/farion1231/cc-switch/blob/e55d8a21b3897b595b746e9f2139716b2931641d/src-tauri/src/services/session_usage_codex.rs#L2379)将状态码写为固定的 `200`；[请求 ID](https://github.com/farion1231/cc-switch/blob/e55d8a21b3897b595b746e9f2139716b2931641d/src-tauri/src/services/session_usage_codex.rs#L2208)由本地线程与事件序号等组成。导出不能据此声称拿到了官方 HTTP 成功记录或官方账单流水号。

### 6. CCS 现有 SQL 导出覆盖整个数据库

[导出命令](https://github.com/farion1231/cc-switch/blob/e55d8a21b3897b595b746e9f2139716b2931641d/src-tauri/src/commands/import_export.rs#L30)调用 `db.export_sql`。用户备份中除了用量，还有供应商配置、提示词、MCP 与其他设置。报销证据包应只保留用量及必要溯源信息，不附送原始全库 SQL。

上游采用 [MIT License](https://github.com/farion1231/cc-switch/blob/e55d8a21b3897b595b746e9f2139716b2931641d/LICENSE)。若后续实际复用代码，保留相应版权与许可证；当前仅据源码制定独立实现的数据契约。

## 备份实际检查结果

| 项目 | 结果 |
| --- | --- |
| 模型价格记录 | 238 条 |
| 逐条用量明细 | 10,852 条，全部为 `codex` / `codex_session` / `_codex_session` |
| 明细最早事件时间 | 2026-09-28 10:01:40 +08:00 |
| 明细最新事件时间 | 2026-10-27 08:58:11 +08:00 |
| 明细中实际出现的日期 | 18 个本地日期；不将没有记录的日期自动判定为零消耗或采集故障 |
| 明细保存成本合计 | 703.4355190 USD，CCS 记录的参考成本 |
| 全部日汇总 | 118 条，含其他应用 |
| Codex 日汇总 | 110 条，代表 35,500 条历史用量记录 |
| Codex 日汇总日期 | 2026-06-17 至 2026-09-24，有记录的日期并非每日连续 |
| Codex 日汇总保存成本 | 3317.48087702 USD，CCS 记录的参考成本 |
| 明细与日汇总日期交集 | 按 +08:00 对明细分日后，交集为 0 |
| 明细缺少会话 ID | 0 条 |
| 明细负 Token、缓存读取大于原始输入 | 各 0 条 |
| 金额分项核对 | 全部 10,852 条：分项之和乘倍率等于保存总额 |
| 无模型价格的明细 | 45 条，模型为 `codex-auto-review`，保存总额为 0；需要显示“未定价”，不能据此推断免费 |
| 现价重算与历史保存值不同 | 有价格的 10,807 条中，691 条不同：`gpt-6-sol` 64 条、`gpt-6.1-sol` 627 条；未确定是历史价格差异还是其他计价变动，不直接认定错误 |
| 会话去重附表 | 0 条；仅此不足以证明曾否发生旧版导入问题 |

一个可用于后续验收的完整日期样例是 2026-10-26：793 条明细，保存成本合计 32.8928704 USD。该样例用于核对筛选及导出一致性，不预设它属于哪个项目或何种付费通道。

本次检查证明数据库内字段与金额的若干自洽关系；未读取原始 Codex 会话逐条复核，未取得官方账单或支付凭证，不将上述合计当作本次待报销金额。

## 现有 CSV 习惯

- `fluorite-萤石-大通石油数据上传工具`：两个 `usage_起日_to_止日.csv`，分别 4,142 和 2,086 行。
- `liuying-流萤-运维管理平台`：一个同格式 CSV，1,129 行。
- 用量 CSV 有 `Time`、`API Key Name`、`Model`、`Reasoning Effort`、Token、倍率、`Billed Cost`、`Original Cost`、耗时等 21 列，采用 UTF-8 BOM。
- `针对php2shell漏洞专项修复`：`amount` 19 行、`cost` 6 行，分开保存用量金额和实际成本；部分列涉及凭据，不应原样复制到新工具的分享导出。

可以延续按项目目录及日期区间命名的习惯，同时在新工具中明确 `estimated_cost_usd` 等字段含义，避免沿用 `Billed Cost` 暗示订阅按次结算。

## 检查方法与可复查查询

原 SQL 不在真实 CCS 数据库执行。研究将允许表的建表与 INSERT 语句载入临时内存 SQLite；只接受指定表 INSERT，SQLite authorizer 拒绝其他写操作、附件数据库及函数调用。未载入供应商、MCP、提示词等配置数据。金额使用 Python `decimal.Decimal` 逐条求和；没有将浮点 SUM 的结果当作精确费用。

载入后执行的关键查询如下，时间分日显式使用 +08:00，不依赖执行主机时区：

```sql
SELECT app_type, data_source, provider_id, input_token_semantics, COUNT(*)
FROM proxy_request_logs GROUP BY 1, 2, 3, 4;

SELECT MIN(created_at), MAX(created_at), COUNT(DISTINCT session_id)
FROM proxy_request_logs WHERE app_type = 'codex';

SELECT date(created_at, 'unixepoch', '+8 hours') AS local_day, COUNT(*)
FROM proxy_request_logs WHERE app_type = 'codex'
GROUP BY local_day ORDER BY local_day;

SELECT COUNT(*), SUM(request_count), MIN(date), MAX(date)
FROM usage_daily_rollups WHERE app_type = 'codex';

SELECT DISTINCT date(created_at, 'unixepoch', '+8 hours')
FROM proxy_request_logs WHERE app_type = 'codex'
INTERSECT
SELECT date FROM usage_daily_rollups WHERE app_type = 'codex';

SELECT l.model, COUNT(*)
FROM proxy_request_logs l
LEFT JOIN model_pricing p ON p.model_id = l.model
WHERE p.model_id IS NULL GROUP BY l.model;

SELECT input_cost_usd, output_cost_usd, cache_read_cost_usd,
       cache_creation_cost_usd, cost_multiplier, total_cost_usd
FROM proxy_request_logs;
```

最后一条结果逐条按以下方式核对，未发生提前舍入：

```python
from decimal import Decimal
parts = sum((Decimal(row[k]) for k in (
    'input_cost_usd', 'output_cost_usd',
    'cache_read_cost_usd', 'cache_creation_cost_usd'
)), Decimal(0))
assert parts * Decimal(row['cost_multiplier']) == Decimal(row['total_cost_usd'])
```

## 产品建议与后续收敛

首版建议为 Windows 本地的“AI 费用凭证导出器”：选择数据来源 → 选择日期或时间段 → 填写项目与说明 → 预览用量和金额 → 导出。

- 首期输入建议为 CCS SQL 备份和只读 SQLite 快照。后续已验证 Windows 默认路径、只读连接及结构版本，见 `runtime-and-delivery.md`；WAL 并发快照与界面尚待实施验收，不描述为已经支持。
- 核心输出：逐条明细 CSV、每日汇总 CSV、一页可打印费用说明、包含筛选及来源校验信息的清单。旧数据只输出真实存在的日汇总，逐条表不补造旧记录。
- 原始输入、CCS、Codex 保持不变。SQL、密钥、完整对话不进入分享包；内部哈希用于复查导出来源，不宣称它能认证官方账单。
- 该次研究最初未纳入项目识别；后续已通过会话目录验证，并获用户确认项目对象和多目录绑定，最新范围见 `prd.md`、`research/project-identification.md`。原生用量重新采集、多人云平台和复杂分摊引擎仍不属首期。
- 2026-10-27 用户以“按你说的”确认：期间参考成本作为使用证明，允许另填申请金额和依据；首期不自动分摊订阅。最终首期约定以 `prd.md` 和 `design.md` 为准。
