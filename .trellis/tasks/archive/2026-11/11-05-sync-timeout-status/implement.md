# 实施计划

## 阶段门禁

- [x] 用户明确同意建立修复任务、进入规划。
- [x] PRD、设计、实施计划及子代理上下文清单已准备。
- [x] 用户在最终方案摘要之后回复“开始实施”（2026-11-05），已批准本方案。

## 执行顺序

1. 批准后核对 Git，建立 `codex/sync-timeout-status` 分支，设置任务 branch，运行 `task.py start`。
2. 加载 Phase 2.1 详细指令，使用 `gpt-6.1-terra` / `max` 的 Trellis implement 子代理；原生上下文注入优先，缺失则在子代理按清单读取。派发首行使用 `Active task: .trellis/tasks/11-05-sync-timeout-status`。主代理负责规划、规范、Git、交付与收尾；产品/回归/中文片段由实施代理负责，避免重叠编辑。
3. 实施 D1/D2，优先保持 `sources.scan_sqlite` 协议，增加流式临时投影及独立本地预算，保证最后批次和取消检查覆盖完整。风险文件为 `src/aha/sync.py`、必要时 `sources.py/storage.py`。
4. 实施 D3，修正 `src/aha/web/app.js` 的来源卡、初始化与重试状态；使用现有 `last_attempt`/job 形状，必要时增加少量页面样式或文案。
5. 为真实回归补充 tests：源事务释放/并发写、慢处理超旧预算、真正源超时、本地超时、双取消信号、临时写入和回放错误、旧状态/原包不变；页面测试覆盖有/无历史失败、运行中、需要核对、成功恢复、刷新以及错误原因显示。不要只断言实现字符串。
6. 增加 `.release/changes/sync-timeout-status.json` 中文 fix 片段，内容以最终行为为准；产品版本保持单一来源且本任务不手工递增。
7. 加载 Phase 2.2 并派发独立 Trellis check 子代理（同模型/强度），覆盖最终范围、自修复后重跑受影响检查；主代理复核差异、证据与跨层行为。
8. 更新数据库、用量证据、错误处理和前端状态等受影响规范，保留来源一致性/锁预算的唯一权威定义；将精确预算、错误语义和清理要求与代码同步。
9. 完成本机成品流程及清理，复核最终源码与最终 EXE 一致；再按当前提交/归档规则收尾，给出真实发版评估。远端发布另外集中确认。

## 自动检查

按环境实际可用解释器执行，不放宽 SQLite 门禁；保留主 `.venv`。

```text
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m ruff check src tests scripts
.venv/bin/python -m mypy src/aha
.venv/bin/python -m compileall -q src/aha
node --check src/aha/web/app.js
node --test tests/*.test.cjs
python scripts/release.py validate --ref WORKTREE --base main
```

定向调试优先 test_sources/test_storage/test_http 与页面状态；最终依变更运行质量门禁，检查通过后不无依据重复。测试使用合成夹具和独立目录；原始个人数据、凭据和完整日志不入 Git。

## 原生 Windows 与桌面交付

- [x] 核实当前 Windows 构建环境与最近公开版构建信息；使用任务自有隔离 venv、固定依赖和通过门禁的 SQLite。环境若变化则执行额外托盘/Office/打印等全面专项并如实记录。
- [x] 在任务自有目录生成至少 30,000 条合成明细及少量日汇总/价格，验证当前规模成功同步、重复同步、关键数量/金额/Token 及分段耗时；额外用确定性慢处理回归证明超旧限时可成功。
- [x] 真实浏览器验证失败状态、旧资料可查、刷新/重试/成功恢复及窄屏可读；WSL 预览使用当次验证的本机 HTTP，queued 只说明排队。
- [x] `scripts/build_windows.py --stage Directory` → `scripts/verify_windows_artifact.py`；补本次同步相关原生业务验收。
- [x] Directory 通过后 `--stage OneFile --directory-verified` → 独立原生自动验收。
- [x] 查询 Windows 实际桌面，核实旧 `aha.exe` 来源和占用，保留必要恢复副本；交付新单文件并核对 SHA256。
- [x] 从桌面副本用独立合成 data-dir 再次启动，检查同步、页面、材料、复开及退出/描述符清理，不触发真实台账验收。
- [x] 保存源码依据、SHA256、运行时、检查范围、规模耗时及必要小型证据到任务 verification；产品最后修改后重建成品。
- [x] 逐项核实并清理本任务额外环境、合成大库、临时快照、构建中间物和缓存；保留源码、主环境、真实资料、验收记录、旧版恢复副本及最终 EXE。

## 停止/回滚条件

- 若发现两阶段实现破坏身份/金额/旧材料、需要 schema 迁移或改变核对业务行为，返回规划更新设计，不以放宽测试绕过。
- 构建/原生验收失败时保留已识别旧桌面程序；不得以源码通过替代成品交付或公开发版。
- 无需回滚真实资料，因为实施与验收均不写真实台账或源库。提交与发布以各自授权范围执行。

## 发版评估（交付后填写）

已核实最近公开v0.4.0，累计待发用户变化为本次同步修复；建议补丁v0.4.1。实际What’s New、公开发布剩余条件与待选项见 research/commit-plan.md；本机交付完成不代表已公开发布，用户已选择补齐发版条件；开始必要本地提交、回执和PR/CI，正式公开发布仍待最终确认。
