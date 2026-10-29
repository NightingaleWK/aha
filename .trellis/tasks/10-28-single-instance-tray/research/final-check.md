# 完整范围复核

2026-10-28，按后端与前端质量要求复核本任务全部产品差异、打包资源、运行规范和测试。未提交或归档任务。

## 已修复

- `src/aha/runtime.py`、`tests/test_instance.py`：HTTP 线程创建失败时，原实现保留未启动的线程对象，清理会尝试关闭/等待不存在的服务循环。现在转换为安全 `service_unavailable`，清空未启动对象，回归证明监听端口关闭且运行锁可重新取得。
- `src/aha/runtime.py`、`src/aha/__main__.py`、`tests/test_instance.py`：托盘建立期间收到退出请求，原实现仍可能继续创建服务和发布描述符。现在同锁保护线程创建与退出，启动中 stopping 正常结束，入口跳过打印地址、打开页面和进入消息循环；确定性回归证明一次退出即可完成，未发布 runtime，端口关闭且运行锁释放。`start()` 签名不变。
- `src/aha/instance.py`、`tests/test_instance.py`：操作系统无法创建探测线程时返回未验证，不将原始 RuntimeError 暴露给启动流程；不接受未知监听者。
- `src/aha/storage.py`：在原 POSIX 目录 fsync 分支增加静态可识别的 Windows 平台排除，修复原生 Windows strict mypy 对 `os.O_DIRECTORY` 的错误。保留原 Linux/Windows 文件发布行为，未改变数据库或核算逻辑。

## 核对结论

- 生产入口在 Store 前取得资料目录真实运行锁，复用分支不创建 Store、不触发同步；锁文件保留，退出清理最后释放运行权。
- 复用地址、Cookie、协议和实例身份均验证；探测有整体墙钟预算，外部地址、外部重定向、非 aha 身份和 stopping 状态不接受。
- HTTP 请求计数在派发前登记，退出等待已接收请求和取消后的有限同步任务，未将 HTTP 退出响应当成完整清理完成。
- Windows 托盘适配器的句柄/回调声明、主线程所有权、异步回调、TaskbarCreated 和资源回滚已复核；ICO 包资源与两个构建入口均覆盖。
- 重开时无法确认原实例是否带托盘，当前入口使用通用浏览器重试提示，未错误承诺存在托盘。
- Store 独立连接/进程事务边界、认证、启动同步去重及现有冻结材料语义保留。

## 验证

- Linux 完整测试：181 项，成功，2 项 Windows 原生托盘用例按平台跳过，耗时 22.184 秒。
- 新实例/生命周期回归：23 项全部成功，含 5 进程并发冷启动、崩溃恢复、目录别名、身份/预算、请求/同步清理、线程创建失败和启动中退出。
- Ruff：`check src tests scripts` 成功。
- strict mypy：Linux 全部 21 个源文件成功；Windows 独立缓存检查全部 21 个源文件成功。
- compileall 与 git diff 空白检查成功。
- 验证使用任务隔离环境及修复版 SQLite，未修改系统/共享依赖，未执行大规模性能复测。

## 初次复核后的待办（历史）

没有留下未修复的已知产品代码问题。最终源码已冻结，可构建 Windows 目录包。主会话仍负责修复后的 Windows 测试回归、目录包/OneFile 各自的真实 EXE 与浏览器验收，并如实区分原生消息验证和托盘物理点击限制；这些结论以 verification.md 的实际结果为准。

## 2026-10-28 成品证据复核补记

- 主会话已完成最终 Windows 181 项检查（1 项既有重建 symlink 权限夹具跳过）、源码/Directory/OneFile 各 8 项真实浏览器与原生消息自动流程、复制 EXE/NTFS junction/不同端口复用，以及目录包 CSV 的原生 Excel 只读检查和 A4 渲染。OneFile 两份 CSV 仅声称与目录包已验证输出逐字节一致，没有写成另一次 Excel 打开或独立打印验收。
- 复核了 acceptance 下全部 7 份白名单 JSON：阶段结果、成品摘要和 verification.md 一致；source-files.json 中 29 个打包输入指纹与当前文件全部一致，未变更产品源码或重跑已通过代码测试。
- 白名单证据不含私有启动地址、token、Cookie、CSRF、原始截图或个人数据。将工具错误中的个人绝对目录改成通用 WSL 路径说明，并将“完整流程”收窄为“自动流程”，避免误读为全部交互已验收。
- AC4 明确保留实际鼠标展开托盘菜单/点击未覆盖；原生 Win32 消息不计为物理点击，未声称全部 AC4 通过，也未将用户未豁免的限制自动关闭。
- 当前 task.json 仍为 in_progress，commit/completedAt 为 null；提交确认、归档和会话记录仍待主会话按流程处理。完整执行结果以 [验证记录](../verification.md) 和 acceptance 中对应摘要为准。
