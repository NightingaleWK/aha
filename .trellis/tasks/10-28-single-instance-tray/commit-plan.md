# 提交计划

待用户一次性确认后执行，不推送远端。全部路径均为本任务改动，没有未识别文件。

## 批次 1

`feat: 支持单实例重开与 Windows 托盘退出`

按资料目录复用、认证识别、完整退出/崩溃恢复、原生托盘/图标/打包、相关检查与运行规范，并纳入规划和验收摘要。storage.py 仅修正平台类型分支，不改持久化业务。

文件清单：

- `.trellis/spec/backend/directory-structure.md`
- `.trellis/spec/backend/index.md`
- `.trellis/spec/backend/logging-guidelines.md`
- `.trellis/spec/backend/quality-guidelines.md`
- `.trellis/spec/backend/runtime-lifecycle-contract.md`
- `.trellis/spec/backend/usage-evidence-contract.md`
- `.trellis/spec/frontend/local-web-contract.md`
- `.trellis/tasks/10-28-single-instance-tray/check.jsonl`
- `.trellis/tasks/10-28-single-instance-tray/commit-plan.md`
- `.trellis/tasks/10-28-single-instance-tray/design.md`
- `.trellis/tasks/10-28-single-instance-tray/implement.jsonl`
- `.trellis/tasks/10-28-single-instance-tray/implement.md`
- `.trellis/tasks/10-28-single-instance-tray/prd.md`
- `.trellis/tasks/10-28-single-instance-tray/research/acceptance/cleanup.json`
- `.trellis/tasks/10-28-single-instance-tray/research/acceptance/copy-alias.json`
- `.trellis/tasks/10-28-single-instance-tray/research/acceptance/directory-materials.json`
- `.trellis/tasks/10-28-single-instance-tray/research/acceptance/directory-r1.json`
- `.trellis/tasks/10-28-single-instance-tray/research/acceptance/onefile-materials.json`
- `.trellis/tasks/10-28-single-instance-tray/research/acceptance/onefile-r1.json`
- `.trellis/tasks/10-28-single-instance-tray/research/acceptance/source-files.json`
- `.trellis/tasks/10-28-single-instance-tray/research/acceptance/source-r1.json`
- `.trellis/tasks/10-28-single-instance-tray/research/final-check.md`
- `.trellis/tasks/10-28-single-instance-tray/research/runtime-lifecycle.md`
- `.trellis/tasks/10-28-single-instance-tray/task.json`
- `.trellis/tasks/10-28-single-instance-tray/verification.md`
- `README.md`
- `pyproject.toml`
- `scripts/build_windows.ps1`
- `scripts/build_windows.py`
- `src/aha/__main__.py`
- `src/aha/instance.py`
- `src/aha/runtime.py`
- `src/aha/server.py`
- `src/aha/storage.py`
- `src/aha/tray_windows.py`
- `src/aha/web/app.js`
- `src/aha/web/mark.ico`
- `tests/test_http_cli.py`
- `tests/test_instance.py`
- `tests/test_tray_windows.py`

## 状态与后续

代码、双平台检查、Directory/OneFile 自动流程已完成；尚未暂存或提交。AC4 的实际鼠标操作未覆盖，用户尚未豁免；即使本批次获准提交，也保留该待验收项，不自动宣称任务全部完成或归档。验收记录补齐后再按 Trellis 收尾。
