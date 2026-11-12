# 提交与收尾清单（用户已确认）

## 1. 工作提交

`feat: 完善换机接续与完整备份还原`

这一批共同完成CCS25兼容、来源保护和去重、历史目录/预览、完整备份还原、相应测试和Windows验收器、用户说明及恢复合同。所有路径均为本会话及本任务代理修改，初始工作区干净；未识别变更：无。

精确文件清单：

- `.release/changes/ccs25-compatibility.json`
- `.release/changes/device-data-continuity.json`
- `.release/changes/full-backup-restore.json`
- `.trellis/spec/backend/ccs-source-compatibility.md`
- `.trellis/spec/backend/database-guidelines.md`
- `.trellis/spec/backend/directory-structure.md`
- `.trellis/spec/backend/index.md`
- `.trellis/spec/backend/recovery-and-device-contract.md`
- `.trellis/spec/backend/usage-evidence-contract.md`
- `.trellis/spec/frontend/local-web-contract.md`
- `.trellis/spec/frontend/state-management.md`
- `README.md`
- `scripts/verify_windows_artifact.py`
- `src/aha/__main__.py`
- `src/aha/backup.py`
- `src/aha/domain.py`
- `src/aha/ledger.py`
- `src/aha/server.py`
- `src/aha/source_bindings.py`
- `src/aha/storage.py`
- `src/aha/sync.py`
- `src/aha/web/app.js`
- `src/aha/web/index.html`
- `src/aha/web/style.css`
- `tests/test_backup.py`
- `tests/test_backup_cli.py`
- `tests/test_batches.py`
- `tests/test_device_continuity.py`
- `tests/test_evidence.py`
- `tests/test_http.py`
- `tests/test_http_backup.py`
- `tests/test_sources.py`
- `tests/test_storage.py`
- `tests/test_sync_timeout.py`
- `tests/test_windows_artifact_transfers.py`
- `tests/web_state.test.cjs`

## 2. 后续任务与会话记录

工作提交成功后，以Trellis标准脚本先归档`11-12-full-backup-restore`、`11-12-ccs25-device-recovery`和父任务`11-12-device-data-continuity`，再记录本次journal。`.trellis/tasks/`下上述任务的PRD、设计、上下文、研究与验收记录由归档提交保留；`.trellis/workspace/`只包含本次journal的脚本更新。

工作提交→任务归档提交→journal提交；不amend，不推送，不创建或合并远端PR，不公开Release。现有Desktop/D程序及真实台账接续已完成，确认提交不会再次执行导入。

## 3. 发版评估（另需记录用户选择）

最近公开版本v0.4.1；之后main没有其他未发用户功能。本次累计3条片段：完整台账备份与安全新目录还原、新电脑保留历史并接续、CCS25兼容。建议v0.5.0，补齐条件后尽快发布；已生成中文What's New预览。

推荐“先补齐发版条件”：云端固定3.15.2配方与本地3.12.16实际验收运行时对齐，随后执行对应云端候选门禁，并补物理托盘点击验收。也可选“积累到下一版”或“本次无需单独发版”；本次具有用户变化，后两项均保留待发片段。没有选择或授权时保持未发布。

确认工作提交与归档不会自动授权推送、合并发布PR或公开Release。

## 用户最终选择与执行

用户明确选择“按清单本地提交并归档”和“积累到下一版”。36文件工作提交已完成：`c7c6acc87531df6ebb8ed5bc346a624490e8ac0a`；成品与提交源码指纹一致。随后按本清单归档三个任务并记录会话；保留待发片段，不推送或公开发布。
