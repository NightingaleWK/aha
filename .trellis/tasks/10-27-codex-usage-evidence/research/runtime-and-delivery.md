# 本地运行与交付依据

研究日期：2026-10-27。本文是任务约束，不把拟议结构描述为已有代码规范。

## 已只读验证的环境

- 开发目录 `/home/djsyw/code/aha` 位于 WSL，Python `3.14.4`；WSL PATH 暂无原生 Node / Cargo，本次未安装工具链。
- Codex 提供的 Windows Python 位于 `C:\Users\djsyw\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`。实际运行版本 `3.12.14`、平台 `Windows AMD64`、SQLite `3.53.1`。
- `load_workspace_dependencies` 返回 Windows Node：`C:\Users\djsyw\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe`。本轮只发现路径，未据此声称已完成前端检查。
- Windows CCS 默认库存在。在 Windows 原生 Python 中用 `mode=ro`、`PRAGMA query_only=ON` 查询，确认 `user_version = 23`，具有 `proxy_request_logs`、`usage_daily_rollups`、`model_pricing`。未读取供应商密钥或配置内容。
- WSL `/home/djsyw/.cc-switch/cc-switch.db` 是另一来源，不自动合并，也不代替 Windows 数据。
- Windows 运行时未装 PyInstaller。后续依赖安装到任务自有隔离环境，不改 Codex bundled Python 或用户全局环境。

## 实现选择与依据

- Python `3.12+` 标准库负责 SQLite、Decimal、CSV、ZIP、HTTP 和 HTML 生成；原生 HTML / CSS / 少量 JavaScript 提供本地浏览器界面。
- 项目识别纳入首期后，压缩日志头读取需要额外的 `zstandard` 运行依赖，固定版本并随 EXE 交付，用户无需另装。[安装文档](https://python-zstandard.readthedocs.io/en/latest/installing.html)列明 Windows 和 Python 3.12 支持；[流式解压 API](https://python-zstandard.readthedocs.io/en/latest/decompressor.html)支持有界读取，不能全量解压日志。研究时 WSL Python 3.14 使用标准库完成头部验证，不代表 Windows 3.12 自带此能力，打包仍需实测。
- 不依赖在线 CDN、Node 服务、React 或原生桌面框架运行时。开发检查用隔离环境内的 Ruff、mypy、可用 Node 语法检查与真实浏览器。
- [Python sqlite3 文档](https://docs.python.org/3.12/library/sqlite3.html)支持 URI 只读连接和在线 backup API。用只读源取得一致的内存快照，再从允许字段构建分析输入。
- [SQLite URI 文档](https://sqlite.org/uri.html)说明 `immutable=1` 会跳过锁和变化检测；不能这样读取仍变化的 CCS 库，也不能仅复制主 `.db` 忽略 WAL。
- 输入 SQL 仅解释所需表的常量数据，不执行提供的 DDL、函数、触发器、ATTACH 或其他程序；不将全库配置写入本地磁盘副本。
- [PyInstaller 文档](https://pyinstaller.org/en/stable/operating-mode.html)支持含运行时的 Windows 成品，要求在相应平台构建。先验证目录包，再构建便携 `aha.exe`，不能把 Linux 产物改后缀充当 EXE。
- Windows 构建如需本地文件系统，使用任务自有临时目录和隔离环境；不复制真实备份或凭据。

## 验证边界

已验证原生 Python 与源库只读结构查询。尚未做并发快照实验、依赖安装、程序构建和浏览器验收；必须在实施阶段取得实际运行证据，不能用文档支持替代实测。
