# 运行输出与操作历史

## 当前输出方式

本项目没有集中 logger 或滚动日志文件。当前实现是私有启动信息、安全 HTTP 错误，以及应用库内的业务历史，不能按模板假设已有 debug/info/warn 日志等级框架。

[__main__.py](../../../src/aha/__main__.py) 有控制台时输出 `AHA_URL=<本次启动地址>`，其中包含 bootstrap 凭证；无控制台时可通过资料目录的 `runtime.json` 定位启动。该文件记录 PID、run_id、bootstrap_url，只删除属于当前 run 的描述符。浏览器自动打开失败时输出一条无敏感细节的中文提示。

这类启动信息是本机私有入口，不得粘贴进公开日志、任务验收正文或分享包。记录启动/退出结果时只记录是否可访问、是否清理、端口是否关闭，不记录真实 token、Cookie 或 CSRF。

## 默认 HTTP 日志关闭

[server.py](../../../src/aha/server.py) 的实际实现：

```python
def log_message(self, format: str, *args: Any) -> None:
    return
```

`LocalHTTPServer.handle_error` 也不调用默认 traceback 输出，避免暴露请求、路径和凭证。公开错误通过 `AppError` 的安全 JSON 返回；不要重新打开原始请求体、URL 查询串或异常栈的默认打印。错误处理见 [错误规范](./error-handling.md)。

## 应用库内操作历史

[storage.py](../../../src/aha/storage.py) 定义 `status_events`；[migrations.py](../../../src/aha/migrations.py) 定义 `claim_events` 及禁止修改/删除 claim 事件的触发器。后者记录 batch/version、action/reason、时间、版本和状态变化，写入由 [batches.py](../../../src/aha/batches.py) 的 `record_event` 和事务内生命周期操作管理。

- 历史记录与有效版本、占用、幂等必须在同一事务中提交。
- `status_events` 和 `claim_events` 用于保留业务操作历史；当前有效状态还由 revisions/batch_control 等表管理，不是仅靠事件回放推导。
- 用户填写的原因保存在本地资料库，分享材料使用 evidence 的允许投影；不能把整份本地事件表当作公开导出。
- 一般状态变化、撤回和下载不释放占用；日志里的“成功”也不能代替原包/占用/状态断言。

## 常见错误与验证

不要打印 SQL/来源路径/聊天正文/账号配置/IP/完整目录规则，不要将 `runtime.json` 加入证据包，不要为了说明操作成功而覆盖原事件。若未来确需持久运行日志，应单独确定字段和保留策略，不在现有任务内假设已经存在。

检查 [test_http.py](../../../tests/test_http.py) 的认证/输出边界、[test_http_cli.py](../../../tests/test_http_cli.py) 的私有描述符清理，以及 [test_batches.py](../../../tests/test_batches.py)、[test_migrations.py](../../../tests/test_migrations.py) 的历史保留和生命周期结果。记录运行验收时，区分新实测与归档结果。
