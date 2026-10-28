# 前端质量要求

## 自动检查

从仓库根用可用的本地 Node 运行 `node --check src/aha/web/app.js`。若开发环境通过 Windows Node 读取 WSL UNC 路径时发生 package config 错误，可在 Windows 文件系统工作目录以 `node --input-type=commonjs --check` 从标准输入送入同一脚本检查；记录调用方式，不把个人运行时路径固化为项目要求。

后端请求形状使用隔离 Python 环境运行：

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_http*.py' -v
```

此命令同时包括 HTTP 和 CLI 生命周期。其他代码质量检查见 [后端质量要求](../backend/quality-guidelines.md)。仅文档且源码不变时检查链接/引用和一致性，不重复已通过全套基线。

真实 HTTP 场景参考 [test_http.py](../../../tests/test_http.py) 的共享 CookieJar 测试，片段如下：

```python
self.assertEqual(len(cookies), 2)
for index, server in enumerate((self.server, other)):
    with browser.open(server.origin + "/api/status", timeout=10) as response:
        status = json.load(response)
```

它验证同浏览器认证两个实例；直接 Store 调用或静态代码字符串断言没有覆盖浏览器 Cookie/请求形状。

## 何时需要真实浏览器

改变请求字段、预览失效、生命周期、下载或布局时验证实际页面。使用隔离资料，测试从界面触发 API，检查反馈和材料；不以直接调用后端替代整条 UI 链路。

- 启动同步去重、手动 SQL/默认数据库、失败/needs_review 终态和刷新恢复；项目/日期、元数据、游标分页与人工归属。
- 保存占用→剩余可用→旧预览阻止→专用修订→提交/撤回→已报销作废→释放重用。
- 旧创建/作废请求重放、重启后原包、原生退出和端口关闭；来源重建/覆盖/版本候选的明确核对。
- **保持修订弹窗打开**时改变占用/权限，确认旧 analysis 清除且禁保存，重新预览后才能继续。
- 保存成功后下载失败能从记录重下；历史与作废版本仍可下载，不能误显示修改动作。

## 视觉、文案与导出

核对 computed style、1440/1366/1280 桌面及 430/375 窄窗口，包含长名称/金额、完整 CNY/USD、空/错误态、弹窗内错误和退出状态。检查真实截图和物理显示，不能用 CSS 字符串测试代替，也不把设备像素密度当浏览器缩放。

正文/输入 16px、表格/按钮 15px、标签/表头 14px、次要至少 13px；更多产品顺序与文案要求见 [页面契约](./local-web-contract.md)。用量/金额显示、CSV、每日汇总、HTML/JSON 要取同一实际成员与精确金额，不受分页影响。

发布阶段分别记录目录包和 OneFile 的真实 EXE/浏览器运行，CSV 在目标 Excel 打开，HTML 打印逐页检查。已有归档验收只是相应版本和时间的历史证据；只改文档不会生成新的 Windows/Excel/业务验收。个人截图、ZIP、打印文件留在 Git 外。
