# 本地提交计划

状态：成品已交付；用户已于2026-10-27确认“提交、归档、合并到main，然后再提交”，并明确确认“推送 main 到 GitHub”，当前版本进入试用。本计划涉及本任务已有改动；归档后合并本地main，再记录日志提交并推送。

## 1. 实现用量独占与报销记录管理

一个贯通功能提交，包含占用/版本/迁移、核算与API、界面排版文案、证据包、测试、规范及任务验收资料。文件清单：

- `.trellis/spec/backend/usage-evidence-contract.md`
- `.trellis/spec/frontend/local-web-contract.md`
- `.trellis/tasks/10-27-usage-exclusive-claims/check.jsonl`
- `.trellis/tasks/10-27-usage-exclusive-claims/commit-plan.md`
- `.trellis/tasks/10-27-usage-exclusive-claims/design.md`
- `.trellis/tasks/10-27-usage-exclusive-claims/implement.jsonl`
- `.trellis/tasks/10-27-usage-exclusive-claims/implement.md`
- `.trellis/tasks/10-27-usage-exclusive-claims/prd.md`
- `.trellis/tasks/10-27-usage-exclusive-claims/research/http-analysis-api.md`
- `.trellis/tasks/10-27-usage-exclusive-claims/research/implementation-api.md`
- `.trellis/tasks/10-27-usage-exclusive-claims/research/storage-feasibility.md`
- `.trellis/tasks/10-27-usage-exclusive-claims/research/typography-copy-audit.md`
- `.trellis/tasks/10-27-usage-exclusive-claims/research/ux-lifecycle.md`
- `.trellis/tasks/10-27-usage-exclusive-claims/task.json`
- `.trellis/tasks/10-27-usage-exclusive-claims/verification.md`
- `README.md`
- `pyproject.toml`
- `src/aha/__init__.py`
- `src/aha/analysis.py`
- `src/aha/batches.py`
- `src/aha/claims.py`
- `src/aha/evidence.py`
- `src/aha/migrations.py`
- `src/aha/server.py`
- `src/aha/storage.py`
- `src/aha/web/app.js`
- `src/aha/web/index.html`
- `src/aha/web/style.css`
- `tests/migration_fixtures.py`
- `tests/test_analysis.py`
- `tests/test_batches.py`
- `tests/test_claim_concurrency.py`
- `tests/test_claims.py`
- `tests/test_evidence.py`
- `tests/test_http.py`
- `tests/test_migrations.py`
- `tests/test_storage_helpers.py`

## 2. chore(task): archive 10-27-usage-exclusive-claims

功能提交成功后，使用Trellis脚本将本任务目录移入`.trellis/tasks/archive/2026-10/`并记录完成。不归档其他任务。

## 3. chore: record journal

使用Trellis脚本更新当前开发者的`.trellis/workspace/`日志，关联第1项功能提交和实际交付验收。

## 未识别的工作区改动

无。当前脏文件均来自本任务主会话和实现/检查代理。个人SQL、QA数据、证据ZIP及EXE留在仓库外。

## 执行约束

用户已确认，依次执行功能提交、归档、本地main合并、日志提交，最后将main正常推送到origin；不amend、不强制推送。确认依据为`.trellis/workflow.md`Phase3.4第5步及用户随后明确的远端推送授权。

## 执行记录

功能提交已完成：`1174db5`（实现用量独占与报销记录管理）。后续归档、main合并和日志以Git历史及开发日志为准。
