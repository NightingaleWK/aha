# Windows 与 WSL Codex 原生采集

## 1. 范围

修改 Codex 会话读取、来源设置、事件去重、进度提交、模型参考价或首次接续时阅读。现行输入为确认的 Codex 会话目录，既有 aha 台账及完整备份继续作为历史依据。

## 2. 签名

```python
CodexSource(kind: Literal["windows", "wsl"], root: str, distribution: str | None = None)
probe_source(source: CodexSource) -> CodexSource
scan_source(source, load_cursor, on_event, on_cursor, *, cancel=None)
Store.sync_codex(source, source_id, *, trigger="manual", startup_id=None, cancel=None, since=None)
```

来源配置由 `source_bindings` 按安装和还原标识确认。[HTTP 与页面合同](../frontend/local-web-contract.md) 定义配置、同步、状态和取消。应用 schema 5 增加 `codex_file_progress` 和 `codex_event_evidence`，分别保存物理文件进度和来源事件证据。

## 3. 数据与事务

- Windows 按确认的本机目录读取，留空使用有效 `CODEX_HOME` 或用户目录下的 `.codex`。WSL 明确选择发行版，由 Windows `wsl.exe` 在其中执行固定只读 Python 3 文件操作。目录和相对路径作为数据传递，枚举限制在 `sessions` 和 `archived_sessions`。打开时重检文件身份与目录边界。
- 读取普通 JSONL 和 Zstandard 归档，判断文件增长、替换、截断和未完整尾行。结合已保存身份、字节偏移和核对依据续读。文件、单行、解压、事件与作业预算均有界，超限记录安全原因和覆盖。原始行只用于当次解析，持久化仅保存允许的事件、目录、模型、计数和金额依据。
- 显式响应身份由会话和响应标识稳定派生。累计快照的事件依据包含会话、上下文、原始时刻和规范化计数。同一请求的显式和快照证据合并，跨文件无法证明对应时保留核对。相同时间和 Token 值无法证明两个不同的显式响应重复。
- 已入账金额和业务关系沿用当前版本。采集新原生事实使用程序内版本化参考价与十进制，证据保留模型价及出处。已验证新事件与历史可能重叠时，先保留现有台账和占用，待核对的新依据不进入确定合计。
- 读取阶段仅写任务的最小暂存投影，结束后进入本地分批 staging。起始日按北京时间含当日，早于该日的日志仍可建立解析基线。每端使用独立发布事务同时提交事实、证据、游标、归属和派生统计。重新扩大日期范围时按新范围读取，已核实消费沿用同一个逻辑身份。
- 已完成来源与后续取消或失败可以同时出现在同一作业。来源状态保留每端上次成功时刻，存在问题的本次读入以实际覆盖表示。还原或换机后重新确认物理来源，继续用事件证据去重。

## 4. 错误矩阵

| 条件 | 行为 |
| --- | --- |
| 来源未确认 | `source_binding_required`，历史查询继续可用 |
| 所选来源根或 WSL 不可达 | 逐端 `unavailable`，另一端可独立提交 |
| 未知记录形态、超限或证据不完整 | `partial`，展示覆盖与计数，未确定部分待核对 |
| 取消或写入失败 | 已提交端保留，未提交游标可重放 |
| 两次确认交错 | `stale_source_binding`，重新打开设置后使用当前配置 |
| 模型没有参考价 | Token 可统计，参考成本缺价状态明确 |

## 5. 正常、基础与失败

- 正常：两端读到各自事件，复制和压缩回读时仍为同一消费。批次使用其中已确认、未占用的成员。
- 基础：只确认一个来源也能同步。安装发生变化、旧日志缺失或还原后，已有历史和冻结包仍可查询。
- 失败：Windows 已完成而 WSL 失败，显示两端结果。重新连接 WSL 后接续它自己的游标。

## 6. 验证

- `test_codex_sessions` 核对显式与累计事件、分段、重复、断点、压缩、安全边界和有界清理。
- `test_native_sync` 核对去重、旧明细/整日汇总核对、事件版本、游标与事实同一事务、保存占用及原包。
- `test_http`、`web_state.test.cjs` 核对绑定、终态、逐端保留、迟到请求和继续使用本地查询。Windows 对真实 WSL 的验证单独留证。

## 7. 容易出错的实现

```python
# 错误：用物理文件位置标识消费，复制过的日志会重复入账。
event_key = (source_root, relative_path, byte_offset)

# 正确：文件位置用于续读，逻辑身份及其证据进入台账。
store.sync_codex(source, confirmed_source_id, trigger="manual")
```
