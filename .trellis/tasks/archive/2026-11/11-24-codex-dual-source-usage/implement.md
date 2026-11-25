# aha 双端 Codex 用量采集执行计划

## 阶段 0 审阅和基线

1. 审阅主、子任务的 PRD、设计和计划。用户确认本版方案后，启动原生采集子任务。主任务负责跟踪交叉验收。
2. 从 `main` 选择实施基线，核对现有分支的独立归档与日志提交，避免混入本任务。保持现有真实台账、桌面成品和原始会话文件的回退依据。所有开发及演练初始使用隔离资料目录。
3. 把用户已跑的两端会话用作只读样本，保留脱敏的期望字段和验证记录。补构造化的会话日志、历史台账和完整备份样本，覆盖用户实际样本没有的重放、分叉、失败及冻结包。

## 阶段 1 原生采集在隔离台账通过

1. 完成[双端原生采集执行计划](../11-24-codex-native-usage/implement.md)。按 Windows、WSL 逐端验证发现、无损只读、版本识别、统计和增量。
2. 用同一批日志进行首导、重导、跨端复制、续跑和压缩迁移。检查每笔 Token 和身份，比较查到的项目与本地源目录依据。
3. 让 WSL 暂不可用再恢复。验证 Windows 能提交、WSL 进度保留、复用同一来源身份和旧业务继续查询。验收后交接原生投影、事件身份、源状态、样本和测试回执。

## 阶段 2 历史核对、备份升级与 CCS 退出

1. 按[历史台账迁移与备份还原执行计划](../11-24-codex-history-backup-cutover/implement.md)，先校验历史台账和旧备份基准。以隔离副本预演重叠、缺口、已占用成员和实际升级回退。
2. 将现有启动和手动同步切到原生读取。移除 CCS 活库、SQL、旧绑定逻辑和对应前端入口，并将验证脚本和现行说明迁移到新流程。
3. 对照旧账本和新账本，比对已发布事实、项目、认领占用、报销修订与冻结包 SHA256。用无 CCS 的环境跑旧完整备份还原、新备份往返和新源续采。

## 阶段 3 整体验收与交付

1. 在任务隔离解释器运行 Python 单测、Ruff、strict mypy 和 compileall。检查 `app.js`、`form-controls.js`、`time-range-picker.js`，运行 `node --test tests/web_state.test.cjs`。重点检查来源切换、迟到响应、键盘/焦点以及既有项目时间和保存流程。
2. 本机实际用 Windows 与 WSL 原生样本验收浏览器、同步与查询、导出、备份还原和程序退出。报销说明或格式变化时打开 Excel 与 A4 PDF。把实机 WSL 验收和自动模拟证据分别记录。
3. 用已有 `scripts/build_windows.py` 分别构建和验收 Directory、OneFile。按系统桌面位置交付与已验收 EXE 哈希一致的 `aha.exe`，从该副本以隔离资料再次验证启动、重开、同步、原包和退出。保存源码依据、运行时、哈希和各项验收结果。
4. 按交付规范核对并清理本任务自建虚拟环境、大型合成库、构建中间物和缓存。保留证据、真实资料、旧版必要回退件及最终桌面成品。
5. 编写实际改动的中文 What’s New 片段。正式发布评估按累计待发范围和实际验收做，公开发布及真实资料切换遵循已获得的用户授权。

## 检查与成品入口

在已通过 SQLite 门禁的隔离环境和各阶段独立测试目录中运行以下检查。Windows 成品动作使用原生 Windows x64 解释器，替换示例中的路径。

```text
python -m unittest discover -s tests -v
python -m ruff check src tests scripts
python -m mypy src/aha
python -m compileall -q src/aha
node --check src/aha/web/app.js
node --check src/aha/web/form-controls.js
node --check src/aha/web/time-range-picker.js
node --test tests/web_state.test.cjs
python scripts/build_windows.py --build-root <任务专用构建目录> --stage Directory
python scripts/verify_windows_artifact.py --exe <Directory版EXE> --source-root <源码目录> --data-root <隔离验收目录> --report <Directory回执>
python scripts/build_windows.py --build-root <任务专用构建目录> --stage OneFile --directory-verified
python scripts/verify_windows_artifact.py --exe <OneFile版EXE> --source-root <源码目录> --data-root <另一隔离验收目录> --report <OneFile回执>
```

Directory 只有在实际启动、业务和退出通过后才使用 `--directory-verified`。实机 WSL、桌面文件及材料额外验证按阶段 3。 [成品交付合同](../../../../spec/backend/delivery-and-cleanup.md)

## 回退点

- 阶段 1 和阶段 2 的试验只在隔离资料完成，有问题可继续使用现有产品与原台账。
- 正式升级前保有已验证的旧版完整备份，以及匹配旧库的 EXE。迁移失败原库可用。需要回退时用升级前的备份在独立目录还原并用旧 EXE 打开。
- 若已经在新版本产生可用量、归属或报销更新，回退前先另存新版完整备份，明确两份台账覆盖范围。用两个独立目录防止混用，同一期业务只以已选择的台账处理。
