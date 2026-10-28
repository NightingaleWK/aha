# 本地提交计划

状态：用户已于2026-10-28明确同意本地提交并归档；按以下已确认清单执行，不推送。

1. `feat: 建立 Codex 本地用量台账`

   将相互依赖的新schema、只读同步、本地查询、精确统计、冻结报销、界面、受控重建工具及相关测试/规范/验收证据作为一个完整工作提交。最终产品源码指纹950、150项双平台完整检查通过；不再运行大规模测试。

文件清单（95项，含本计划；删除文件按删除提交）：

- `.trellis/spec/backend/database-guidelines.md`
- `.trellis/spec/backend/directory-structure.md`
- `.trellis/spec/backend/error-handling.md`
- `.trellis/spec/backend/index.md`
- `.trellis/spec/backend/logging-guidelines.md`
- `.trellis/spec/backend/quality-guidelines.md`
- `.trellis/spec/backend/usage-evidence-contract.md`
- `.trellis/spec/frontend/local-web-contract.md`
- `.trellis/spec/frontend/quality-guidelines.md`
- `.trellis/spec/frontend/state-management.md`
- `.trellis/spec/frontend/type-safety.md`
- `.trellis/spec/guides/code-reuse-thinking-guide.md`
- `.trellis/spec/guides/cross-layer-thinking-guide.md`
- `.trellis/tasks/10-28-codex-local-usage-ledger/check.jsonl`
- `.trellis/tasks/10-28-codex-local-usage-ledger/design.md`
- `.trellis/tasks/10-28-codex-local-usage-ledger/implement.jsonl`
- `.trellis/tasks/10-28-codex-local-usage-ledger/implement.md`
- `.trellis/tasks/10-28-codex-local-usage-ledger/prd.md`
- `.trellis/tasks/10-28-codex-local-usage-ledger/research/acceptance/real-rebuild-and-delivery.json`
- `.trellis/tasks/10-28-codex-local-usage-ledger/research/acceptance/windows-directory-r4.json`
- `.trellis/tasks/10-28-codex-local-usage-ledger/research/acceptance/windows-onefile-1m-pre-density.json`
- `.trellis/tasks/10-28-codex-local-usage-ledger/research/acceptance/windows-onefile-r4.json`
- `.trellis/tasks/10-28-codex-local-usage-ledger/research/commit-plan.md`
- `.trellis/tasks/10-28-codex-local-usage-ledger/research/final-check.md`
- `.trellis/tasks/10-28-codex-local-usage-ledger/research/implementation-api.md`
- `.trellis/tasks/10-28-codex-local-usage-ledger/research/ledger-storage-and-query.md`
- `.trellis/tasks/10-28-codex-local-usage-ledger/research/performance/README.md`
- `.trellis/tasks/10-28-codex-local-usage-ledger/research/performance/benchmark-smoke-r4.json`
- `.trellis/tasks/10-28-codex-local-usage-ledger/research/performance/check-density-vm-final.json`
- `.trellis/tasks/10-28-codex-local-usage-ledger/research/performance/check-live-publish-explain-ro.json`
- `.trellis/tasks/10-28-codex-local-usage-ledger/research/performance/linux-10m-concurrent-load.json`
- `.trellis/tasks/10-28-codex-local-usage-ledger/research/performance/linux-10m-fixed-window-r4.json`
- `.trellis/tasks/10-28-codex-local-usage-ledger/research/performance/linux-10m-fixture-verification.json`
- `.trellis/tasks/10-28-codex-local-usage-ledger/research/performance/linux-10m-footprint.json`
- `.trellis/tasks/10-28-codex-local-usage-ledger/research/performance/linux-10m-seed-initial-failure.json`
- `.trellis/tasks/10-28-codex-local-usage-ledger/research/performance/linux-1m-sync-export.json`
- `.trellis/tasks/10-28-codex-local-usage-ledger/research/performance/linux-1m.json`
- `.trellis/tasks/10-28-codex-local-usage-ledger/research/performance/released-windows-10m-result.json`
- `.trellis/tasks/10-28-codex-local-usage-ledger/research/performance/space-guard-result.json`
- `.trellis/tasks/10-28-codex-local-usage-ledger/research/performance/windows-10m-100k-package-audit.json`
- `.trellis/tasks/10-28-codex-local-usage-ledger/research/performance/windows-10m-r4-fixture-preparation.json`
- `.trellis/tasks/10-28-codex-local-usage-ledger/research/performance/windows-10m-r4-user-stopped.json`
- `.trellis/tasks/10-28-codex-local-usage-ledger/research/performance/windows-1m-footprint.json`
- `.trellis/tasks/10-28-codex-local-usage-ledger/research/performance/windows-1m-increment-export.json`
- `.trellis/tasks/10-28-codex-local-usage-ledger/research/performance/windows-1m-unchanged-20k.json`
- `.trellis/tasks/10-28-codex-local-usage-ledger/research/performance/windows-1m.json`
- `.trellis/tasks/10-28-codex-local-usage-ledger/research/performance/windows-million-stop-by-user.json`
- `.trellis/tasks/10-28-codex-local-usage-ledger/research/source-sync-contract.md`
- `.trellis/tasks/10-28-codex-local-usage-ledger/research/ui-and-validation-contract.md`
- `.trellis/tasks/10-28-codex-local-usage-ledger/research/validation-history.md`
- `.trellis/tasks/10-28-codex-local-usage-ledger/research/validation-progress.md`
- `.trellis/tasks/10-28-codex-local-usage-ledger/task.json`
- `.trellis/tasks/10-28-codex-local-usage-ledger/verification.md`
- `README.md`
- `pyproject.toml`
- `scripts/benchmark_ledger.py`
- `scripts/build_windows.py`
- `scripts/rebuild_trial_data.py`
- `src/aha/__init__.py`
- `src/aha/__main__.py`
- `src/aha/analysis.py`
- `src/aha/archive.py`
- `src/aha/batches.py`
- `src/aha/claims.py`
- `src/aha/decimal_sql.py`
- `src/aha/domain.py`
- `src/aha/evidence.py`
- `src/aha/ledger.py`
- `src/aha/migrations.py`
- `src/aha/projects.py`
- `src/aha/queries.py`
- `src/aha/server.py`
- `src/aha/session_meta.py`
- `src/aha/sources.py`
- `src/aha/sql_dump.py`
- `src/aha/storage.py`
- `src/aha/sync.py`
- `src/aha/web/app.js`
- `src/aha/web/index.html`
- `src/aha/web/style.css`
- `tests/billing_fixtures.py`
- `tests/migration_fixtures.py`
- `tests/test_analysis.py`
- `tests/test_availability_scaling.py`
- `tests/test_batches.py`
- `tests/test_claim_concurrency.py`
- `tests/test_claims.py`
- `tests/test_evidence.py`
- `tests/test_http.py`
- `tests/test_migrations.py`
- `tests/test_projects.py`
- `tests/test_rebuild_trial_data.py`
- `tests/test_sources.py`
- `tests/test_storage.py`
- `tests/test_storage_helpers.py`

未识别改动：无。清单来自当前工作区；全部为本任务主会话及按文件所有权调度代理的工作。

工作提交完成后，仅归档当前`10-28-codex-local-usage-ledger`任务并记录中文开发日志，归档和日志由项目脚本分别产生chore提交；不推送、不amend、不改远程。旧成品及用户资料保全保持不动。

确认依据：`.trellis/workflow.md` Phase3.4要求“Present the plan once, ask for one-shot confirmation”；`.agents/skills/trellis-finish-work/SKILL.md`要求“Code commits are NOT done here”，因此先确认并完成工作提交，再归档/日志。
