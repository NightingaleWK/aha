# 运行输出与操作历史

## 私有启动信息

程序未引入滚动日志框架。有控制台时 __main__ 输出 AHA_URL，无控制台时读取资料目录 runtime.json 的 PID/run_id/bootstrap_url；只删除属于当前启动的描述符。这些是私有凭证，验收只记录可访问、端口关闭与描述符清理，不记录真实token/Cookie/CSRF。

## HTTP与同步错误

RequestHandler.log_message 和 LocalHTTPServer.handle_error 关闭原始访问/traceback输出。AppError仅给出安全code/message；不打印SQL、来源路径、聊天正文、账户配置或请求体。sync_runs 保存安全运行状态、计数与错误，未核实的来源变化不能记成成功。

## 库内事件

batches.py 的 batch_events 与 ledger.py 的 reconciliation_events 记录原因、主体、时间和结果。批次事件与有效版、占用、幂等、统计一起提交；当前状态仍由业务表管理，不声称仅靠事件回放。

事件只写本地，分享包使用 evidence 的允许投影，不导出整份事件表、目录规则或源配置。同步无变化时不为每条事实追加重复观察，避免运行频率使本地资料成倍膨胀。

## 验证

test_http/test_http_cli 检查认证和退出；test_batches 检查生命周期/幂等/原包；test_storage检查同步失败和最近成功时间；test_rebuild_trial_data检查保全与恢复。技术成功、状态日志或HTTP200不代表正式报销或到账。
