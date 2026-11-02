# 实施、原生验收与交付记录

日期：2026-11-02。用户已批准实施与桌面单文件交付。工作分支 `codex/ccs-schema-compatibility`，基线 `f98df67`。用户在交付与清理完成后回复“执行”，已批准按提交清单完成本地 Git 提交、归档与 journal。

## 成品与源码依据

- 产品版本 0.3.1；支持外部 CCS 23、24，内部投影仍 23、应用 schema3、材料 manifest4。
- 最终产品源码指纹 `f02947a38d7b3ccb893ab5387a79d6be3eee497c15b23e7a30b0fa03a345e6f5`；覆盖 `git ls-files src scripts pyproject.toml` 的 38 个文件，算法见 [独立检查](research/check-report.md)。构建前、后与交付时一致；其后只更新说明与验收记录。
- Windows Directory SHA256：`2e6f103e42d3bbfb9466de260d816b42906f86d388b277e502bc5686e14861e7`。
- Windows OneFile / 实际桌面副本 SHA256：`d709f7306a926a76351c1d6fa4892c87e25484e74e84657da5cbefd7c86589ea`，11,745,593 字节。
- 系统桌面接口 `SHGetFolderPathW(CSIDL_DESKTOPDIRECTORY)` 确认交付位置 `C:\Users\djsyw\Desktop\aha.exe`；复制前无同名文件、无运行中的 aha。复制后 SHA 与验收 OneFile 相同，并实际从该桌面路径启动验证。
- 使用既有 `scripts/build_windows.py`；Directory 实际通过后才加 `--directory-verified` 构建 OneFile。原生 Windows x64 隔离 Python 3.15.2、SQLite 3.53.4、PyInstaller 6.22.3、zstandard 0.25.0；没有修改系统 Python/SQLite 或主 .venv。

## 自动检查与独立复核

- Linux 完整 unittest：211 项，OK，跳过 2 项 Windows 原生限定用例；29.650 秒。隔离 Debian SQLite 3.53.4 库，官方包 SHA 已验证，未放宽 WAL 门禁。
- Windows 完整 unittest：211 项，OK，跳过 1 项平台权限限定用例；73.780 秒。原生托盘结构、消息、重建和关闭用例通过。
- 双平台 Ruff、strict mypy（22 模块）及 compileall 通过；`git diff --check` 通过。独立 trellis-check 未发现需改产品的阻断问题。
- 新回归覆盖 23/24 SQLite 与 SQL、未知/混合/伪造版本声明、缺表缺列、23→24 指纹/身份/归属/占用/原包不变、SQL 暂存失败回滚、旧成功时间、HTTP 实际源版本与旧历史未知态、材料版本作用域。
- 现行规范新增 [CCS 来源兼容](../../../../spec/backend/ccs-source-compatibility.md)，同步 index/database/主契约；独立规范复核后收紧失败/旧 run 可缺版本字段的说明，未改产品代码。

## 真实来源与旧资料副本

- Windows 原生只读同步当前真实 CCS24 至隔离 Store：21,513 条明细、117 条日汇总、8 条价格依据，completed，28.978 秒。该轮 scan 允许投影在 sink 边界被验收脚本观察；独立归一每条身份/内容、fresh/output/read/creation/total Token 和 Decimal 金额，与保存的每条版本及事实逐一相同。没有将两种粒度金额简单相加。
- 原生 SQLite backup 创建用户 aha 一致副本，只对副本同步：原 19,713 条事实和对应版本全部保留，4 个项目和原归属逐条相同；新增 4,317 条，修订 0，最终 24,030 条、pending0，completed。新增包含原本地未覆盖的来源历史，不把全部新增解释成当日新消费。
- 原用户 aha 主库 SHA256 前后保持 `b02f5f957fe32cf8e704d6bfbedcbbdfc24cbf4b12cecddf84065feaa76ef8ed`。真实 CCS 始终 mode=ro/query_only，结构版本与日志模式未改；活源可自然增长，不能以文件整体 hash 断言其未自然变化。
- 最终 OneFile 又直接读取真实 CCS24，写入另一隔离资料目录：21,562 条明细、117 条日汇总、8 条价格，completed、pending0，原用户库仍未变。一次读取为 source_busy；重新启动后的有限检查记录一次 source_busy、一次明确手动重试成功，整段 36.539 秒。保留既有 5 秒来源事务预算，未把失败写为成功；用户遇到“来源忙”时可稍后点“立即同步”重试。本轮没有承诺冷读或并发忙碌时首次同步必成功。

## Directory / OneFile / 实际桌面副本

