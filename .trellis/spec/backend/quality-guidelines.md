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

Windows 的临时目录可能含 `RUNNER~1` 等8.3短名，而恢复接口及后续启动参数按 `Path.resolve()` 返回规范路径。测试仍用原始目录发出请求，以覆盖短名输入；恢复完成后用 `target.resolve(strict=True)` 严格比较结果和 `--data-dir` 参数，保留目标存在、事实与原包SHA等断言。不能用未规范化字符串相等误判同一目录，也不能只改成包含末级文件名来放宽身份检查。

## 按修改选择验证

| 范围 | 测试与断言 |
| --- | --- |
| 来源/SQL/金额/元数据 | test_sources、test_session_meta；WAL/DELETE、busy、读取边界、取消、SQL不可执行、精确历史金额 |
| 台账/修订/覆盖/核对 | test_storage、test_storage_helpers；重复导入、改价、备份冲突、重建别名、needs_review、源清理后本地保留 |
| 本地查询/归属 | test_analysis、test_time_ranges、test_projects；秒/分钟/日/月分段、一次取钟、部分汇总A政策、游标与revision绑定、聚合精确、未归属、目录最长匹配、人工覆盖 |
| 占用/报销 | test_claims、test_batches、test_claim_concurrency；跨连接/进程竞争、冻结成员、换版回滚、别名修订、防重复报销、原包SHA |
| 新库/重建 | test_migrations、test_rebuild_trial_data；拒绝旧库、保全/回滚、受保护源与未知文件阻断、历史精确提取 |
| 材料 | test_evidence、test_time_ranges；全范围流式输出、BOM、公式/HTML保护、manifest4与独立旧manifest3兼容、冻结不漂移、隐私、空/零/非法金额 |
| 运行/HTTP | test_instance、test_http、test_http_cli、test_tray_windows；跨进程运行权、启动同步去重、job真实终态、Cookie/Origin/CSRF、旧预览409、请求/同步清理、退出重启和原生托盘 |

失败测试必须检查持久状态、旧成功时间和文件，不能只看返回值。并发不能只用一个线程内的锁代替独立连接/进程。复用合成夹具，资源显式关闭，私有源/包/截图留 Git 外。

## 规模与 Windows 门禁

性能用 [benchmark_ledger.py](../../../scripts/benchmark_ledger.py) 的固定seed百万/千万样本，记录机器、物理存储、预热/样本、P95、进程冷启动定义、RSS、固定来源窗口和真实导出校验。fast-seed仅用于建夹具，恢复生产索引/参数并抽样全projection验证后再查询；不能将 tmpfs预跑当物理盘结果，不能清全机缓存模拟冷启动。

Windows每版先验证Directory的真实EXE、HTTP/页面资源、业务材料和退出，再构建并独立验证OneFile；`--directory-verified` 不能代替已执行的目录包验证。按用户确认的 [发布合同](./release-contract.md)，首次发布完成本机全面验收，以后每版自动检查，涉及托盘、Excel、打印的改动追加相应本机专项，构建运行时或配方改变时重新全面验收。回执与实际相关指纹绑定，失效或未执行的专项不得放行。重建、成品、正式发布和真实报销各自留证；业务断言见 [主契约](./usage-evidence-contract.md)。

## 交付与临时文件收尾

按 [成品交付与清理](./delivery-and-cleanup.md) 核对：本机功能实施默认包含与最终源码一致的桌面 OneFile，实际交付文件的 SHA 与原生启动验证通过后才完成交付。提交/归档不能代替这一步；用户明确限定交付范围时遵守其限制。

验证结束后主动清理有明确归属且不再使用的合成大库、额外任务环境、中间物与缓存，保留真实资料、主环境、必要报告和成品。核对清理前后 Git 状态与成品 SHA，避免留下数 GB 临时文件或误删用户资料。
