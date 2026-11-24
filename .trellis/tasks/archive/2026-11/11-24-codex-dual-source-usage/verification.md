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

维护者于 2026-11-24 选择**先补齐发版条件**，并确认提交归档、推送功能分支及创建草稿 PR 跑 CI。候选建议版本为 v0.7.0。[本地 What’s New 预览](research/whats-new-preview.md) · [功能 PR #15](https://github.com/NightingaleWK/aha/pull/15)

## 发布前复验

- Windows x64 Python 3.15.2、SQLite 3.53.4 与固定构建依赖组成的本机运行时摘要与公开 v0.6.0 一致。SQLite 与 Zstandard 原生模块从已校验的公开产物取得，分别核验归属、模块字节和两种新包内的文件哈希。
- 首轮 CI 的 372 项 Python 测试和 Ruff 通过，Windows mypy 对 POSIX 常量报错。`aa1576e` 以 `sys.platform` 限定分支，保留既有只读标志。Windows 和 Linux 平台的严格 mypy、本机 Windows 的 23 项来源相关测试及 WSL 文件读取边界检查通过。[首轮 CI](https://github.com/NightingaleWK/aha/actions/runs/45335690745) · [最新 PR 检查](https://github.com/NightingaleWK/aha/pull/15/checks)
- 修正后的 Directory 和 OneFile 分别通过实际程序、Windows Chrome 双来源同步、Excel 和 A4 PDF。并发验收期间有一轮 OneFile 的 WSL 发现未返回，在其余本机检查结束后用同一 EXE 和全新资料目录复跑通过。
- 维护者实际双击托盘、从右键菜单打开 aha，再使用菜单退出。验证进程以 0 退出、运行描述文件移除且端口关闭。此回执绑定实际点击测试的 `1c86767`，其托盘与构建配方指纹和最终源码一致。[托盘执行证据](research/windows-release-tray.json) · [托盘回执](../../../../../.release/acceptance/codex-dual-source-windows-tray.json)
- 已从最终单文件版更新系统桌面 `aha.exe`，以桌面副本验收业务和退出，哈希 `2f8a5652a81466be981f05e23df238b194a4901df24ea8b0814c495a04fd5be8`。回退副本 `aha-v0.6.0-rollback.exe` 校验通过。此开发成品的版本字段仍为 `0.6.0`。[复验事实和成品](research/windows-release-preflight.json) · [发布验收回执](../../../../../.release/acceptance/codex-dual-source-windows.json)

发布脚本已识别当前运行时下的全部六项本机回执。正式发布使用发布 PR 统一升号和合并后 GitHub 构建，检查云端产物及其运行时摘要。

结束复验后确认任务临时目录内无占用进程，清理隔离 Python、构建目录、缓存、合成资料及验收所用浏览器目录，共 497.2 MiB。随后再次核对桌面成品及回退副本的 SHA256。
