# 原生EXE自动验收脚本扩展

日期：2026-11-12。仅修改`scripts/verify_windows_artifact.py`并增加`tests/test_windows_artifact_transfers.py`，没有修改备份核心、产品模块或真实资料，也没有等待或冒称已运行尚未交付的EXE。

## 实际新增的执行链

- 原生EXE在独占合成Windows profile启动，先读CCS23，再24、25；各版本准确传递且相同事实不增不改。
- SQL25实际导入；SQLite26与SQL26分别失败，明确unsupported_schema和实际26；全局数量/最近成功时间不变，旧历史仍可查询；每次失败后恢复SQLite25并实际成功同步。
- 新分析和材料明确内部投影23/normalized_usage_projection，不把CCS25当内部协议。
- 保存3条合成用量的报销，下载并校验四文件原材料。
- 实际调用HTTP备份job，轮询其自身ID至completed，下载.aha-backup并核对长度/SHA，检查DB/manifest存在且没有runtime/运行锁/temporary。
- 建立二进制上传会话，按服务端<=4MiB限额上传；小包也拆为至少两块，实际覆盖非零offset和精确received进度。完整恢复到合成原库之外的新目录。
- 独立原生SQLite只读比较原库/恢复库事实、版本、项目、报销、冻结成员数量与claim身份；不仅比较汇总。
- 启动恢复目录同一EXE：确认required绑定；绑定前历史可查、旧报销原包SHA一致，startup同步被source_binding_required阻断且事实/占用不变；明确确认来源后两次CCS25同步均unchanged，原包/claims保持不变；正常退出、端口与descriptor清理。
- 原资料进程继续保持原事实/占用；再验同目录重开、完整重启、原包SHA和退出。

## 回执范围

scope按实际完整成功链新增ccs-23-24-25/sql-25/unsupported-26-history-preserved/usage-projection-23/full-backup-download/chunked-backup-upload/new-directory-restore/restored-source-rebinding/restored-repeat-sync-idempotence；整链任何失败不返回verified=true。

`complete_backup`记录实际备份SHA/大小、3条事实与3个有效claims、恢复来源已确认及原包SHA。合成验收目录保留`material`四文件/原ZIP、`complete.aha-backup`和`restored-store`，供父会话继续浏览器、Excel和打印专项；当前脚本不宣称物理托盘/Office/浏览器操作已通过。

## 当前已执行检查

环境：Windows任务qa312，Python3.12.16 / SQLite3.53.1，通过父任务run-native.py调用。

- `unittest discover -s tests -p 'test_windows_artifact*.py' -v`：8项通过（0.097秒），含既有环境/凭证/材料边界及新增二进制认证、错误上传进度、job身份与超时拒绝。
- Ruff脚本与新增测试：通过。
- strict mypy脚本（follow-imports=silent，专用mypy-verifier缓存）：通过。
- Windows py_compile脚本/新测试：通过。
- Git diff空白检查：通过。

最终Directory/OneFile的实际EXE验收由父会话在最终构建后运行，届时才可记录这些新scope为成品已通过。本回执仅证明验收脚本及其边界检查就绪。
