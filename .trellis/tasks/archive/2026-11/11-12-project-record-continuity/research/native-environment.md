# 本任务原生环境与资料保护

- 2026-11-12 实测原生 CPython 3.12.16 x64 / SQLite 3.53.1，满足 WAL 修复门禁；Linux 系统 Python 3.14.4 / SQLite 3.46.1 不满足，未用于产品数据库检查，未放宽门禁。
- 任务环境 `C:\Users\djsyw\AppData\Local\Temp\aha-project-record-continuity-20261112`，含 task-ownership.json；qa312 是任务自有环境，无既有主 .venv 被替换。通过 run-native.py 捕获子进程真实输出/返回码，每次检查使用独立合成 profile。
- 实测包：PyInstaller 6.22.3、zstandard 0.25.0、Ruff 0.17.4、mypy 2.4.1、Playwright 1.65.1、pywin32 312、pypdf 7.0.1、PyMuPDF 1.26.7。固定构建依赖沿用 scripts/requirements-build.txt；QA 依赖不当成冻结产品运行时。
- mypy 的 SQLite 缓存不能放仓库 UNC 路径（该组合会产生 INTERNAL ERROR），使用任务原生 Windows 盘 cache，Linux/Windows/不同代理独立。检查环境问题不通过修改产品规避。
- 新完整 schema3 备份及旧桌面 EXE 已保护在 D 盘持久备份目录，依据与 SHA 见 [protection.json](protection.json)。保护采用提交版备份模块，不受开发中源码变动影响；真实资料只读。该持久恢复资料不纳入任务清理。
- 提交版恢复模块在独立任务目录还原该备份，schema3、42,220 条事实、5 项目、1,500 已归属及事实内容/费用/claims/版本/coverage 摘要与当前源一致，见 [real-copy-baseline.json](real-copy-baseline.json)。这只是恢复基线，不冒称 schema4 或关联恢复验收通过。
- Computer Use 插件已完整阅读指导/确认规则。当前初始化、重试、reset 后重试都在发出输入前被宿主拒绝：`sandboxCwd is not a local file URI: file:///home/wangkai/code/aha`。未发出桌面输入，不能据此声称物理托盘点击或 Office UI 操作通过。实际浏览器和材料检查使用原生 Edge Playwright / Office COM / A4 PDF，并分别说明范围。
- 最终门禁、真实修复和桌面验收完成后，qa312/构建物/缓存及任务验证副本已统一清理；保留基础原生解释器、真实默认库、D盘持久恢复包和桌面单文件成品。原验收报告的临时路径由retained-evidence.json映射到D盘小型验收材料；报告字节本身未被回写。清理后已从实际桌面重开同一默认服务，程序不依赖被删除的QA环境。
- 最后一次全库快照断言遇到正常启动同步新增559条，改为对修复后备份的原42,220行逐键核对事实/版本/关系，确认旧范围完全保留；没有修改产品适应静态数量假设。额外只读审计目录使用独立TemporaryDirectory并已删除，最终证据见final-native-state.json。
