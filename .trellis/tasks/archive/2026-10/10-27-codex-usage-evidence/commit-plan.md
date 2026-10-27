# 本地提交计划

成品与技术验证已完成。用户已于 2026-10-27 回复“ok”，批准按本计划执行本地提交与后续归档、日志。

## 按顺序执行

1. 工作提交：`实现 Codex 用量证据导出工具`。包含独立工具源码、测试、构建/许可证脚本、README、忽略规则、实际规范及本任务规划与验证记录。

具体文件：

- `.gitignore`
- `.trellis/spec/backend/index.md`
- `.trellis/spec/backend/usage-evidence-contract.md`
- `.trellis/spec/frontend/index.md`
- `.trellis/spec/frontend/local-web-contract.md`
- `.trellis/tasks/10-27-codex-usage-evidence/check.jsonl`
- `.trellis/tasks/10-27-codex-usage-evidence/commit-plan.md`
- `.trellis/tasks/10-27-codex-usage-evidence/design.md`
- `.trellis/tasks/10-27-codex-usage-evidence/implement.jsonl`
- `.trellis/tasks/10-27-codex-usage-evidence/implement.md`
- `.trellis/tasks/10-27-codex-usage-evidence/prd.md`
- `.trellis/tasks/10-27-codex-usage-evidence/research/implementation-api.md`
- `.trellis/tasks/10-27-codex-usage-evidence/research/optimization-options.md`
- `.trellis/tasks/10-27-codex-usage-evidence/research/project-identification.md`
- `.trellis/tasks/10-27-codex-usage-evidence/research/retention-batch-contract.md`
- `.trellis/tasks/10-27-codex-usage-evidence/research/runtime-and-delivery.md`
- `.trellis/tasks/10-27-codex-usage-evidence/research/source-findings.md`
- `.trellis/tasks/10-27-codex-usage-evidence/task.json`
- `.trellis/tasks/10-27-codex-usage-evidence/verification.md`
- `README.md`
- `pyproject.toml`
- `requirements-dev.txt`
- `scripts/build_windows.ps1`
- `scripts/build_windows.py`
- `scripts/collect_licenses.py`
- `scripts/launch.py`
- `scripts/licenses/zstd-1.5.7-LICENSE.txt`
- `scripts/requirements-build.txt`
- `src/aha/__init__.py`
- `src/aha/__main__.py`
- `src/aha/analysis.py`
- `src/aha/archive.py`
- `src/aha/batches.py`
- `src/aha/domain.py`
- `src/aha/evidence.py`
- `src/aha/projects.py`
- `src/aha/server.py`
- `src/aha/session_meta.py`
- `src/aha/sources.py`
- `src/aha/sql_dump.py`
- `src/aha/storage.py`
- `src/aha/web/app.js`
- `src/aha/web/index.html`
- `src/aha/web/mark.svg`
- `src/aha/web/style.css`
- `tests/test_analysis.py`
- `tests/test_batches.py`
- `tests/test_evidence.py`
- `tests/test_http.py`
- `tests/test_http_cli.py`
- `tests/test_projects.py`
- `tests/test_session_meta.py`
- `tests/test_sources.py`
- `tests/test_storage.py`
- `tests/test_storage_helpers.py`

## 后续收尾

工作提交成功后，仅归档当前 `codex-usage-evidence` 任务并记录本次日志，由 Trellis 生成对应的归档、日志提交。保留 `00-bootstrap-guidelines` 初始化任务状态。

未识别改动：无。个人原始数据、QA 资料、虚拟环境、Windows 构建目录和 EXE 均不进入 Git。只做本地提交，不推送。

本计划的一次性确认已取得，具体提交标识见 Git 历史和会话日志。
