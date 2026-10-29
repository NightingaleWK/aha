# 提交计划（用户已确认）

用户已于2026-10-29明确回复“确认提交并归档（建议）”。按已确认清单提交一个完整功能单元，代码、对应测试、规范和验收记录在同一工作提交内。当前分支 `codex/form-time-filter`，基线 `447bc19`。

提交信息：`feat: 统一清爽表单与北京时间范围筛选`

内容：共享搜索/下拉/分段组件、分钟与快捷时间、A方案部分日说明、统计与冻结材料范围一致、manifest4及旧材料兼容。

验证：Linux与Windows203项回归（各有平台跳过）、Node6项、真实目录EXE13项及补充场景、Excel/A4、百万合成查询回归。具体证据见 verification.md、check-report.md、time-performance.md。

## 产品代码

- `src/aha/analysis.py`
- `src/aha/batches.py`
- `src/aha/evidence.py`
- `src/aha/queries.py`
- `src/aha/server.py`
- `src/aha/storage.py`
- `src/aha/time_ranges.py`
- `src/aha/web/app.js`
- `src/aha/web/form-controls.js`
- `src/aha/web/index.html`
- `src/aha/web/style.css`
- `src/aha/web/time-range-picker.js`

## 回归测试

- `tests/test_evidence.py`
- `tests/test_http.py`
- `tests/test_time_ranges.py`
- `tests/web_state.test.cjs`

## 用户说明与规范

- `.trellis/spec/backend/directory-structure.md`
- `.trellis/spec/backend/index.md`
- `.trellis/spec/backend/quality-guidelines.md`
- `.trellis/spec/backend/time-range-contract.md`
- `.trellis/spec/backend/usage-evidence-contract.md`
- `.trellis/spec/frontend/component-guidelines.md`
- `.trellis/spec/frontend/directory-structure.md`
- `.trellis/spec/frontend/local-web-contract.md`
- `.trellis/spec/frontend/quality-guidelines.md`
- `.trellis/spec/frontend/state-management.md`
- `.trellis/spec/guides/cross-layer-thinking-guide.md`
- `README.md`

## 任务设计、计划和验证记录

- `.trellis/tasks/10-29-form-time-filter/check.jsonl`
- `.trellis/tasks/10-29-form-time-filter/design.md`
- `.trellis/tasks/10-29-form-time-filter/implement.jsonl`
- `.trellis/tasks/10-29-form-time-filter/implement.md`
- `.trellis/tasks/10-29-form-time-filter/prd.md`
- `.trellis/tasks/10-29-form-time-filter/research/aha-form-directions.html`
- `.trellis/tasks/10-29-form-time-filter/research/check-report.md`
- `.trellis/tasks/10-29-form-time-filter/research/commit-plan.md`
- `.trellis/tasks/10-29-form-time-filter/research/compatibility-findings.md`
- `.trellis/tasks/10-29-form-time-filter/research/current-state.md`
- `.trellis/tasks/10-29-form-time-filter/research/time-performance.md`
- `.trellis/tasks/10-29-form-time-filter/research/verification.md`
- `.trellis/tasks/10-29-form-time-filter/task.json`

## 工作树归属与提交之后

未发现不属于本任务的未识别改动。运行时、合成库、截图、下载包、构建物与凭证全部位于Git忽略或仓库外目录，不进入此提交。

按已确认的本清单一次提交；不推送。随后按Trellis规则归档任务、记录会话，产生独立管理提交；不会发布或替换用户程序。

确认依据：`.trellis/workflow.md` Phase3.4要求先展示具体计划并取得一次确认。现有“进入实施”授权已用于完成全部产品和验证工作；用户现已明确确认这份具体Git提交计划及归档，不再重复询问。

工作提交已完成：`8848629`，与确认的41文件清单一致。归档与会话记录由后续Trellis管理提交维护；未推送。
