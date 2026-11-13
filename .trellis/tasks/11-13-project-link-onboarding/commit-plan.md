# 提交计划（用户已确认）

工作提交：`feat: 按目录整体关联项目记录`

同一功能的后端、界面、测试、规范、中文变更片段及规划/验收证据作为一个工作提交：

- `src/aha/directory_bindings.py`
- `src/aha/project_links.py`
- `src/aha/projects.py`
- `src/aha/ledger.py`
- `src/aha/associations.py`
- `src/aha/storage.py`
- `src/aha/server.py`
- `src/aha/web/app.js`
- `src/aha/web/index.html`
- `src/aha/web/style.css`
- `tests/test_directory_bindings.py`
- `tests/test_http.py`
- `tests/web_state.test.cjs`
- `README.md`
- `.release/changes/project-link-onboarding.json`
- `.trellis/spec/backend/project-association-contract.md`
- `.trellis/spec/backend/database-guidelines.md`
- `.trellis/spec/backend/usage-evidence-contract.md`
- `.trellis/spec/backend/directory-structure.md`
- `.trellis/spec/frontend/local-web-contract.md`
- `.trellis/spec/frontend/state-management.md`
- `.trellis/tasks/11-13-project-link-onboarding/`

未识别的脏文件：无。会话开始时工作区干净，以上由本会话与已分工代理产生。

确认后：执行这一笔工作提交，再按Trellis流程归档当前任务并记录会话（归档/日志各自形成后续bookkeeping提交）；不推送远端、不合并PR、不公开Release。

发版建议：积累到下一版，建议候选v0.6.0；当前桌面为已验收的0.5.1本机改进构建，版本号由未来发布PR统一递增。最近公开v0.5.1至今累计用户改动仅本次目录整体关联。中文片段保留，缺口见verification.md及research/release-assessment.json。

也可以选择提交后先补齐发版条件；该选择仅授权准备/补验，不代表跳过物理托盘和云端候选门禁或自动公开。若选择自行提交，本会话不替你提交/归档，待你确认完成后接续。

用户确认：2026-11-13回复“同意提交，积累到下一版（推荐）”。
