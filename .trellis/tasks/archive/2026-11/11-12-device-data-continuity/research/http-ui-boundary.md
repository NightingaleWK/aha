# HTTP 与页面实施边界

最小行为缺口是完整 aha 备份/还原缺少可操作入口、旧账本缺少新电脑来源确认、空时段容易误解为历史丢失，以及核对提交后没有重新查询。HTTP 边界属于 server.py，原生页面状态及结构属于 web/app.js、index.html、style.css。

本代理仅改这些文件、新增 HTTP 备份/来源绑定回归及 web_state 状态测试。backup.py/Store/CLI 由 backup_core 负责，source_bindings/sync/身份与目录依据由 source_recovery 负责；不改写真实用户资料，也不做全库合并或源码外的发布操作。

复用现有认证、Origin/CSRF、受控 worker、独立 busy/syncBusy 与请求代际。完整备份使用有限后台任务和文件下载，上传按固定大小二进制分块；还原必须新目录并提供打开恢复台账入口。原有费用材料下载、同步轮询与退出行为需保持，变化以 HTTP/状态回归验证。
