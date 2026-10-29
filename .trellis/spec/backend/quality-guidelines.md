# 后端质量要求

## 环境与检查

[pyproject.toml](../../../pyproject.toml) 定义 Python3.12+、Ruff E/F/I/UP 与100字符行宽、mypy strict。复用 domain 校验和精确十进制聚合，不用 cast/ignore 掩盖边界。使用任务隔离环境和资料目录，不修改系统或工具 bundled 依赖。

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m ruff check src tests scripts
.venv/bin/python -m mypy src/aha
.venv/bin/python -m compileall -q src/aha
node --check src/aha/web/app.js
```

SQLite 必须通过 [运行时门禁](./database-guidelines.md)；版本不满足时在任务环境准备修复版本，不全局替换库。Windows 使用 Scripts/python.exe；Node UNC 检查方式见 [前端质量](../frontend/quality-guidelines.md)。

Linux 与 Windows 并行运行 mypy 时使用各自的 `--cache-dir`，避免共用仓库缓存。平台限定的标准库属性使用可被类型检查识别的 `sys.platform` 分支；运行时 `os.name` 判断未必能让 Windows 类型检查排除 Unix 属性。

## 按修改选择验证

| 范围 | 测试与断言 |
| --- | --- |
| 来源/SQL/金额/元数据 | test_sources、test_session_meta；WAL/DELETE、busy、读取边界、取消、SQL不可执行、精确历史金额 |
| 台账/修订/覆盖/核对 | test_storage、test_storage_helpers；重复导入、改价、备份冲突、重建别名、needs_review、源清理后本地保留 |
| 本地查询/归属 | test_analysis、test_projects；游标与revision绑定、聚合精确、未归属、目录最长匹配、人工覆盖 |
| 占用/报销 | test_claims、test_batches、test_claim_concurrency；跨连接/进程竞争、冻结成员、换版回滚、别名修订、防重复报销、原包SHA |
| 新库/重建 | test_migrations、test_rebuild_trial_data；拒绝旧库、保全/回滚、受保护源与未知文件阻断、历史精确提取 |
| 材料 | test_evidence；全范围流式输出、BOM、公式/HTML保护、manifest3、隐私、空/零/非法金额 |
| 运行/HTTP | test_instance、test_http、test_http_cli、test_tray_windows；跨进程运行权、启动同步去重、job真实终态、Cookie/Origin/CSRF、旧预览409、请求/同步清理、退出重启和原生托盘 |

失败测试必须检查持久状态、旧成功时间和文件，不能只看返回值。并发不能只用一个线程内的锁代替独立连接/进程。复用合成夹具，资源显式关闭，私有源/包/截图留 Git 外。

## 规模与 Windows 门禁

性能用 [benchmark_ledger.py](../../../scripts/benchmark_ledger.py) 的固定seed百万/千万样本，记录机器、物理存储、预热/样本、P95、进程冷启动定义、RSS、固定来源窗口和真实导出校验。fast-seed仅用于建夹具，恢复生产索引/参数并抽样全projection验证后再查询；不能将 tmpfs预跑当物理盘结果，不能清全机缓存模拟冷启动。

Windows先目录包真实EXE/浏览器、CSV Excel、HTML A4打印，再构建并验收OneFile。脚本的 --directory-verified 不能代替已执行的目录包验证。重建演练、成品验收、实际试用清理和正式报销各自记录，不把一种证据冒充另一种。完整断言见 [主契约](./usage-evidence-contract.md)。
