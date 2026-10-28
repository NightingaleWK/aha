# 后端质量要求

## 代码与环境

配置来源是 [pyproject.toml](../../../pyproject.toml)：Python 3.12+，Ruff `E/F/I/UP`、100 字符行宽，mypy strict。当前领域数据大量使用 `dict[str, Any]`/`Row`；严格检查不等于已经存在完整 DTO 模型。复用 domain 的归一化和校验，不用随意 cast 或忽略诊断代替边界验证。

开发使用任务自有 `.venv` 与 `--data-dir`，不修改系统或工具 bundled Python 的依赖。合成夹具/临时目录用于测试；个人源库、runtime 凭证、证据包及截图保持仓库外。

## 常规检查

从仓库根在已配置的隔离环境执行：

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m ruff check src tests scripts
.venv/bin/python -m mypy src/aha
.venv/bin/python -m compileall -q src/aha
node --check src/aha/web/app.js
```

Windows 将 Python 入口换成 `.venv\Scripts\python.exe`；Node 使用可用的本地运行时。构建依赖固定在 `scripts/requirements-build.txt`，开发检查依赖固定在 `requirements-dev.txt`，运行步骤见 [README](../../../README.md)。

## 测试如何选

| 修改范围 | 至少核对的场景 |
| --- | --- |
| 来源/金额/目录依据 | `test_sources.py`、`test_session_meta.py`、`test_analysis.py`、`test_projects.py`：WAL、不可执行 SQL、精确成本、时间边界、粒度与归属 |
| 留存/SQLite/文件 | `test_storage.py`、`test_storage_helpers.py`：原子失败、缺失/损坏、重启及原件移除后独立恢复 |
| 占用/版本/升级 | `test_claims.py`、`test_batches.py`、`test_claim_concurrency.py`、`test_migrations.py`：双连接/进程竞争、失败回滚、旧 writer、原包保留 |
| 导出 | `test_evidence.py`：全成员/合计、BOM、公式/HTML 保护、manifest、隐私、空/零/非法金额 |
| 路由/运行生命周期 | `test_http.py`、`test_http_cli.py`：真实请求、CookieJar 双实例、过期主体、幂等重放、退出/重启 |

表中测试均位于 `tests/`。测试必须观察失效/错误后的数据状态，不能仅断言函数返回成功。真实例子来自 [test_batches.py](../../../tests/test_batches.py) 的有效版本测试：

```python
self.assertFalse(history["revisions"][0]["is_effective"])
self.assertTrue(history["revisions"][1]["is_effective"])
self.assertEqual(self.store.download(first["id"], 1), original)
```

创建新测试时先复用合成来源与现有夹具，显式关闭资源；并发问题不能只用一个线程内的锁替代双进程测试。可逆小文档变动检查引用与一致性即可；没有源码变化或新问题时不重复已通过的产品基线。

## Windows 发布门禁

使用真实 Windows x64 隔离环境，先目录包，实际 EXE/浏览器核对导入、项目、占用/版本、迁移副本、下载、重启和退出；CSV 在目标 Excel 打开，HTML 实际打印检查，再构建 OneFile 并验证。使用 [build_windows.py](../../../scripts/build_windows.py) 的 `--directory-verified` 前必须已有目录包验收。

构建成功、HTTP 200、Linux 测试或历史记录不能单独证明当前原生成品已验收；个人资料副本测试也不等于正式资料迁移或业务报销成功。检查断言见 [主契约第 6 部分](./usage-evidence-contract.md#6-测试要求)。
