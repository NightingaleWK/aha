# 实例与生命周期契约

## 1. 范围与触发

修改 CLI、运行锁、runtime.json、实例识别、HTTP 退出或 Windows 托盘时阅读。相关代码在 instance.py、runtime.py、__main__.py、server.py、tray_windows.py；业务 Store/schema 不负责生产启动互斥。

## 2. 签名

```python
acquire_instance(data_dir: Path, *, timeout: float = 10.0) -> InstanceLease | LaunchDescriptor
InstanceLease.publish(bootstrap_url: str, run_id: str) -> LaunchDescriptor
InstanceLease.close() -> None
verify_instance(descriptor: LaunchDescriptor, timeout: float = 1.0) -> bool
ApplicationRuntime(server, lease).start() / run() / request_shutdown() / close()
WindowsTray(on_open, on_exit, tooltip="aha", icon_path=None).start() / run() / stop() / close()
```

CLI：`python -m aha [--data-dir PATH] [--port 0] [--no-browser] [--no-tray]`。port 只影响新建，复用沿用原端口；no-browser 不隐含 no-tray。Linux 不加载 Win32 适配器。

## 3. 请求与资源契约

- 规范化实际资料目录，在打开 Store 之前取得 `.instance.lock` 上的操作系统排他锁；同一实际目录的不同 EXE 复用，独立目录允许并行。锁文件长期保留且句柄不继承，不用删除文件“释放”。
- runtime.json 用原子临时写入/replace，字段为 descriptor_version=1、application="aha"、protocol_version=1、pid、run_id、profile_id、bootstrap_url。run_id 绑定 Application.launch_id，profile_id 为目录摘要；只有服务和必要托盘就绪后才发布，只按本次 run_id 删除。
- 启动器总等待最多 10 秒，单次探测最多 1 秒且共享截止时间。复用分支不得创建 Store、修改描述符或请求同步。
- 私有地址仅 `http://127.0.0.1:<端口>/?token=<凭证>`。直接回环连接，不用环境代理、不跟随外部重定向。bootstrap 换 Cookie 后，认证读取 `GET /api/instance` 并比对身份。
- 实例响应 `{application, protocol_version, run_id, profile_id, state}`；state 为 starting/ready/stopping，只有 ready 可复用。不查 Store，不带资料路径、token 或业务内容；保留 Host/Cookie 等现有边界。
- 页面与托盘统一请求退出：标记 stopping、拒绝新业务、取消有限同步、停止 HTTP、等待已接收请求/worker、关闭 Store/托盘、清理本次描述符，最后释放运行锁。HTTP 退出响应只代表请求已接受。
- 托盘初始化期间收到退出时锁存停止意图，正常结束启动，不发布描述符、不打开浏览器；线程赋值/start 与退出共用同步边界，启动失败不等待未运行的 loop。
- 托盘窗口和消息循环由创建线程管理，stop 只投递跨线程信号；回调异步执行。隐藏顶层窗口接收 TaskbarCreated，按实例重建内置图标。不得重启用户 Explorer 来验证恢复。

## 4. 校验与错误矩阵

| 条件 | 结果 |
| --- | --- |
| 已锁定但未 ready、探测失败或正在退出 | 有限重试；超时 `instance_busy`，不抢占或启动第二个 Store |
| 未支持的描述符/协议版本 | `instance_incompatible`，要求先退出原程序 |
| 旧格式记录 PID 可能仍存活 | `legacy_instance_running`，要求先正常退出旧版 |
| 新版崩溃，锁已释放，支持的描述符残留或坏 JSON | 取得锁后可新建，PID 复用不代表旧实例仍持锁 |
| 外部地址、错误身份、非 aha 监听者 | 不复用、不交给浏览器，不结束该进程 |
| 正在退出时请求新业务 | `application_closed` / HTTP 409 |
| 默认托盘初始化失败 | 反向清理并安全报错；不留下无入口服务 |
| 浏览器返回 false 或打开异常 | 安全提示，通过已有托盘或再次双击重试，不泄露凭证 |

未知文件和清理错误不通过删除业务资料解决。首次升级先退出旧版；旧二进制无法遵守新互斥协议。旧重建工具对白名单外锁文件保持保护。

## 5. 正常、基础与错误场景

- 正常：连续双击重开同一服务，刷新/多标签只恢复已有启动 job；第一次 no-browser 后打开页面仍可触发首轮同步。
- 基础：无桌面检查显式 no-tray；两个资料目录拥有独立服务和端口 Cookie，退出一个不影响另一个。
- 错误：仅凭 PID 或端口判断身份、先放锁再等 worker、关标签自动退出、将 OneFile bootloader 父子 PID 当成两个服务。

## 6. 必需检查

test_instance 覆盖跨进程同时冷启动/重复复用、目录别名、崩溃恢复、陈旧/坏描述符、协议与身份、来源不重读、退出请求/同步清理和启动失败回滚；test_http/test_http_cli 保留认证、持久重启和端口关闭；test_tray_windows 的原生部分验证真实结构、Shell 图标、消息与资源释放。

Windows 目录包与 OneFile 分别用隔离资料和真实浏览器验证重复打开、关页重开、双目录、同步去重与保存材料重启不变。原生消息检查与物理点击应如实区分；不能把 mock、历史结果或构建成功写成新成品完整验收。

## 7. 错误与正确做法

```python
# 错误：文件存在不等于锁有效，删除文件会制造另一份锁对象。
if (data_dir / ".instance.lock").exists():
    (data_dir / ".instance.lock").unlink()

# 正确：取得真实运行权或复用经过认证的身份；整个清理完成后才关闭 lease。
instance = acquire_instance(data_dir)
if isinstance(instance, LaunchDescriptor):
    open_browser(instance.bootstrap_url, tray_available=True)
```
