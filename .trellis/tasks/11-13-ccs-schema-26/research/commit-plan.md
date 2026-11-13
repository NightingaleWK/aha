# 一次性本地提交确认

本机成品交付和清理已经完成。以下仅提交本任务改动，不推送远端；确认后按顺序执行，再归档任务并记录日志。

## 1. `fix: 支持 CC Switch 26 用量同步`

- `src/aha/domain.py`
- `tests/test_sources.py`
- `tests/test_storage.py`
- `tests/test_http.py`
- `tests/test_evidence.py`
- `scripts/verify_windows_artifact.py`
- `.release/changes/ccs26-compatibility.json`
- `README.md`
- `.trellis/spec/backend/ccs-source-compatibility.md`
- `.trellis/spec/backend/database-guidelines.md`
- `.trellis/spec/backend/usage-evidence-contract.md`
- `.trellis/spec/backend/index.md`

## 2. `chore: 记录 CCS 26 本机验收与交付`

- `.trellis/tasks/11-13-ccs-schema-26/` 下的任务、计划、研究、完整原始日志和必要小型验收证据。
- `.release/acceptance/ccs26-materials.json`：由已准备的 `local-acceptance.json`机械绑定第1个提交SHA，保留当次实际指纹、运行时及证据，不引入新的“通过”声明。

随后由Trellis分别生成任务归档和会话日志记账提交。已有公开片段、产品版本和用户资料不改动。

## 未识别的脏文件

无。会话开始只有本任务规划目录未跟踪；当前全部改动均属本次AI实施/验证。

## 确认状态

用户于2026-11-13确认“按清单提交并归档（推荐）”，授权按上述两组提交、归档及记录日志。工作流依据：`.trellis/workflow.md`第3.4步。

同轮用户选择“先补齐发版条件（推荐）”，另行授权在本地收尾后创建修复PR、运行CI并准备0.5.1候选；公开发布仍未获授权。
