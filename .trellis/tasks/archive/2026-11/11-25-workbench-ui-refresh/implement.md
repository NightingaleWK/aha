# 实施与验收

1. 在 Trellis 规划审阅通过后激活任务。实现代理加载两层 spec 及趋势研究，在当前任务工作区内实现。以用户已选择的工作台原型作为视觉目标。
2. 对接只读趋势统计及按日表局部日期参数。直接复用 SQLite 投影、精确聚合、范围解析、事务校验和游标身份。新增覆盖分页以上的多项目多模型夹具、日／月／年、部分日、状态和 revision。
3. 整理 `index.html`、`style.css` 和 `app.js` 的三页结构与对应文案。保留 DOM 现有事件入口，接入趋势、用量明细和报销侧栏的请求生命周期。紧凑列表后验证原有目录、批次和版本动作。
4. 集中核对前端反馈。用现有 Node 可控请求夹具补迟到成功、409、断连、保存失效和日期局部分页回归。用真实 Chrome 对照工作台原型与任务验收，覆盖系统减少动效、键盘及焦点、窄窗口、长名称和金额。用 Windows 与 WSL 合成资料验证同步终态及应用行为。
5. 由检查代理复核实际代码、DOM 与合同。执行以下仓库检查，Python 使用任务自有环境，缓存和样例使用任务目录。

   ```text
   python -m unittest discover -s tests -v
   python -m ruff check src tests scripts
   python -m mypy src/aha
   python -m compileall -q src/aha
   node --check src/aha/web/app.js
   node --check src/aha/web/form-controls.js
   node --check src/aha/web/time-range-picker.js
   node --test tests/web_state.test.cjs
   python scripts/release.py validate --base v0.7.0 --ref WORKTREE
   ```

6. 复核已有时间、HTTP、组件和视觉规范，更新与最终实现有关的约定及中文 What’s New 片段。发版工具负责版本号。验收报告按真实执行范围记录。
7. 使用原生 Windows x64 与通过 SQLite 门禁的隔离环境构建。先运行 `scripts/build_windows.py --stage Directory` 并验收实际 HTTP、页面、主业务、材料和退出，再使用 `--stage OneFile --directory-verified` 构建并独立验收。通过系统接口解析桌面位置，核实同名文件的归属及占用，按交付规范放置最终 EXE。从桌面实际启动隔离台账并核对 SHA-256、主流程、退出及描述符。
8. 保留小型验收记录和最终成品，按确认名单清理合成资料、临时环境及中间物。源代码、规范和任务收尾按仓库流程执行。给出相对最近公开版的累计范围、What’s New、建议版本及实际验收缺口，集中获取公开发布选择。

## 回归重点

验证同步后分析失效、图表和用量来自一致的选区、日柱局部范围、旧回包、已保存重下、侧栏与冲突弹窗的焦点层级、已关闭弹窗的操作反馈以及真实页面可用性。分别记录源码浏览器、Directory、OneFile 与桌面副本的证据。涉及材料渲染、托盘或构建环境变化时，按发布合同追加相应专项。

回滚以同一提交边界撤回首页资源及只读接口，已冻结材料使用原版本下载。旧桌面副本按现有交付流程保留可恢复依据。
