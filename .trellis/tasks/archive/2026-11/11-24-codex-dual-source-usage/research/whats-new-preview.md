# What’s New · v0.7.0

## 兼容性与升级提醒

- **退出 CC Switch 数据库读取与 SQL 导入**：已有 aha 历史、项目、报销占用和旧原包随正式台账迁移。旧 schema 3/4 的完整备份仍可还原。
## 本次亮点

- **直接同步 Windows 和 WSL 的 Codex 用量**
- **退出 CC Switch 数据库读取与 SQL 导入**

## 新增功能

- **直接同步 Windows 和 WSL 的 Codex 用量**：aha 直接从两端的 Codex 会话和归档增量读取用量。每端独立显示进度与失败原因，同一用量回读或复制时按证据去重。项目统计和报销材料继续使用同一本本地台账。

## 升级说明

- 在数据来源中确认 Windows Codex 目录和 WSL 发行版。已有历史时默认从台账最后一个北京时间日期接续，可调整起始日期补采。
- 如果需要保留只存在于 CC Switch 中且缺少 Codex 原生日志的历史，请在升级前用旧版将这段用量入账，并生成完整 aha 备份。

## 下载与完整变更

- [Windows x64 单文件 EXE](https://github.com/NightingaleWK/aha/releases/download/v0.7.0/aha-0.7.0-windows-x64.exe)
- [SHA256 校验信息](https://github.com/NightingaleWK/aha/releases/download/v0.7.0/SHA256SUMS.txt)
- [完整变更](https://github.com/NightingaleWK/aha/compare/v0.6.0...v0.7.0)
