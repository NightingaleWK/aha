# 启动与托盘研究

研究日期：2026-10-28。以下是规划依据，不是新功能测试报告。

## 源码事实

| 位置 | 事实与设计影响 |
| --- | --- |
| `src/aha/__main__.py:18` | 默认目录独立于 EXE；复制 EXE 不能绕开同一资料运行权。 |
| `src/aha/__main__.py:26`、`:52`、`:79` | 当前每次建服务，runtime 原子覆盖且按本次 run_id 删除；保留这些语义，新增真正的运行锁。 |
| `src/aha/server.py:95`、`:110`、`:229` | Application 持有启动身份/凭证、有限 worker 与取消事件，启动同步按服务生命周期去重。 |
| `src/aha/server.py:494`、`:582`、`:609`、`:621`、`:731` | 已限制回环、Host、Cookie、Origin、CSRF；新增识别仍须认证，托盘走进程内退出。 |
| `src/aha/web/app.js:795`、`:808`、`:938` | 初始化发起 startup 同步并恢复任务；当前退出接口成功立即显示已退出，应核对新关闭状态的准确表达。 |
| `src/aha/storage.py:23`、`:247` | Store 拥有事务/连接，不把实例运行权放进其构造器。 |
| `tests/test_http_cli.py:19`、`tests/test_http.py:376` | 沿用自有进程树清理和同浏览器双实例 CookieJar 回归。 |
| `scripts/rebuild_trial_data.py:87`、`:153` | 清理按白名单且拒绝可能存活 PID；不将新锁文件顺便加入删除范围。 |
| `scripts/build_windows.py:107`、`:108` | 默认无控制台，启动错误需安全原生反馈，目录包/OneFile 分别验收。 |

## 官方能力依据

- [Python msvcrt.locking](https://docs.python.org/3/library/msvcrt.html#msvcrt.locking)：Windows 标准库有文件区域锁和立即失败的 LK_NBLCK；固定区域、长期持有句柄，不按 PID 文件存在判断占用。
- [Microsoft _locking](https://learn.microsoft.com/en-us/cpp/c-runtime-library/reference/locking?view=msvc-170)：锁从当前偏移开始，可超过 EOF；冲突与无效句柄是不同错误，须固定 seek/范围并区分错误。
- [Python flock](https://docs.python.org/3/library/fcntl.html#fcntl.flock)：Unix 提供排他/非阻塞标志，适配现有 Linux CLI 与检查，无需额外锁依赖。
- [Shell_NotifyIconW](https://learn.microsoft.com/en-us/windows/win32/api/shellapi/nf-shellapi-shell_notifyiconw)：原生 API 可添加、修改、移除图标，适合本次两个托盘操作。
- [TaskbarCreated](https://learn.microsoft.com/en-us/windows/win32/shell/taskbar#taskbar-creation-notification)：Shell 向顶层窗口广播重建事件，应用应重新添加图标。
- [Message-only windows](https://learn.microsoft.com/en-us/windows/win32/winmsg/window-features#message-only-windows)：此类窗口不接收广播，因此用隐藏顶层窗口接收重建通知。
- [PyInstaller bootloader](https://pyinstaller.org/en/stable/advanced-topics.html#bootloader)：OneFile 可以有父子两个进程；本任务保证一个服务所有者，不能承诺任务管理器只有一个 PID。

## 技术决定

1. 使用资料目录内操作系统锁，避免固定端口冲突和仅凭 PID 的误判；异常退出不靠删除标记恢复。锁文件退出时保留，避免 inode/句柄竞争。
2. runtime 只用于定位与凭证；HTTP 核验限定主机/协议/身份，不跟随外部重定向或代理。识别接口不读业务库，避免重开受长查询拖累。
3. ctypes 原生托盘减少运行时依赖；代价是结构布局、回调寿命和消息线程需真实 Windows 验证。
4. 退出由同一控制器负责，锁最后释放；请求被接受与进程完全结束分开表达。
5. 首次升级先退出旧版，不强制结束未知进程，不改业务库或放宽试用清理白名单。

## 实施验证项

Windows 锁竞争/崩溃释放、目录别名、ctypes 布局与句柄清理、菜单/图标重建、HTTP 与同步退出排序、目录包和 OneFile 的真实资源与关闭。方案与验证路径已在 design.md/implement.md 给出，这些是待执行技术验证，不是待用户决定的产品问题。
