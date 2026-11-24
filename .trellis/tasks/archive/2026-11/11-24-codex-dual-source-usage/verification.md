# 双端 Codex 采集验收

验收日期为 2026-11-24（北京时间）。工作分支为 `codex/codex-dual-source-usage`，从 `dc41d0d` 开始。用户已确认现有三项任务的设计并授权执行。

## 采集与历史

- Windows 单文件成品对本机和 WSL 的真实 Codex 来源完成只读采集，在独立台账中验证两端都可入账。稳定后重读两端均新增 0 笔。Windows 实际样本有一行超过安全解析限制及一条无效累计记录，显示部分覆盖。WSL 样本覆盖完整。
- Windows Chrome 实测覆盖两端配置、起日与全部历史、键盘及焦点、跨端复制去重、失联的一端恢复、参考价、刷新和退出。验证 1440、1366、1280、430、375 五种宽度。
- 报销材料采用已选成员的来源与计价依据，原生记录可追溯到随版本提供的参考价。旧记录、历史日汇总、金额、归属、占用与冻结成员保留。
- 真实 schema 4 台账以一致只读快照备份，Directory 成品在独立目录还原到 schema 5。对比事实、版本、金额、项目、占用及原有修订投影一致。该实际快照未含冻结 ZIP，旧包字节保全由含冻结材料的 schema 3/4 兼容回归覆盖。

## Windows 桌面成品

Directory、OneFile 和系统桌面 `aha.exe` 分别以隔离资料实际启动，验证资源、压缩回读、材料、完整备份还原、重开复用和退出。桌面副本与已验收的 OneFile 哈希一致，原正式版保留为 `aha-v0.6.0-rollback.exe`。这次是本机开发交付，版本字段仍为 `0.6.0`。

使用隔离 Windows x64 Python 3.12.16 和 SQLite 3.53.1，通过构建入口的 SQLite 门禁。Directory 和 OneFile 生成的合成材料均以原生 Excel 16.0 检查 CSV 头和精确 Token/金额，并在 Chrome 输出有效 A4 PDF。托盘启用启动、通知区消息与退出通过，物理点击仍待补验。

原生 Windows 全量 Python 测试 372 项通过。前端状态测试 73 项通过，Ruff、严格 mypy、JavaScript 语法、compileall 和 `git diff --check` 通过。

源码指纹、成品 SHA256、浏览器、Excel 和 A4 结果见 [本机验收回执](research/windows-artifacts.json)。

验收结束后清理隔离快照、合成台账、Windows 构建目录、任务虚拟环境和缓存，合计约 1.16 GiB。清理后重新核对桌面两个 EXE 的 SHA256。[清理记录](research/cleanup.json)

## 发布评估

最近公开版为 v0.6.0。远端 main 相比其标签只有验收归档，累计待发产品改动为当前分支的原生采集、旧资料迁移和 CCS 读取退役。建议单独发布 v0.7.0，以醒目的升级说明覆盖数据来源变化。[公开版基准](https://github.com/NightingaleWK/aha/releases/tag/v0.6.0)

- 新增 Windows 与 WSL 的独立采集、范围选择和跨端去重。[新增功能片段](../../../../../.release/changes/codex-dual-source-usage.json)
- 退出 CCS 活库读取与 SQL 导入。正式旧台账及 schema 3/4 完整备份继续可用。[升级提醒片段](../../../../../.release/changes/retire-ccs-readers.json)

维护者于 2026-11-24 选择**先补齐发版条件**，并确认按工作提交方案提交归档、推送功能分支及创建草稿 PR 跑 CI。候选建议版本为 v0.7.0。待完成正式构建配方核验、功能分支最终提交的 CI、托盘物理点击及适用回执。[本地 What’s New 预览](research/whats-new-preview.md)
