# 实施计划

1. 产品开发由 Trellis 实现代理按所有权并行修改。后端新增分页、详情和批量接口，复用单笔核对的事实、审核和重算逻辑，覆盖接口与业务回归。前端在现有核对弹窗实现筛选、翻页、跨页选择、批量确认和单笔展开，覆盖迟到、失败、重试与无障碍状态。
2. 主会话准备任务专用验证运行时及隔离合成资料，记录现有实现的工作量，测量万级待办和约 6.5 万明细场景。实际进行 100 条和更大批次，验证结果、重算次数、兼容历史和已报销原包。
3. 执行 Trellis 质量复核。运行适用的 Python unittest、Ruff、strict mypy、compileall、JS 语法、Node 状态测试、git diff --check 和真实浏览器交互。核对同秒不同原生事件、说明、精确金额、选择过期、重试与占用。
4. 更新后端用量证据与前端本机接口、状态等合同，编写中文 What’s New 片段。复核范围与仓库差异，提交本地 Git。
5. 用系统确认的 Windows x64 隔离解释器和任务自有构建目录，从最终源码构建 Directory 并完成原生隔离验收，通过后构建 OneFile。验收 OneFile，确定实际桌面及旧 aha.exe 归属，保留可回退副本，交付 SHA 相同的单文件并从桌面再次验证。记录每阶段验收、源码与哈希。
6. 关闭任务进程，盘点项目根目录和任务临时目录，清理本任务合成数据和可重建环境，保留验收证据与成品。完成归档和 journal，给出当前公开基线、累计变化与发版建议。

## 验证入口

- `python -m unittest discover -s tests`（通过 SQLite 门禁的环境，按 CI 入口）
- `python -m ruff check src tests scripts`、`python -m mypy --strict src/aha`、`python -m compileall`
- `node --test tests/web_state.test.cjs` 及修改的 JS 语法检查
- `python scripts/build_windows.py --build-root <任务自有目录> --stage Directory`
- `python scripts/verify_windows_artifact.py --exe <Directory 或 OneFile> --source-root <源码> --data-root <验收目录> --report <回执>`
- `python scripts/build_windows.py --build-root <任务自有目录> --stage OneFile --directory-verified`
- 合成浏览器核对筛选、跨页全选、成功和冲突处理。验证用真实 Windows 桌面副本的安全本机入口，复开、原包和退出。

## 变更边界与回退依据

- 后端 `ledger.py` 和新核对查询/批量模块负责确定证据、执行和统计；`storage.py` 和 `server.py` 负责门面和 HTTP。单笔核对原有测试继续覆盖全部类型。
- 前端 `web/app.js`、`web/index.html`、`web/style.css` 负责交互和页面。保持可回滚的程序副本，schema 版本沿用现有版本。
- 任何写入验证均使用任务自有资料。验收源码 SHA、Windows 运行时、产物 SHA 和已实际执行的检查写入任务记录。

## 确认说明补充

遍历交互表单，复用人工确认说明的默认值。检查静态和动态字段、编辑与清空、确认后的请求及从最终桌面文件启动。变更完成后刷新中文发布片段，从最终源码重新构建并验证两种成品。

## 原生配对时间补充

确认历史核对可同时使用持久原生事件秒和已配对快照秒。使用截图中那一项的只读证据确认根因，测试使用独立合成资料，并验证无配对、配对冲突、同计数独立事件、项目及报销守卫。检验翻页和批量预览的成本，更新证据契约和中文片段后重建、验收并交付桌面副本。

## 候选依据优先补充

后端实现核对资格、预览成本、已核实事实投影及复读，覆盖截图形态、日期边界、归属和冻结原包。前端使用现有批量表单展示采用候选的数量和金额变化。复核合并后的接口、归属、报销、可用统计、复读和一次重算，再执行原生 Directory 和 OneFile 浏览器检查与桌面交付。
