# 实施与验收计划

## 开始条件

- [x] 用户批准创建任务和规划。
- [x] 当前来源、历史兼容与上游迁移已完成只读研究。
- [x] PRD 已收敛，design 与 implement/check JSONL 已准备。
- [x] 向用户展示最终方案；2026-11-02 用户回复“可以，继续吧”，明确批准实施及成品交付。
- [x] 加载 phase 1.4 后 task.py start；实施前加载适用规范与 phase 2.1。
- [x] 创建 `codex/ccs-schema-compatibility` 分支，保持既有用户改动。

## 1. 实施与检查

- [x] trellis-implement 负责 sources/sql_dump/domain/sync/queries/evidence、版本元数据及相应回归测试；以本方案约束为准，变更面只限确有必要的文件。
- [x] 共享外部支持集合 23/24、真实版本记录；内部历史投影仍 23，应用 schema3 与指纹不变。
- [x] 修正不兼容错误与 README/规范的版本含义，明确导出旧字段的兼容作用域。
- [x] 补充有意义的回归：23/24 SQLite 与 SQL、缺失/混合/伪造/未知版本、缺表缺列、23→24 同内容去重、失败原子性/旧成功时间、真实源版本记录、内部投影兼容、旧冻结包不变与新材料版本标注。
- [x] trellis-check 独立覆盖任务全范围并修复问题；主会话检查最终 diff、规格和验收证据。

## 2. 自动验证

复用主开发环境；运行时不合门禁时才准备任务自有隔离环境。Windows 检查独立 mypy cache。

```text
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m ruff check src tests scripts
.venv/bin/python -m mypy src/aha
.venv/bin/python -m compileall -q src/aha
```

- [x] Linux 完整测试、Ruff、strict mypy、compileall。
- [x] Windows 隔离解释器运行完整测试与适用检查（包括新来源回归），检查实际 SQLite WAL 修复门禁。
- [x] 新 HTTP 同步结果和真实浏览器验证；先同步23再同步24同内容，失败后仍能查询原台账。
- [x] 通过合成夹具检查项目/归属、占用、保存下载、版本与原包 SHA；真实用户当前无报销包，不能把该事实当成冻结回归已通过。

## 3. 原生来源与旧资料副本

- [x] 真实 CCS 只读投影写入隔离 aha 资料，独立比较允许投影记录数、逐行内容和精确 Token/费用；源变化按同一受控观察点比较，分别记录来源读取与发布耗时。
- [x] 使用 Windows 原生 SQLite backup 创建用户 aha 一致副本；同步写入副本，比较原项目配置、既有事实/版本/归属，观察新增与合法修订，不自动处理核对事项。
- [x] 对比源版本/表结构/日志模式及用户默认资料的必要指纹，证明本任务未写入真实资料；活 CCS 可自然增长，不把自然变化误写为本任务修改。

## 4. Windows 成品交付

- [x] 任务自有构建根、合成资料和环境集中放置（建议 Windows TEMP 下 `aha-ccs-schema-compatibility-*`）；建立路径归属清单，不沿用旧任务环境。
- [x] 选择符合门禁的原生 Windows x64 隔离解释器；使用既有 `scripts/build_windows.py` 构建 Directory。
- [x] Directory 原生 EXE + HTTP/浏览器验证 23/24 同步、查询、保存/下载、退出、重复打开；材料按规范验证 CSV Excel 和 HTML A4 打印。
- [x] Directory 实际通过后使用同脚本 OneFile / --directory-verified 构建，再独立运行验收。
- [x] 重新从系统接口确认桌面，识别同名旧文件及占用。复制为实际桌面 `aha.exe`，记录最终源码依据、SHA256、运行时与产物一致性。
- [x] 从桌面副本用隔离合成 --data-dir 启动，验证同步、查询、保存/下载、原包重下、关页重开、退出与 descriptor/端口清理；默认保留托盘，物理点击与模拟消息证据分开。

构建入口：

```text
<Windows venv>\Scripts\python.exe scripts/build_windows.py --build-root <任务根> --stage Directory
<Windows venv>\Scripts\python.exe scripts/build_windows.py --build-root <同任务根> --stage OneFile --directory-verified
<实际桌面>\aha.exe --data-dir <独立合成目录> --no-browser
```

## 5. 收尾与回退点

- [x] 主会话更新来源兼容/版本区分相关 spec，不改无关工作流。
- [x] 保留必要的小型验收报告、指纹和复现方法；真实副本/源投影不进 Git。
- [x] 核实进程占用、路径归属与符号链接边界后，逐项清理本任务合成库、额外环境、构建中间物/缓存；保留源码、主环境、真实资料、必要记录和最终桌面成品。 已清理 530.4MiB，见 verification.md / cleanup.json。
- [x] Git 提交清单集中确认：2026-11-02 用户回复“执行”，批准工作提交、任务归档与 journal；按批准清单完成本地收尾。
- [x] 已报告成品、启动方法、验证和清理结果。提交前再次核对：程序现位于 D:\Program Files\aha-0.6.0\aha.exe，正在运行，SHA 与本轮0.3.1成品相同；不恢复已移走的桌面副本。

回退点：实现失败仅撤回本任务改动；隔离验收失败保留诊断并修复；无已验证 OneFile 时不替换桌面成品。用户默认 aha 数据库始终不是本任务的写入目标。
