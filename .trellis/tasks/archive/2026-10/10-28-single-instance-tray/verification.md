# 单实例与托盘验证记录

检查日期：2026-10-28；收尾日期：2026-10-29。实现与自动检查完成，已提交并合并本地 main；按用户明确指令归档，实际鼠标交互仍未验收，不计为通过。

## 环境与隔离

- Linux：Python 3.14.4，任务 `.venv-single-instance-tray`；仅该进程加载既有任务私有 SQLite 3.53.4，系统 SQLite 未修改。
- Windows：任务自有 Python 3.12.14 / SQLite 3.53.1 venv，固定开发/打包依赖；构建与验收资料均位于本任务专有临时目录。
- 原生 Chrome 156.0.8078.48 独立配置目录，BROWSER 只在自有测试进程内指向此配置。默认资料来源被隔离到小型合成 home，没有读取用户实际 CCS 库。
- 凭证只存在私有描述符/浏览器中；入库摘要不包含私有启动 URL、token、Cookie、CSRF、个人资料或原始截图。

## 自动检查进度

| 项目 | 当前结果 |
| --- | --- |
| Linux 全量、Ruff、strict mypy、compileall | 最终 181 项成功，2 项 Windows 专属检查按平台跳过；其余门禁通过，详见完整复核记录 |
| Windows 全量 | 最终 181 项成功，55.188 秒，跳过 1 项既有重建 symlink 权限夹具；本次目录别名用 NTFS junction 已通过 |
| Windows Ruff、compileall、JS 语法 | 通过；JS 用 Windows Node 从 stdin 检查同一脚本 |
| Windows strict mypy | 独立缓存、全部 21 个源文件通过；既有 O_DIRECTORY 平台类型分支已修复 |
| 原生托盘适配器 | 8/8 通过，含真实 Win32 结构、窗口、Shell 图标、键盘激活、重建和资源清理 |
| 源码模式自动链路 | 8/8 通过，0 browser pageerror |
| Directory 成品 | 8/8 自动流程通过，0 browser pageerror；原生 Excel 只读核对 CSV，A4 一页并渲染目视无裁切 |
| OneFile 成品 | 8/8 自动流程通过，0 browser pageerror；两份 CSV 与已由 Excel 核对的目录包输出逐字节一致 |
| 复制 EXE / 目录别名 / 显式端口 | 复制的 OneFile 通过 NTFS junction 访问同一资料、指定另一端口，仍复用原 run_id，退出清理成功 |

## 已执行的自动流程

真实 Chrome 与原生 Windows 自有进程依次验证：默认启动打开页面和托盘；刷新与保存项目/原包；5 次并发复用；关闭所有 aha 页面后再次启动找回；托盘双击消息打开与 TaskbarCreated 重建；第二资料目录独立运行及页面退出；托盘退出/持久重启/原包 SHA 保留；自有进程终止后的陈旧描述符恢复及最终页面退出。

托盘整体链路使用真实隐藏窗口的 Win32 消息触发，未使用 mock，但不等于实际鼠标点击验收。Computer Use 工具在初始化即报 `sandboxCwd is not a local file URI`（当前 WSL 工作目录），重置后同样失败；未通过替代桌面输入绕过。实际鼠标展开菜单/点击仍未覆盖，不宣称已验证。

## 成品与证据

| 成品 | SHA-256 |
| --- | --- |
| Windows Directory 的 aha.exe | `a9f55ff6ff52abb10fc65866ca7cb25170f50af8a4f7c7a5232ac38738bd9183` |
| Windows OneFile 的 aha.exe（10,239,834 字节） | `89c1292bfd065c0782c42acdb1aeb2b457920c5c102a0a4216f8ed94cbb21e75` |

成品保存在本任务的 `%LOCALAPPDATA%\Temp\aha-build\20261028-single-instance-tray-01a181a5\release`，未覆盖用户原 EXE。OneFile 为 `portable\aha.exe`，Directory 为 `directory\aha\aha.exe`。

可入 Git 的白名单摘要：[源码流程](research/acceptance/source-r1.json)、[Directory 流程](research/acceptance/directory-r1.json)、[OneFile 流程](research/acceptance/onefile-r1.json)、[复制与别名](research/acceptance/copy-alias.json)、[Directory 材料](research/acceptance/directory-materials.json)、[OneFile CSV 对比](research/acceptance/onefile-materials.json)、[源码/打包输入指纹](research/acceptance/source-files.json)、[进程清理](research/acceptance/cleanup.json)、[完整代码复核](research/final-check.md)。最后核对本任务自有 aha/Chrome 进程为 0，Excel 进程为 0；未结束任何无关进程。

Excel 16.0 以只读打开两份 CSV，分别为 13×23 与 2×17；数据检查完成后 PowerShell COM 回收阶段超时，随后核对无 Excel 进程残留。该辅助脚本的退出问题单列保留，不混同为 aha 退出失败。Chrome A4 输出 PDF 为 1 页，实际 MediaBox 为 595.92×842.88pt；Poppler 1500px 渲染经主会话目视，无裁切。

## AC 对应

| 验收 | 结果 |
| --- | --- |
| AC1、AC2、AC3 | 通过：并发冷启动与复用、误关重开、同步去重、双资料与同浏览器 Cookie 隔离，补充复制 EXE/目录别名实测 |
| AC4 | 原生结构、Shell 图标、双击/键盘消息打开、重建与退出路径通过；实际鼠标展开菜单和点击仍未覆盖 |
| AC5、AC6 | 通过：页面/托盘消息退出，端口和描述符清理、锁释放、项目/原包保留；请求/同步清理与初始化退出竞态有回归 |
| AC7、AC8、AC9 | 自动检查与代码复核通过：崩溃/残留/坏格式/未知监听者恢复或拒绝、失败清理、认证与凭证边界、无托盘 CLI |

## 复核发现

- 启动器探测使用共同墙钟预算，拒绝非 aha 监听者和外部重定向；慢速分段响应不能延长等待。
- HTTP 线程创建失败需要清理未启动的线程与监听端口，已加入回归修复。
- 托盘刚建立时收到退出须锁存停止意图，不再发布运行描述符或打开页面，已补充该竞态回归。
- Windows 类型检查使用独立缓存，并修复 Unix 目录属性的静态平台分支；不改变 Store 核算、事务或文件发布语义。

## 交付与未完成项

2026-10-29，用户明确回复“提交，合并main，归档”，批准 [提交清单](commit-plan.md) 的一次性批次及本地合并、归档。工作提交为 `6fa4ee16658f389661e187f5f64732563331daae`；本地 main 从 `01b2c1e` 快进至该提交，包含已完成归档的本地用量台账三个继承提交，未推送远端。

归档前重新核对 40 个提交文件、29 个冻结的源码/打包输入、两种 Windows 成品 SHA-256 和上下文清单，全部一致；产品代码没有新增变更，因此沿用上述已通过门禁，没有重复运行全量测试。

本次按用户明确指令归档。AC4 的实际鼠标交互限制仍保留为未验收，未记为通过，也未把归档指令解释为用户已实际测试或明确豁免。任务归档状态记录本次交付收尾，不补造该项验收证据。
