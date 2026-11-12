# 首轮正式PR CI：Windows短路径断言

运行：[43177104150](https://github.com/NightingaleWK/aha/actions/runs/43177104150)，源码da826a723b81e76f805e3d8e13e0679dff9bbddf，原生Windows/Python3.15.2。固定构建依赖安装成功，release inputs通过；351项Python中350通过、1失败，后续静态/JS步骤按退出码跳过，不能记通过。

唯一失败为`test_http_backup.BackupHTTPTests.test_full_http_roundtrip_keeps_current_ledger_and_original_packages`第118行的路径字符串断言。产品报告的目标在`C:/Users/runneradmin/.../restored`，测试TemporaryDirectory给出同目录的8.3短名`C:/Users/RUNNER~1/.../restored`。产品按既有合同规范化路径，错误在测试将两种有效表示当作两个不同目录。

修复仅限测试比较真实目录身份或规范化后的路径，保留后续事实、项目、材料、恢复入口等业务断言；不修改产品、API、SQLite门禁或备份验证。固定源码的新CI仍须完整通过后再合并PR。

本记录依据GitHub连接器直接取得的job日志（job131043907724），不把本机3.12通过结果替代该失败或其后续3.15重跑。
