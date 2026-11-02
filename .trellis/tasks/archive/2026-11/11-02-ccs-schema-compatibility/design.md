# CCS 结构版本 24 兼容设计

## 状态与依据

2026-11-02 用户回复“可以，继续吧”，已批准本方案实施。依据见 [需求](prd.md) 与 [只读研究](research/compatibility-findings.md)。

## 版本边界

1. 定义共享的 CCS 外部支持集合 `{23, 24}`，供 SQLite、SQL 和错误消息复用。未知版本明确包含实际版本与支持范围；不自动接受任意较大版本。
2. 内部规范化投影继续为版本 23，与源 CCS user_version 分离。澄清常量命名/用途，并保持历史 JSON、record_key、row_fingerprint、allowed_projection_sha256 兼容；不机械替换仓库中所有 23。
3. 应用库仍为 schema3，不清库、不重建、不新增业务迁移。旧 manifest3/4 ZIP 原字节下载。

## 来源读取与同步

```text
CCS SQLite / 字面量 SQL
  → 验证外部版本 23 或 24 + 既有必要字段
  → 允许用量投影（规范化格式版本 23） + 观察到的外部 source_schema_version
  → 原 staging / 核对 / 原子发布
  → sync_runs.result_json 记录本次实际源版本
  → 原本地查询、归属、冻结材料
```

- SQLite `_validate_schema` 返回验证后的真实版本；scan_sqlite 的 source 元数据带该整数，load_sqlite 内部投影仍为 23。保留三个表与字段集合检查、同事务一致性、取消和预算。未知版本须在 sink 前拒绝。
- SQL 版本声明集合必须只有一个受支持整数；23 与 24 同时出现仍视为不一致。继续识别真实注释/字面量 PRAGMA，不从字符串伪装内容取版本，不执行任何 SQL；scan_sql_dump source 返回本次声明版本。
- `_publish` 在现有 result_json 中持久化真实外部版本，sync_status/HTTP 可观察；只记录本轮，不把最后一次版本映射为全体历史的来源。历史投影没有新字段时留未知，不从内部 schema_version=23 猜原始外部版本。
- 现有来源 identity 与投影内容 hash 不纳入外部版本差异。只改 user_version 的合成源从 23 升 24，重复同步不增加 facts/content versions、不改占用；真实金额/内容变化仍进入原修订核对链路。

## 查询与材料

- 分析 schema_version 仍表示规范化投影 23；明确添加/复用 usage_projection_schema_version，避免误认为本次 CCS 结构。
- 保留导出信息中旧 source_schema_version=23 以免破坏既有消费者，同时增加明确的 source_schema_version_scope=normalized_usage_projection 和 usage_projection_schema_version=23；在 README/spec 解释旧字段的兼容含义。该固定旧字段不再单独宣称原始 CCS 的真实结构版本。
- 不新增猜测的 source_schema_versions，不从最近一次同步或适配器支持列表制造冻结成员的逐条来源证明；真实源版本可从本轮同步记录追溯。未来若需要逐成员来源证明，应另行设计冻结溯源契约。
- 旧 ZIP/冻结 JSON 不回填、不重建；新字段限新生成分析和材料，保持现有 manifest4 四文件、精确费用与时间合同。

## 兼容、风险与回退

- 未来未知版本依然失败，错误提示更可诊断；必要字段缺失与不合法数值仍失败。
- CCS 自然清理/修订或 fork 识别可能带来正常的来源差异，按 needs_review 机制呈现；本任务不自动确认核对事项。
- 真库只做只读来源；真实 aha 的回归用原生 SQLite 一致备份到隔离目录，保留源身份并核对必要状态，不能直接同步写入默认用户资料。
- 产品按补丁版本发布（建议 0.3.1），同步项目元数据与 UI 使用的版本来源；不引入新 UX 或数据结构。
- 回退仅需恢复旧 EXE/本任务源码；既有应用数据协议保持兼容，旧 EXE 对 CCS24 仍会拒绝读取。交付前重新识别同名文件，保留必要可恢复旧版，不覆盖未知文件。

## 执行责任

按当前 Codex/Trellis 模式，实施与检查分别交给 trellis-implement / trellis-check 子代理；主会话维护规划、协调发现、更新规范、构建交付和收尾。每次派发须带 Active task 与明确文件责任，告知共享代码库中不能撤销他人改动。只在用户批准本方案、task.py start 后派发。
