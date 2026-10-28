# 错误处理

## 公开错误形状

[domain.py](../../../src/aha/domain.py) 的 `AppError(code, message, status=400)` 是可向用户展示的错误。`code` 供调用方处理，`message` 给出可操作的中文说明，`status` 由 HTTP 边界使用。公开消息不得包含源 SQL、绝对源路径、凭证、正文或 traceback。

[server.py](../../../src/aha/server.py) 的 `RequestHandler._error` 将其变为实际响应：

```python
self._json(error.status, {"code": error.code, "message": error.message})
```

不要将 `str(exc)` 拼入响应。错误码、状态与 UI 行为的对应关系以 [后端契约](./usage-evidence-contract.md) 和 [前端契约](../frontend/local-web-contract.md) 为准。

## 错误在所属边界转换

- 来源读取在 sources/sql_dump 将 IO、编码或 SQLite 失败转为安全的来源错误；已有 AppError 原样抛出。
- `Store._transaction` 对所有异常执行回滚；SQLite locked/busy 转 `store_busy`（409），其他 SQLite 写错误转 `storage_write_failed`（500）。不能捕获后继续提交。
- 缺少/损坏的 capture 或 ZIP 拒绝读取，提示保留现场；不重建历史材料来掩盖损坏。
- HTTP 顶层对断管、连接重置和超时结束响应；意外异常仅返回 `internal_error` 的通用消息。默认服务器 traceback 输出关闭，见 [输出与历史](./logging-guidelines.md)。
- CLI 在启动失败时使用 `startup_error`；Windows 无 stderr 时通过本机消息框提示。启动描述符写入失败会关闭已创建的服务和 Store。

真实来源转换片段，见 [sources.py](../../../src/aha/sources.py)：

```python
except AppError:
    raise
except (OSError, ValueError, sqlite3.Error) as exc:
    raise AppError(
        "source_unavailable", "无法完成数据库只读快照；请稍后重试或主动选择 SQL 备份。"
    ) from exc
```

## 失效与冲突

409 表示需要刷新、重选或人工消解，不代表应自动覆盖。保存不能静默缩小用量或修改用户金额；修订不能在失效后借用新建分析；旧请求重放也不能复活被作废的记录。页面依据稳定错误码清理相关预览，而不是匹配中文措辞。

输入格式错误通常为 400；认证 401、来源/CSRF 403、找不到对象 404、超限 413、Content-Type 415 按当前边界返回。不要把所有失败统一成 500。

## 常见错误与检查

禁止裸 `except: pass` 把业务失败记成成功、将损坏读取替换为空结果、在失败事务外继续写入。清理临时文件和断开连接的受控忽略必须保留现有局部范围。

参考 [test_sources.py](../../../tests/test_sources.py) 的来源拒绝、[test_claim_concurrency.py](../../../tests/test_claim_concurrency.py) 的提交失败、[test_http.py](../../../tests/test_http.py) 的边界与过期预览、[test_http_cli.py](../../../tests/test_http_cli.py) 的启动失败清理。测试应断言稳定错误码/状态和原资料保留，避免只断言抛出任意异常。
