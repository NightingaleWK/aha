# 后端开发规范

aha v0.3.0 是 Python 3.12+ 本机 Codex 台账与费用证据工具。产品实现位于 `src/aha/`，CCS 来源只读，业务在独立 Store/schema3 查询；SQLite 运行时必须通过并发修复门禁。这里记录当前实现的开发约束；用户说明见 [README](../../../README.md)。

## 开发前检查

- 先读当前任务的需求、设计和执行计划，再读 [用量证据与本机运行契约](./usage-evidence-contract.md)。
- 识别本次修改涉及来源读取、领域计算、应用库、冻结材料还是 HTTP；按下表补读分题。
- 使用任务自有 venv 和 `--data-dir`，个人源库、材料和运行凭证不进入 Git。
- 跨层修改同时读 [前端契约](../frontend/local-web-contract.md) 和 [跨层思考指南](../guides/cross-layer-thinking-guide.md)。

## 规范索引

| 文档 | 解决的问题 |
| --- | --- |
| [用量证据与本机运行契约](./usage-evidence-contract.md) | 来源、核算、独占、版本、迁移、HTTP 与交付的不变量 |
| [目录与模块职责](./directory-structure.md) | 功能放在哪里、如何通过 Store 门面复用领域模块 |
| [SQLite 与持久化](./database-guidelines.md) | 只读来源、事务、备份、迁移及不可变文件 |
| [错误处理](./error-handling.md) | AppError、状态码、安全消息和故障回滚 |
| [运行输出与操作历史](./logging-guidelines.md) | 私有启动输出、关闭的默认日志和库内审计事件 |
| [质量要求](./quality-guidelines.md) | Python 检查、测试实例、隔离和原生发布门禁 |

## 质量检查

按 [质量要求](./quality-guidelines.md) 运行与改动相符的测试、Ruff、strict mypy 和 compileall；接口/页面变更增加 HTTP 与实际浏览器验证。Windows 发布须完成目录包、原生程序、Excel/打印及 OneFile 门禁，不能仅凭 Linux 测试宣布发布通过。

规范和任务说明使用简体中文，命令、路径、字段、错误码和协议标识保留原文。仅文档变动时检查引用、占位、业务一致性和写入范围；源码未变且基线已通过时，不重复全套产品测试。
