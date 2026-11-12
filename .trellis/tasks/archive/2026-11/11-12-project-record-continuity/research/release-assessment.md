# 本次实施后的发版评估

2026-11-12；本机成品与真实资料恢复完成。下文保留交付当时的评估；用户随后明确改为“现在发版”，授权提交/main合并/push/公开发布/归档。最新执行记录见release-execution.md，原延期描述不再代表当前选择。

## 公开基线与累计范围

本会话经 GitHub 连接器只读核对，最近公开版本仍为 [v0.4.1](https://github.com/NightingaleWK/aha/releases/tag/v0.4.1)，发布时间为北京时间 2026-11-05 22:37。当前本机 EXE 的产品版本仍为 0.4.1；它包含本轮工作树功能，不冒称已发布的 0.5.0。正式版本只在发布 PR 中统一递增。

相对公开基线，先前已经实施但未公开的内容为：CC Switch 25 兼容、换机来源隔离与历史接续、完整台账备份和独立目录恢复。本次新增持久逐笔项目关系、整个会话的持续分配、历史依据恢复、跨页待归属处理、项目费用概况和报销材料的归属覆盖说明。

累计含新增功能，建议候选 **v0.5.0**。本次影响项目费用核算，值得纳入最近一次功能发布；已完成本机交付，继续沿用用户此前明确选择的 **“积累到下一版”**，不额外发布同一 0.4.1 版本、不自行推送或合并发布 PR。该选择不宣称 GitHub 发布门禁已经满足。

## What’s New 预览

本次中文片段为 [.release/changes/project-record-continuity.json](../../../../.release/changes/project-record-continuity.json)，累计候选内容见 [whats-new-preview.md](whats-new-preview.md)。核心说明：

> 消费记录持续保存项目归属；换机后可按 aha 留存依据恢复历史关联，按目录、会话或时间跨页批量处理待归属记录，项目统计与报销材料同步披露归属覆盖情况。

升级事项已注明 schema3→4 前完整备份、旧版不能打开新库、旧完整备份仍可在新目录恢复；无依据和仅有日汇总的消费不会被自动猜测或拆分。

## 实际证据与公开前缺口

- 本机原生 Python 3.12.16 / SQLite 3.53.1：351 项 Python、Ruff、26 个源文件 strict mypy、compileall；Node 53 项全部通过。
- Directory 和 OneFile 各自通过标准原生门禁、9 项新归属 UI 流程、原生 Excel COM 语义值核对、A4 PDF 生成和逐页图检查。桌面同 SHA 的文件又独立通过标准门禁与 9 项 UI 流程；Excel/A4 的独立执行来自相同 SHA 的 OneFile，未冒称第三次 Office 检查。
- 真实规模独立副本及默认真实台账均完成升级/恢复；37,165 条明细恢复项目归属，事实/费用/Token/项目规则/占用/旧包与总量守恒保持，前后完整备份及修复后独立恢复验证通过。此处的 42,220 物理行不是百万或千万规模证据。
- 当前正式云端配方仍使用 Python 3.15.2，与本机实际验收的 3.12.16 不同；正式候选构建及其运行时、源码和产物指纹尚须按发布合同重新绑定和验收，不能复用本机回执直接放行。
- Computer Use 宿主在输入前拒绝初始化，未实际执行物理托盘点击；无桌面 HTTP、原生 Edge 自动化和托盘已启用不替代物理点击证据。云端候选与适用人工门禁齐备前，公开动作保持未完成。

若用户之后改变发布选择，可选择“先补齐发版条件”进入候选准备；本轮不重复询问既有延期选择。

## 最终正式发布与收尾

- v0.5.0 已正式公开：https://github.com/NightingaleWK/aha/releases/tag/v0.5.0 ，发布时间2026-11-12T08:51:47Z；实际tag/source均为12d213b5b3c3c505d24f73fc7888966f24435337。功能PR#9与发布PR#10均已合入main，六项验收回执提交cae26d6已推送。恢复workflow43185710907质量/inspect/candidate/prepare全部成功，build跳过，复用原草稿字节。
- 正式云端EXE/实际Desktop及D盘既有程序SHA均8991fa71cadd906678cb1b76d302921d1e874f022918f854a0540f2bb3d0e4d5，版本0.5.0；公开build-info与SUMS独立下载核对，源码/notes/runtime及标签一致。见release-publication.json。
- 新生产匹配Python3.15.2/SQLite3.53.4：351项Python全部通过、Ruff/mypy/compileall通过；Directory与确切云端OneFile分别完成原生检查及9项归属UI、Excel/A4与逐页图检查；实际桌面同SHA文件再次完整原生检查通过。六scope回执.release/acceptance/v0.5.0-project-continuity.json绑定真实M、生产runtime与实际证据，不修改旧312记录。
- 用户明确确认当前桌面最终v0.5.0三项物理托盘正常，见release-user-tray-v050.json；与先前312测试分开记录。
- 原实施root逻辑1,364,373,147字节已先清理；本次发布root另585,271,718字节已清理，D盘acceptance-records-v0.5.0保留1,798,354字节小型合成材料/QA记录。真实默认库、全部持久备份/回退EXE、最终成品、基础解释器和源码均保留。清理后默认程序健康并能重开同一服务，见release-cleanup.json及release-after-cleanup-runtime.json。
- 当前没有已知待发布产品改动；收尾仅规范、验收记录和Trellis归档/日志，不据此新增0.5.1。剩余人工待归属仍按业务清单继续处理，不伪造全部消费已归属。

此前延期建议已被用户现在发布的选择与上述实际公开结果替代，当前无需再选择发布动作。
