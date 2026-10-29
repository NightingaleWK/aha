# 提交计划

2026-10-29，用户明确回复“提交，合并main，归档”，批准本批次提交及本地合并、归档；不推送远端。全部路径均为本任务改动，没有未识别文件。以下清单保留提交时的原始路径。

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

代码、双平台检查、Directory/OneFile 自动流程已完成，工作提交为 `6fa4ee16658f389661e187f5f64732563331daae`。本地 `main` 已从 `01b2c1e` 快进至该提交，同时带入继承的本地用量台账三个提交；开发分支保留。

按用户本轮明确指令继续归档并记录会话。AC4 的实际鼠标展开菜单/点击仍未验收，记录保留，不把归档指令记为实际操作通过或明确豁免。
