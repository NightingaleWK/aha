# 兼容 CC Switch 结构 27

## 目标

恢复 CC Switch 升级后中断的 Codex 用量同步，让用户从桌面打开 aha 即可继续使用。

## 已核实

- 本机 CC Switch 4.0.35 的 SQLite `user_version` 为 27，三个用量相关表具备现有适配器要求的字段。`src/aha/domain.py` 的外部版本白名单只到 26。
- [上游 26→27 迁移](https://github.com/farion1231/cc-switch/blob/61c43c036ec7eb3a6950b292729d6a7094abe716/src-tauri/src/database/schema.rs#L731-L746) 给技能仓库和已安装技能新增主机字段。三个用量相关表的建表定义、日汇总逻辑及 [SQL 导出版本声明](https://github.com/farion1231/cc-switch/blob/61c43c036ec7eb3a6950b292729d6a7094abe716/src-tauri/src/database/backup.rs#L704-L712) 对现有投影兼容。上游会话导入器有独立的分叉识别等变化，aha 继续沿用其已写入的记录以及现有来源核对机制。

## 需求

- SQLite 同步和带用量的 SQL 备份显式支持外部结构 27，兼容 23–26，记录每轮实际外部版本。保留必要表和列、SQL 版本唯一性以及未知版本校验。
- 按现有规则保留内部投影 23、应用库 schema4、消费身份、Token 语义、历史金额和冻结材料。相同消费重复同步不得增计。
- 提供中文 What’s New 片段和按源码构建验证的 Windows 单文件 `aha.exe`，放到系统实际桌面。

## 验收

- [x] 来源、台账与 HTTP 回归覆盖结构 27 成功、23–26 兼容、28 和坏字段拒绝。版本变化后同一消费的指纹、归属、报销占用和原包字节一致，失败保留成功状态。
- [x] Windows Directory 与 OneFile 均执行结构 27 启动、23–27 逐版手动同步、SQL 27、未知 28 拒绝与恢复、材料保存和原包下载、重开和退出。使用隔离 aha 资料只读验收本机 CCS。Edge、Excel 和 A4 PDF 通过。累计发版所需的托盘实际点击和云端验收记录见 [发版评估](research/release-assessment.json)。
- [x] 桌面副本独立启动验证，SHA256 与 OneFile 一致。留存证据并清理此次任务专用环境和中间文件。见 [验收记录](research/verification-summary.json) 和 [清理记录](research/cleanup.json)。

## 范围边界

CC Switch 及正式台账只用于只读验证和独立副本验证。统计规则、历史迁移及 GitHub 正式发布各自沿用已有合同，发布由收尾评估后单独决定。
