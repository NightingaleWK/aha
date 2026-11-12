# 实施验收进度

本记录随实际执行更新；未执行项不计通过。用户已批准真实台账修复和桌面交付，并在本机实测后追加授权本地提交、main合并、git push、正式发版及归档收尾；不重复确认已授权事项。

## 已完成

- 用户产品方针：记住逐笔消费、稳定归属项目、项目费用可追溯、报销材料与成员一致。D1默认保留历史已确认关系。
- Trellis任务已in_progress，分支codex/project-record-continuity。core/UI/evidence均已实施，independent_check最终无阻塞问题；详见research/final-code-review.md。
- 原生QA：Python3.12.16 x64/SQLite3.53.1，任务环境在Windows LocalAppData/Temp/aha-project-record-continuity-20261112；全仓Ruff和26源文件strict mypy通过。Node语法及53项状态回归通过。
- 恢复前已将真实schema3全备份和旧EXE保存在D盘持久备份，research/protection.json记录路径和SHA；该保护阶段使用提交版备份实现，只读原库。后续真实修复见primary-recovery.json，不能把前阶段“未写”误读为最终状态。
- 独立真实副本schema3→4、347旧会话目录恢复及37,165明细重新关联通过；已归属1,500→38,665，剩余3,438明细及110行参与统计的日汇总待归属。77,603代表请求量、原事实/费用/Token/claims/旧材料/coverage均保留，所有项目+未归属守恒。缺日志刷新后关系hash不变；schema4完整备份/独立恢复通过。见research/real-copy-association-verification.json。
- 源程序原生Edge流程通过；Directory冻结EXE已构建并通过标准原生门禁及9项归属浏览器流程，五种宽度/console0/跨页80/整会话80+未来/材料81条与重开原包SHA一致。见research/directory-verification.json和native-ui-directory.json。
- Directory SHA256：c9934c01f2f41bef9c329c8439a7bf0cc33de1623928a1dcadd1e726d3e739ae；构建前后source-fingerprints一致。
- 主合同、schema4/旧备份、前端状态和README已同步，中文变更片段及累计v0.5.0候选预览已准备；release validate WORKTREE相对v0.4.1通过。

## 全量检查说明

core早期343项全量仅当前schema硬编码3的一项失败，已改权威常量并定向通过。主会话首轮最终入口少加仓库根路径，造成test_rebuild_trial_data模块导入失败（335测试通过/1导入错误），归档在python-harness-import-failure.*；这是任务脚本问题，未修改产品迁就夹具。已修正入口并重新执行最终整仓检查，最终以python-final.json为准。

## 后续门禁

- [x] 最终整仓Python351项、Ruff、mypy26源文件、compileall全部通过；Node53项通过。
- [x] Directory Excel与A4 PDF/逐页图检查通过。
- [x] OneFile构建、标准原生门禁、新归属UI与Excel/A4独立检查通过。SHA256：9ccd827d1dc4edbbda8b4a8bf30abe3867143950b828a7ffc5217c97e334e97a。
- [x] 最终OneFile在受保护真实规模副本运行升级/HTTP恢复/重开，旧事实与关系守恒，原库仍未写。实测冷启动含schema3升级11.367秒，预览2.004秒，原子恢复17.745秒；这是当前42,220行规模，非百万/千万性能证据。
- [x] 完成上述门禁后保存最新schema3完整备份，原子交付实际桌面，使用交付文件升级/恢复真实台账并核对，再保存schema4完整备份、独立恢复核对全部事实与关系。真实操作通过已验证实例入口，不构造Store试写原库；没有强杀进程或自动在线回退。
- [x] 实际桌面文件以合成资料再次通过标准原生门禁及9项新归属UI流程，从桌面重开/退出、原包重下、五种宽度/console0均通过；产品指纹和SHA一致。见desktop-verification.json、native-ui-desktop.json。
- [x] 盘点并清理本任务的验证副本、QA环境、构建中间物和缓存，逻辑文件量1,364,373,147字节；保留真实原库、持久D盘备份/旧EXE、成品及2,090,763字节小型合成验收材料。11个Edge兼容junction均核实只指向任务内部，先拆链接再清理，不跨边界。见cleanup.json；临时材料新旧路径映射见retained-evidence.json，原验收报告字节保持不变。
- [x] 清理后使用保留的基础原生解释器核对成品/备份/原验收报告SHA，桌面文件仍可重开同一默认服务。期间正常同步新增559条消费；逐键与修复后备份比较原42,220行及其旧版本、逐笔关系/会话默认/审核事件，原事实/金额/Token/归属完整。当前当次核对已归属39,224条；不是把正常增长误判为破坏原基线。只读审计的额外临时目录也已删除。见final-native-state.json。
- [x] 准备具体本地提交/归档计划及累计发版评估；用户已批准，功能提交da826a7及测试修复9dcf2e9已推送，PR#9/#10已合main；六scope验收回执cae26d6与v0.5.0正式公开完成。归档/日志按已批准Trellis计划收尾，实际Git记录为准。

