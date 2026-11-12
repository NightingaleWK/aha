# 本地提交与归档审阅计划

本机 EXE、真实台账恢复、完整备份、独立恢复及临时资源清理已完成。本计划仅处理当前分支的本地 Git 记录；不推送、不创建 PR、不公开发版。

工作区开始时除本任务规划记录外为干净；以下代码、测试、规范和任务记录均由本轮主会话及已授权子代理修改。没有未识别改动。

## 计划顺序

1. `feat: 持久保存项目归属并完善费用核对`
   将下列源码、回归、规范、README与中文变更片段作为一个完整功能单元提交。

- `.release/changes/project-record-continuity.json`
- `.trellis/spec/backend/ccs-source-compatibility.md`
- `.trellis/spec/backend/database-guidelines.md`
- `.trellis/spec/backend/directory-structure.md`
- `.trellis/spec/backend/index.md`
- `.trellis/spec/backend/logging-guidelines.md`
- `.trellis/spec/backend/project-association-contract.md`
- `.trellis/spec/backend/recovery-and-device-contract.md`
- `.trellis/spec/backend/time-range-contract.md`
- `.trellis/spec/backend/usage-evidence-contract.md`
- `.trellis/spec/frontend/local-web-contract.md`
- `.trellis/spec/frontend/state-management.md`
- `.trellis/spec/frontend/type-safety.md`
- `README.md`
- `scripts/verify_windows_artifact.py`
- `src/aha/associations.py`
- `src/aha/backup.py`
- `src/aha/batches.py`
- `src/aha/evidence.py`
- `src/aha/ledger.py`
- `src/aha/migrations.py`
- `src/aha/project_links.py`
- `src/aha/projects.py`
- `src/aha/queries.py`
- `src/aha/server.py`
- `src/aha/storage.py`
- `src/aha/web/app.js`
- `src/aha/web/index.html`
- `src/aha/web/style.css`
- `tests/test_assignment_coverage.py`
- `tests/test_assignment_migration.py`
- `tests/test_associations.py`
- `tests/test_http.py`
- `tests/test_migrations.py`
- `tests/test_projects.py`
- `tests/test_storage.py`
- `tests/test_time_ranges.py`
- `tests/web_state.test.cjs`

2. `chore(task): archive 11-12-project-record-continuity`
   由Trellis归档当前任务，将PRD/设计/实施/验收、脱敏聚合和哈希报告、可复现方法及本计划一并保留。任务记录约0.7MB；不包含真实数据库、备份包、EXE、截图或构建环境。归档前写入本地提交确认记录。

3. `chore: record journal`
   记录本次工作提交、真实修复与成品交付、剩余人工待归属、验收范围和继续积累到v0.5.0的选择。

## 不包含的文件与动作

- 未识别脏文件：无。
- 真实台账、修复前后备份、旧EXE和最终桌面/D盘EXE均位于仓库外，不进入Git。
- 不推送、合并远端、改动公开标签或发布；候选版本仅建议v0.5.0，沿用“积累到下一版”。
- 仍有3,438条明细及110行参与统计的日汇总待人工确认，任务收尾只表示归属功能和有依据的恢复已交付，不冒称所有消费已归属。

## 实际审阅证据

- [验收与交付](../verification.md)
- [默认台账恢复](primary-recovery.json)
- [桌面原生门禁](desktop-verification.json)、[新归属UI](native-ui-desktop.json)
- [清理](cleanup.json)、[清理后重开与旧范围逐键核对](final-native-state.json)
- [累计发版评估](release-assessment.md)、[What’s New候选预览](whats-new-preview.md)

确认本计划后按顺序执行三个本地记录步骤；未经确认不提交。

## 后续授权

用户随后明确要求“发了吧，然后工作收尾，任务归档，合并主分支main，git push”，并确认本人实测无问题。本地提交计划已获批准；最新发布选择改为现在发版。执行中保留既有验收证据并补齐实际候选，工作记录归档放在正式发布之后。

## 执行结果

用户追加授权已覆盖全部动作；本地功能da826a7、测试/规范9dcf2e9、生产候选验收cae26d6均已提交推送，功能/发布PR合入main，正式v0.5.0公开并完成成品/下载验证和清理。接续按本计划执行当前任务归档和日志记录，最后push main；不再重复确认。
