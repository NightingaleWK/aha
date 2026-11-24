# 提交方案

## 工作提交

`feat!: 改用 Windows 与 WSL 原生 Codex 用量采集`

以同一提交落地采集、台账迁移、CCS 读取退役、回归和使用说明。文件如下。

- `.release/changes/codex-dual-source-usage.json`
- `.release/changes/retire-ccs-readers.json`
- `.trellis/spec/backend/ccs-source-compatibility.md`
- `.trellis/spec/backend/codex-native-source-contract.md`
- `.trellis/spec/backend/database-guidelines.md`
- `.trellis/spec/backend/directory-structure.md`
- `.trellis/spec/backend/index.md`
- `.trellis/spec/backend/project-association-contract.md`
- `.trellis/spec/backend/quality-guidelines.md`
- `.trellis/spec/backend/recovery-and-device-contract.md`
- `.trellis/spec/backend/runtime-lifecycle-contract.md`
- `.trellis/spec/backend/time-range-contract.md`
- `.trellis/spec/backend/usage-evidence-contract.md`
- `.trellis/spec/frontend/local-web-contract.md`
- `.trellis/spec/frontend/state-management.md`
- `.trellis/spec/guides/cross-layer-thinking-guide.md`
- `README.md`
- `scripts/rebuild_trial_data.py`
- `scripts/release.py`
- `scripts/verify_windows_artifact.py`
- `src/aha/__main__.py`
- `src/aha/backup.py`
- `src/aha/batches.py`
- `src/aha/claims.py`
- `src/aha/codex_sessions.py`
- `src/aha/codex_source_io.py`
- `src/aha/domain.py`
- `src/aha/evidence.py`
- `src/aha/ledger.py`
- `src/aha/migrations.py`
- `src/aha/native_sync.py`
- `src/aha/queries.py`
- `src/aha/server.py`
- `src/aha/session_meta.py`
- `src/aha/source_bindings.py`
- `src/aha/sources.py`
- `src/aha/sql_dump.py`
- `src/aha/storage.py`
- `src/aha/sync.py`
- `src/aha/web/app.js`
- `src/aha/web/index.html`
- `src/aha/web/style.css`
- `tests/native_usage_fixtures.py`
- `tests/test_assignment_migration.py`
- `tests/test_codex_sessions.py`
- `tests/test_device_continuity.py`
- `tests/test_http.py`
- `tests/test_http_backup.py`
- `tests/test_instance.py`
- `tests/test_native_sync.py`
- `tests/test_sources.py`
- `tests/test_storage.py`
- `tests/test_sync_timeout.py`
- `tests/test_windows_artifact.py`
- `tests/web_state.test.cjs`

## 任务记录

工作提交确认后按现有完工流程分别归档双端采集、历史迁移及主任务，再记录开发日志。
发版单独依据已审阅的版本和验收回执执行。