三个成品位置分别执行 8 组真实 Edge 浏览器流程，均无页面运行错误和服务端500。使用独立合成用户目录、独立 --data-dir，保留默认托盘；浏览器为 Edge156.0.4314.58、zh-CN、America/Los_Angeles。60 条合成明细，金额 11.400000060 USD、总 Token6300，没有会话 ID，不扫描个人会话。

1. 启动自动同步 CCS24，界面显示 v0.3.1、本地60条。
2. 同一合成源改为23再改为24并手动同步，实际版本准确，新事实0、版本/内容不增长。
3. 通过实际文件输入导入 SQL24，仍为60条。
4. 通过数据来源表单读合成25，显示实际25与支持23、24，保留60条和最近成功时间；随后恢复24。
5. 实际页面填写用途并保存下载，产生一个60成员冻结批次，材料版本/Decimal金额/Token/文件 SHA 全部核对。
6. 重复启动同一路径 EXE 复用同一 PID/run_id，不追加启动同步；关页重开仍为同一服务。
7. 完全退出后重启，原事实/占用/批次仍在，原 ZIP 重下载 SHA 相同。
8. 页面退出后 runtime.json 删除；原生驱动另核对已关闭端口和进程。OneFile 父/子 bootloader 不误判为两个服务。

Directory 的7个打包 web 文件与源码逐字节 SHA 一致；OneFile 与桌面副本还对6个实际 HTTP 页面/资源逐字节比较，licenses 返回200。桌面副本最终与 OneFile SHA 一致。

物理托盘点击未执行；Windows 原生消息/结构测试和默认启用托盘的 EXE 启动/完整退出已执行，不将它们写成物理点击证据。桌面自动化入口因 WSL cwd 无法初始化，浏览器使用现有 Edge + bundled Playwright 的独立配置；未操作日常浏览器资料。

## 办公软件与打印

- Directory 与 OneFile 各自生成材料，各以 Excel16.0/build20527 原生文本导入器明确使用 UTF-8、逗号分隔读取 CSV：60行，中文模型、+08:00 时间、11.400000060USD 和6300Token 正确，关闭时未保存。早期 OpenText 调用未应用分隔参数，改为明确 QueryTable 文本导入；没有改 CSV、产品或系统区域设置，不声称自然双击 CSV 的分隔行为已验证。
- Directory 与 OneFile 费用 HTML 各经 Edge 实际 print-to-PDF，均为1页 A4；PDF尺寸、文本和精确数值核对通过，逐页渲染人工检查，无截断。未进行纸质打印。
- 桌面副本独立完成保存、下载及材料 JSON/CSV/文件校验；其 EXE 与 OneFile 完全相同，不重复宣称额外 Excel/打印验收。

## 验收脚本修正与证据边界

Windows 最初两轮验证命令分别缺仓库导入路径/仓库工作目录；纠正原生测试调用后完整211项通过。浏览器驱动改为绑定本次 POST 返回的 job_id 后再等终态，避免读到上一次成功；真实来源驱动使用 closing(Store) 关闭资源；PDF金额按 Decimal 等值比较，保留合法尾零归一。上述均为验收驱动修正，未修改产品迁就夹具。

必要证据位于 `C:\Users\djsyw\.codex\visualizations\2026\11\02\01a199ff-0ba7-7b12-afb4-3db989063674\ccs-schema-qa`：双平台最终日志、构建运行时/指纹/桌面交付回执、三处 browser/database/material check、合成ZIP与截图、两份Excel/PDF记录，以及无逐条个人数据的真实源/副本检查摘要。真实来源副本、运行凭证和构建中间物不进Git。

## 清理与 AC 状态

AC1–AC5 已通过。任务自有 Windows/Linux 环境、合成库/验收副本、构建中间物及已核实的编译轮缓存已清理，文件逻辑大小合计 556,173,144 字节（530.4MiB），Windows 7,861 个任务文件；结果见证据区 cleanup.json。删除前已核对进程、runtime、路径归属和链接边界；保留最终桌面成品、主开发环境、用户原库和必要小型验收记录。本地 Git 收尾已获用户“执行”授权；工作提交为 `fa4ec9327592ccb48b27ed3c744d0751b44dd0df`，按批准流程归档并记录 journal；无远端推送。

## 交付后的路径核对

2026-11-02 11:00（北京时间）提交前复核：原桌面 aha.exe 已不在，运行中的 OneFile 位于 `D:\Program Files\aha-0.6.0\aha.exe`。该文件仍为11,745,593字节，SHA256与本轮0.3.1成品完全相同；目录名不作为产品版本依据。保留当前位置与正在运行的用户实例，不重新创建桌面副本或干预真实服务。
