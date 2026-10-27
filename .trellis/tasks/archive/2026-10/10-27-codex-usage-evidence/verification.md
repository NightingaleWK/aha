# 实施与交付验证

日期：2026-10-27。代码分支：`feat/codex-usage-evidence`。本记录区分自动测试、真实数据技术验收与用户后续业务使用；测试申请金额不是实际报销申请。

## 交付物

- Windows x64 GUI 单文件：`C:\Users\djsyw\Desktop\aha-v0.1.0-20261027\aha.exe`。
- 同目录包含 `使用说明.md`、`SHA256.txt`，不含测试项目、测试批次、个人备份或原费用材料。
- 版本 `0.1.0`；EXE 大小 `10,143,465` 字节。
- SHA-256：`9db93fb5c58406afcd3de138063a961dc14d66e224c8157fe9fb60753f24260a`。
- 源码、测试、构建入口和完整开发说明保存在本仓库。EXE、个人证据和截图在 Git 忽略范围或仓库外。

## 工程检查

| 检查 | 结果与范围 |
| --- | --- |
| Linux unittest | 完整 89 项通过 |
| Windows 原生 unittest | 完整 89 项通过，日志 `native-tests.log` |
| Ruff | `src tests scripts` 通过 |
| strict mypy | `src/aha` 与两个 Python 构建脚本，共 15 文件通过 |
| compileall / Node | Python 编译与原生 Node JavaScript 语法检查通过 |
| Trellis 上下文 | implement/check 各 9 项，含实现后规范，validate 通过 |
| 检查代理 | 全范围及最后增量检查完成，无未决代码问题；已补真实代码规范 |

Windows 原生运行时 Python `3.12.14` / SQLite `3.53.1`；构建为 PyInstaller `6.22.3`、zstandard `0.25.0`。实际成品为 `PE32+ ... (GUI), x86-64`，内置 Python、zstd 扩展、静态资源和许可证。

本机 PowerShell 脚本执行策略拒绝 `.ps1` 入口，因此增加纯 Python 构建入口；未修改执行策略或用户全局环境。依赖安装、构建及测试均在任务自有 Windows 隔离环境进行。先通过目录包及重启验证，再传 `--directory-verified` 构建单文件。

## 真实来源与核算

所给 SQL 在读取前后 SHA-256 相同：

`1c19a1b1c0da4355bcb4b98c6a47d909619b92507cebf9ad2c8f5eb8e3c7042b`

| 核对项 | 实际结果 |
| --- | --- |
| 所给 SQL | 10,852 条明细、110 条 Codex 历史日汇总 |
| 北京时间 2026-10-26，全部项目 | 793 条明细、`32.8928704 USD` |
| 会话头关联 | 178 / 178 个会话，含普通和 zstd 压缩日志 |
| 流萤目录规则样例 | `/home/djsyw/code/liuying` 命中 2,994 条明细，`137.0881180 USD` |
| 归属分区 | 各项目加未归属的记录数、各类 Token、Decimal 金额严格等于全部 |
| 重读 | 同内容 capture 身份相同，不增加快照总费用 |
| 来源清理与重启 | 测试确认原件移除后，可独立恢复留存和原 ZIP；不跨快照拼账 |

目录线索覆盖与业务归属分开：程序按用户规则或人工指定分类，不通过正文猜测。旧日汇总保持来源粒度。成本沿用 CCS 保存金额，申请金额另填，不分摊订阅或计算汇率。

## 原生程序与真实浏览器

Windows Chrome `156.0.8078.48` 中，目录包和最终单文件分别走完下列流程：

1. 原生 EXE 启动，本机默认 Windows CCS 库只读加载。
2. SQL 备份导入，实际统计和日期验收值一致；单文件另验证显式刷新目录依据。
3. 新建流萤项目，绑定 Linux 与 Windows 两个目录；单文件实测从发现列表勾选和手填并用。
4. 项目及日期预览、50 条分页与翻页、人工归属修正后重算。
5. 首次创建草稿并下载四文件 ZIP；重下载原版本，SHA-256 相同。
6. 将 v1 人工改为已报销，修改说明和申请金额生成 v2；v2 为草稿，v1 的状态、内容和原包保持。
7. 跨批次重叠提示可查看，确认继续后生成新批次；不自动扣减费用。
8. 430px 窄窗口检查，根页面无横向溢出；检查空结果、无效结构导入与旧预览失效。
9. 退出后进程正常结束、端口关闭、runtime 凭证文件删除。
10. 重启同一隔离资料目录，恢复项目、历史 SQL 留存、两份版本及 v1 已报销状态；重新下载 v1 与首次 ZIP 哈希相同，流萤仍为 2,994 条。

桌面交付副本另以不带 `--no-browser` 的参数启动：仅为这次测试设置子进程的浏览器选择，自动打开隔离 Chrome，未由测试脚本导航页面，便自行加载默认库。实际页面读取与可见退出按钮均验证通过，正常退出清理凭证。未改系统默认浏览器或正式资料目录。

两轮浏览器最终检查无未处理脚本或控制台错误。真实端到端检查修复了两个界面问题：新批次预检发送空批次 ID；新版本保存后已展开详情滞后。前者有完整 HTTP 请求形状回归，后者由真实浏览器验证两版本及旧状态保持。

## CSV、证据包与打印

最终单文件生成的原包 SHA-256：

`54355335640441443a117e6e6e7a1e6f55848a5f9f2a13c124b4d77479cad087`

- ZIP 恰有四个约定文件，三份内容的 manifest 哈希均一致；分享投影不含完整源路径、目录规则、账号配置或正文。
- 明细 CSV 有 2,994 条数据，日报 CSV 有 10 条数据；两份 Decimal 汇总及 manifest 总额同为 `137.0881180 USD`，不受界面分页限制。
- 本机 Microsoft 365 Excel `16.0` 实际只读打开两份 CSV：明细 `2995 × 23`（含表头），日报 `11 × 17`；中文项目名正确，金额识别为数字。Excel 浮点求和与精确 CSV 值在 `1e-9` 内一致。
- 浏览器实际打开费用说明，使用打印媒体生成 A4 PDF；目录包的 2 页已渲染逐页检查，表格、中文、金额和说明未截断。最终单文件 HTML 再次打印成功。
- 验收中人工填写的 `100.00 CNY`、新版本的零金额均为测试，不作为真实报销材料交付。

## 证据位置与保留边界

个人运行证据位于仓库外 `C:\Users\djsyw\Documents\Codex\aha-qa-01a17b2c`，主要文件：

- `real-data-integration.json`
- `directory-final-browser.json` / `directory-final-restart.json`
- `portable-browser.json` / `portable-restart.json`
- `portable-export-check.json` / `portable-print-check.json`
- `auto-launch-check.json` / `desktop-exe-auto-launch.png`
- `portable-day.png`、`portable-projects.png`、`portable-batches.png`、`portable-narrow.png`
- 实际 ZIP、导出的 CSV/HTML、打印 PDF 和逐页 PNG

构建日志、隔离 venv 与源码副本位于任务自有 `aha-build\20261027-codex-usage-evidence`。这些 QA 资料不复制进正式默认资料目录或桌面交付目录，不写入用户 OneDrive 费用记录。

## 收尾状态

实现、规范、原生交付和技术验证已完成。用户已于 2026-10-27 回复“ok”，批准按 `commit-plan.md` 进行本地工作提交、当前任务归档及会话日志；具体提交标识见 Git 历史和会话日志。规范初始化任务 `00-bootstrap-guidelines` 未被本次部分规范补充冒充完成。
