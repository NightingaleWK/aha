# 执行计划：CCS 结构版本 26

## 启动门禁

- [x] 用户同意创建任务并继续规划。
- [x] 核查官方固定迁移、三张用量表和本机26必要字段。
- [x] PRD收敛；需求、设计和执行计划已落盘；配置implement/check规范与研究清单。
- [x] 向用户呈现最终规划摘要并取得随后明确实施批准：用户于2026-11-13回复“开始实施”。
- [x] 批准后执行 `python3 .trellis/scripts/task.py start .trellis/tasks/11-13-ccs-schema-26`；读取阶段2.1并按Codex自动模式使用Trellis实施/检查子代理。

## 实施顺序

1. 主会话：复核Git状态，按需创建 `codex/ccs-schema-26` 分支；读取开发前规范。新建任务隔离环境/资料目录时记录归属和收尾处理，不修改主解释器。
2. 实施代理所有权：domain白名单、来源/Store/HTTP/材料回归、原生验收脚本和中文片段；不改真实资料，其他代理的修改不得回退。
3. 将26加入显式外部集合；扩展现有23/24/25成功链至26，将未知负例改为27，确保缺字段、混合声明、失败暂存清理与历史保护仍实际验证。
4. 原生验收脚本真实执行26 SQLite/SQL成功、27失败及26恢复；scope描述与实际检查一致。
5. 主会话：更新README、CCS兼容规范、后端主契约/index及必要任务记录；新片段描述实际交付，版本由发布PR统一递增。
6. Trellis检查代理独立核对需求、设计、规范和变更，修复真实缺陷并报告验证；主会话完成集成。

## 源码检查

采用任务自有、满足SQLite门禁的Python解释器（下记 `<QA_PYTHON>`），分别保留日志与结果，实际参数按平台路径填写：

```text
<QA_PYTHON> -m unittest discover -s tests -v
<QA_PYTHON> -m ruff check src tests scripts
<QA_PYTHON> -m mypy src/aha --cache-dir <任务专用mypy缓存>
<QA_PYTHON> -m compileall -q src/aha
node --check src/aha/web/app.js
node --test tests/web_state.test.cjs
<QA_PYTHON> scripts/release.py validate --base <当次核实的validation-base> --ref WORKTREE
```

首先用 `test_sources/test_storage/test_http/test_evidence` 定位回归，修改收敛后完成规定检查；通过后不无故重复全套。变更原生脚本应同时覆盖 `test_release` 的脚本与报告约束。

## Windows成品与真实验收

1. 核对原生CPython、SQLite及固定构建依赖；优先使用与公开成品一致的运行时，记录来源和SHA。若不同，按合同安排全面本机验收；不得改全局运行时或放宽门禁。
2. 将构建与验证文件集中在有归属标记的 `%LOCALAPPDATA%\Temp\aha-ccs26-20261113`。私有profile/data-dir、报告与源码树分离。
3. 使用 `scripts/build_windows.py --build-root <任务根> --stage Directory`；实际运行 `scripts/verify_windows_artifact.py` 验证目录包，保留托盘（仅无桌面时显式no-tray）。
4. Directory通过后执行 `--stage OneFile --directory-verified` 并独立验证OneFile。两个检查分别留证26兼容、27失败/恢复、原包下载、复开与退出；适用专项单独记录。
5. 从Windows默认CCS只读投影到隔离台账验证26路径；不写原库或真实aha。如需要回归真实aha历史，只用一致副本并保护原目录。
6. 再次核实KnownFolder桌面与同名文件归属/占用，按合同保留旧版、交付单文件 `aha.exe`；从交付位置配合隔离资料启动并验证，核对交付副本SHA与验收产物一致。
7. 最后一次产品源码改变后重建对应成品；报告区分自动检查、物理托盘/Office及历史指纹相等，未执行项目不记通过。

## 收尾与回滚点

- 创建/修改源码前、首次构建前、交付覆盖前分别核对Git状态与成品依据。
- 不涉及应用库迁移，失败保留原台账和原包。桌面交付异常时退出本任务实例并恢复核实过的旧文件，不强杀未知进程。
- 保留verification与小型报告，按清单核对归属、符号链接和运行占用后删除自建合成库、额外环境及中间缓存，记录释放量和最终SHA。
- 按实际完成范围办理提交/归档/日志；桌面交付未完成不得宣布实施完成。
- 完成已授权实施和交付后核实最近公开Release及累计待发内容，提供建议版本、中文What’s New及验收缺口；集中引导“现在发版/积累到下一版/本次无需单独发版”，有缺口则首项为“先补齐发版条件”。无新发布授权不执行远端发布。