## 真实交付结果

- 实际桌面：`C:\Users\djsyw\Desktop\aha.exe`；既有已识别的`D:\Program Files\aha.exe`也同步为相同SHA的成品。已请求正常浏览器打开，未把命令成功冒称看到了浏览器窗口。
- 修复时42,220物理行不变，其中42,103条明细、117行日汇总（110行参与统计，7行已被明细覆盖）；347会话恢复，37,165条旧明细重新归属。修复时已归属1,500→38,665，之后正常同步的新增消费单独计数。
- 仍待确认3,438条明细和110行参与统计的日汇总；其中旧机仅有目录但无项目规则的1,813条和新机有目录无规则的1,625条没有被猜测分配。全部消费归属尚未清零，项目管理的原因/目录/会话/日期筛选、跨页选择与预览可供继续处理。
- D盘持久目录：`D:\aha-backups\project-record-continuity-20261112-135506-f8009f`。最新修复前包`aha-before-final-apply-d948bde94b81.aha-backup`（schema3），修复后包`aha-after-project-associations-c48292ed1446.aha-backup`（schema4）；具体SHA及独立恢复证据见primary-recovery.json。该目录和原始保护包/旧EXE不在清理范围。
- 所有原实施代码门禁、Directory/OneFile/桌面原生验收、真实修复、原任务环境清理已完成；本地功能提交已批准并执行。归属合同及README/中文发布片段已与实际行为同步；新授权的正式发布环境与候选检查单独留证，任务归档待正式发布完成。

## 原实施检查边界与最终补验

以下段落保留正式发布前的检查边界；新生产候选的实际补验与公开结果见末尾“最终发布验收”。

Computer Use初始化/重试/reset均被宿主sandboxCwd URI拒绝，未发出桌面输入；不能声称物理托盘点击通过。实际门禁区分原生HTTP/Edge自动化、Excel COM、A4 PDF与物理操作。

最近核对公开版仍v0.4.1；累计CCS25/换机接续/完整备份及本次归属改进建议v0.5.0。原“积累到下一版”已由用户最新“现在发版”替代，已明确批准main合并/push/发布与归档。云端配方3.15.2与原本机3.12.16证据不能混同；新的3.15.2验证环境/实际候选/适用物理托盘证据正在补齐，尚未宣称已发版。最新状态见research/release-execution.md和release-readiness-check.md。

## 最终发布验收（已完成）

- v0.5.0 已正式公开：https://github.com/NightingaleWK/aha/releases/tag/v0.5.0 ，发布时间2026-11-12T08:51:47Z；实际tag/source均为12d213b5b3c3c505d24f73fc7888966f24435337。功能PR#9与发布PR#10均已合入main，六项验收回执提交cae26d6已推送。恢复workflow43185710907质量/inspect/candidate/prepare全部成功，build跳过，复用原草稿字节。
- 正式云端EXE/实际Desktop及D盘既有程序SHA均8991fa71cadd906678cb1b76d302921d1e874f022918f854a0540f2bb3d0e4d5，版本0.5.0；公开build-info与SUMS独立下载核对，源码/notes/runtime及标签一致。见research/release-publication.json。
- 新生产匹配Python3.15.2/SQLite3.53.4：351项Python全部通过、Ruff/mypy/compileall通过；Directory与确切云端OneFile分别完成原生检查及9项归属UI、Excel/A4与逐页图检查；实际桌面同SHA文件再次完整原生检查通过。六scope回执.release/acceptance/v0.5.0-project-continuity.json绑定真实M、生产runtime与实际证据，不修改旧312记录。
- 用户明确确认当前桌面最终v0.5.0三项物理托盘正常，见research/release-user-tray-v050.json；与先前312测试分开记录。
- 原实施root逻辑1,364,373,147字节已先清理；本次发布root另585,271,718字节已清理，D盘acceptance-records-v0.5.0保留1,798,354字节小型合成材料/QA记录。真实默认库、全部持久备份/回退EXE、最终成品、基础解释器和源码均保留。清理后默认程序健康并能重开同一服务，见research/release-cleanup.json及research/release-after-cleanup-runtime.json。
- 当前没有已知待发布产品改动；收尾仅规范、验收记录和Trellis归档/日志，不据此新增0.5.1。剩余人工待归属仍按业务清单继续处理，不伪造全部消费已归属。
