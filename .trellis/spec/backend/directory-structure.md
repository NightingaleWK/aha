# 目录与模块职责

## 适用范围

增加或调整 Python 模块前先确认本页；业务边界以 [用量证据契约](./usage-evidence-contract.md) 为准。项目使用 `src` 布局，包入口是 `aha`，见 [pyproject.toml](../../../pyproject.toml)。

## 实际布局

| 路径 | 职责 |
| --- | --- |
| `src/aha/__init__.py`、`__main__.py` | 版本、CLI、默认资料目录、浏览器启动、runtime 描述符和退出清理 |
| `domain.py` | 允许字段、数值/日期、记录身份、内容指纹和 AppError |
| `sources.py`、`sql_dump.py` | CCS SQLite 只读快照、SQL 字面量子集解析 |
| `session_meta.py` | 有界读取普通/zstd 会话头与目录依据，不读取聊天正文 |
| `projects.py` | 路径规范化、项目配置、目录规则和人工归属 |
| `analysis.py`、`claims.py` | 唯一核算流程、用量身份与覆盖/冲突评估 |
| `storage.py` | Store 门面、应用库连接/事务、不可变文件写入、备份 |
| `archive.py` | 留存投影、内容对象、capture 与来源观察 |
| `batches.py`、`migrations.py` | 报销版本/占用/状态/幂等，以及 schema 初始化/升级 |
| `evidence.py` | 冻结 CSV、HTML、manifest 和 ZIP |
| `server.py`、`web/` | 本机 HTTP、认证/请求校验，以及内置页面资源 |
| `tests/` | unittest、合成来源与隔离持久化/HTTP/进程场景 |
| `scripts/` | Windows 构建、许可证采集和启动入口 |

除 `web/`、`tests/` 和 `scripts/` 外，表中未展开的 Python 文件均位于 `src/aha/`。应用数据在运行时指定的资料目录，不放入包目录。

## 扩展方式与实例

[storage.py](../../../src/aha/storage.py) 的 Store 是对外持久化入口，相关领域模块由门面局部导入，避免互相持有第二份应用连接。真实片段：

```python
def config(self) -> dict[str, Any]:
    from .projects import configuration

    return configuration(self)
```

新增归属逻辑先检查 [projects.py](../../../src/aha/projects.py)，核算检查 [analysis.py](../../../src/aha/analysis.py)，独占检查 [claims.py](../../../src/aha/claims.py)。前端/路由调用现有 Store 方法，领域实现按现有模块职责使用事务，不在路由另建一套账本。

## 常见错误与验证

- 将 sources 的只读连接用于应用写入，或在 HTTP 中直接拼持久化 SQL，会绕过事务和门面。
- 把费用求和复制到页面或 evidence，会使预览与原包产生两套口径；复用 analysis。
- 将 `archive.py` 留存与 Trellis 任务归档混淆，或将个人数据放进源码，会破坏所有权边界。

修改模块职责后检查导入依赖和调用方，再运行 [质量要求](./quality-guidelines.md)。可参考 [test_storage.py](../../../tests/test_storage.py) 的留存/重启场景、[test_batches.py](../../../tests/test_batches.py) 的门面调用。
