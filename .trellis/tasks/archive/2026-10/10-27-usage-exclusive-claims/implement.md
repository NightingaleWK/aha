> 实施批准：用户已于2026-10-27在更新后的完整方案后明确回复“开始实现”。下文规划阶段状态语句保留为决策过程；以本批准记录为准。

# 实施与验收计划

状态：实现、全范围检查、Windows成品验收及桌面交付完成；功能提交`1174db5`已保存。用户已确认归档、合并main并推送GitHub，按Trellis收尾流程记录。

## 所有权与顺序

一个贯通任务，不拆模块级子任务。已建立 feat/usage-exclusive-claims，基于 feat/codex-usage-evidence。

- storage implementer：storage.py、claims.py/迁移辅助、batches.py 及 storage/claims/batches/migration 测试；唯一 schema owner，先冻结门面。
- API/data implementer：analysis.py、server.py、必要 domain.py 共享纯函数及 HTTP/analysis 测试，不另建 claim 规则。
- UI/delivery implementer：web/**、evidence.py、版本号、README、必要构建调整及 evidence 测试；同时负责全局排版与产品文案，不改源读取/正式资料。API/data 与 storage 实现者按文案约定给出用户可理解的公共错误，code不变。
- 主会话：接口协调、隔离真实资料/Windows构建/browser/Excel/打印、规范及交付；auto 派发 trellis-check 全范围审查。

每次派发以 Active task: .trellis/tasks/10-27-usage-exclusive-claims 开头，按 JSONL→PRD→design→implement 读取，明确协作者并存、不得覆盖他人。依赖门面未冻结时串行推进，不猜接口。

## 执行清单

### 0. 规划与基线

- [x] 允许任务创建，用户确认剩余可用与有原因作废释放。
- [x] 核对旧代码/归档/正式库计数，持久化研究与界面依据落盘。
- [x] PRD收敛、设计和实施计划完成，准备 spec/research 上下文。
- [x] 用户追加全界面可读性与产品文案，合并 PRD/设计/研究；旧最终摘要不再作为本次实施批准依据。
- [x] 更新后的完整摘要已展示，用户明确批准实施；校验后进入 start。
- [x] 已加载 before-dev，建立新分支，派发实现代理并冻结持久化门面。

### 1. 占用、版本与迁移

- [x] schema2、control/claims/holds/events、protocol/generation、索引约束。
- [x] 唯一身份、覆盖、疑似重建规则及一致占用 snapshot；内部粒度冲突分组排除。
- [x] 原子保存/草稿修订/状态/撤回/作废/旧确认，幂等优先，失败原版保留。
- [x] v1备份/迁移/legacy_review，未知/损坏/故障回滚，不改旧包。
- [x] 两连接/两进程竞争、并发升级、旧真实SQL、作废后新owner取得再重试等关键测试。

### 2. 核算与 API

- [x] 唯一核算中 available/all、原匹配/排除/实际可用、精确金额与成员一致。
- [x] 新建/修订主体、claim_revision/generation/active_version，409可操作提示。
- [x] 专用修订预览不可被新建借用豁免；撤回/作废/resolve原因与幂等。
- [x] 历史/作废无写状态或修订；旧下载照常；失效与丢响应重试兼容。
- [x] 抢占、0可用、跨粒度、疑似重建、全部查看不可创建等测试。

### 3. 界面与证据

- [x] 统一排版变量，正文16/表格15/标签14/次要至少13及控件间距，清理响应式小字号覆盖，保留整体风格。
- [x] 三页/表单/空态/提示/弹窗文案审校，统一报销记录、修改、下载等业务词，去口号和助手旁白；必要口径集中按需帮助。
- [x] 可用/全部、排除原因与批次、零可用、刷新；移除仍然继续。
- [x] 唯一有效版操作、修订预览、撤回/作废原因、待核对处理、历史重下载。
- [x] 新 HTML/JSON 可用口径及有效依据，CSV实际成员；旧包SHA保持。
- [x] 真浏览器创建A→B剩余→修订→提交撤回→报销作废→释放重用，检查1440/1366/1280桌面、430窄窗口、长内容、计算字号及优化前后截图。

### 4. 检查与 Windows

- [x] trellis-check全范围，替换旧允许重叠测试，保留不相关89项基线保障。
- [x] Linux/原生Windows测试、Ruff、strict mypy、compileall、Node通过。
- [x] 自有隔离venv/构建目录，目录包验证后OneFile，不改系统执行策略或全局依赖。
- [x] 正式资料只读副本升级保留草稿/包，不将开发程序指向正式data-dir。
- [x] EXE/browser剩余范围、并发、作废、旧版、重启、退出端口释放。
- [x] Excel/打印与剩余金额一致，原包和原SQL指纹不变。

### 5. 规范与收尾

- [x] 真实spec与README升级说明同步，验收证据落盘。
- [x] 新桌面目录交付和SHA，不覆写旧成品/OneDrive/正式原件。
- [x] Phase3.4一次性确认及功能提交完成；归档和日志由Trellis收尾流程记录，main推送已另获用户明确授权。

## 检查命令

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m ruff check src tests scripts
.venv/bin/python -m mypy src/aha scripts/build_windows.py scripts/collect_licenses.py
.venv/bin/python -m compileall -q src/aha
node --check src/aha/web/app.js
python3 .trellis/scripts/task.py validate usage-exclusive-claims
```

Windows复用纯Python构建入口，实际版本/产物指纹和人工检查写 verification，构建成功不冒充业务验收。

## 回退

规划无产品修改。实施回退仅新源码/新发布目录；升级后恢复旧版需停止程序、恢复升级前应用库备份及配套资料，不自动降级正式资料或删除任何历史对象/原包。
