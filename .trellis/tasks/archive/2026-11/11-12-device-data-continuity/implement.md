# 集成执行计划

## 门禁

- [x] 建任务批准、只读调查、使用方式确认、唯一副本保护。
- [x] PRD收敛，父子边界/依赖，设计与执行计划。
- [x] 已展示最终方案；2026-11-12用户回复“按你说的做”，批准实施、当前台账接续和桌面EXE交付。
- [x] 按1.4启动父任务及两个子任务，创建codex/device-data-continuity分支，按模块所有权并行实施。

## 顺序

1. full-backup-restore：完整备份/新目录还原；依赖现有保护副本；用有报销、多版本、作废原包的合成库验证。
2. ccs25-device-recovery：CCS25、来源隔离/去重、历史cwd、历史入口与核对后预览。独立模块可与备份核心并行实施；真实原库写入等完整恢复验收通过。
3. 父任务集成：一致副本派生的新目录运行新版，逐项核对原事实/版本/项目/cwd/汇总口径。真CCS只读，记录当次重叠/新增/候选。
4. 最终源码原生构建Directory并验收，再OneFile独立验收；系统KnownFolder确认实际桌面，识别同名exe归属/占用后交付aha.exe并记录SHA。
5. 正常退出已识别旧实例，最终程序启动当前资料，按授权建立新电脑来源绑定/补同步，核对旧历史及新增、项目、全历史/当天预览。事实候选不得自动跳过。
6. 更新spec与中文What's New，记录源码/运行时/成品/备份指纹。核实清理任务自有环境、合成库、构建缓存，保留真实资料/恢复副本。按项目流程集中处理提交/归档与发版评估。

## 检查

使用符合SQLite门禁的Windows x64隔离环境；主环境不改。Linux环境先核实SQLite，不放宽门禁。

```text
<qa-python> -m unittest discover -s tests -v
<qa-python> -m ruff check src tests scripts
<qa-python> -m mypy src/aha
<qa-python> -m compileall -q src/aha
node --check src/aha/web/app.js
node --test tests/web_state.test.cjs
<build-python> scripts/build_windows.py --build-root <任务目录> --stage Directory
<qa-python> scripts/verify_windows_artifact.py --exe <Directory exe> --source-root <源码> --data-root <合成资料> --report <报告>
<build-python> scripts/build_windows.py --build-root <同目录> --stage OneFile --directory-verified
```

真实浏览器覆盖历史空范围、核对确认、来源绑定、备份/还原与焦点。相关Office/托盘/构建专项按实际变化补，不把无桌面检查写成物理操作。桌面副本先用合成data-dir验证重开、原包、退出，再执行已授权的原账本接续。

## 回退

- 原库写入前失败：保留旧程序/原库/保护副本，仅修隔离实现。
- 接续失败：正常退出新版，保全现场，使用完整副本恢复到独立目录，不混搭DB/材料，不覆盖唯一保护副本。
- 最后源码修改后重建成品；未完成原库接续与桌面交付时不归档父任务。

## 最终完成状态

- [x] R1–R5：CCS25兼容、设备来源隔离、去重/候选、历史目录、空时段及核对后预览。
- [x] R6：一致完整备份、新目录恢复、HTTP/CLI/页面、损坏/中断/占用保护。
- [x] R7：真实副本验收；接续前保护；真实默认台账接续，旧39,463事实及5项目保留，新明细2,757、待核对0；再次同步新增0；接续后完整D盘备份。
- [x] R8：最终Directory/OneFile与桌面副本独立验收、实际桌面和原D程序更新、中文片段、规范/说明、任务临时资料清理。
- [x] 最终317项Windows Python测试、Node34及适用静态检查全部通过；浏览器/Excel/A4专项通过。物理托盘与云端候选验收不冒充通过，列为正式发布缺口。
- [x] Phase3.4：用户已确认具体36文件清单，本地工作提交`c7c6acc87531df6ebb8ed5bc346a624490e8ac0a`完成。
- 工作提交后使用本轮Trellis收尾脚本归档两子任务及父任务并记journal；完成状态以task.json与Git归档/journal提交为准。
- [x] 用户选择“积累到下一版”，保留3条待发说明与后续运行时/云端候选/物理托盘条件；本次未推送或发布。

详细实际证据与边界见[verification.md](verification.md)。
