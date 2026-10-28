# 当前实现与文档盘点

日期：2026-10-27。只读基线：`main` / `434c785`，任务创建前干净。本文件描述规划时事实；最终文档结果由任务的 `verification.md` 记录。

## 证据与分析方法

当前源码与测试确定现有行为；README、两份业务契约和归档验证补充背景。历史验证不等于本轮重验，代码事实也不能代替新的业务决策。本次没有访问个人源库、应用资料或桌面成品。未发现可用 GitNexus/ABCoder 工具，采用源码、符号检索和测试核对。

## 文档缺口

| 范围 | 现状与证据 | 校准方向 |
| --- | --- | --- |
| backend 入口 | `backend/index.md:11` 说明其他文件仍为模板，`:30`–`:34` 五项 To fill，`:51` 要求英文 | 中文导航与真实开发前检查 |
| frontend 入口 | `frontend/index.md:11` 指出 React hooks 不适用，但 `:31`–`:36` 六项待填，`:53` 要求英文 | 按原生 DOM 应用组织 |
| backend 分题 | directory-structure、database-guidelines、error-handling、logging-guidelines、quality-guidelines 均含 To be filled | 实际模块、SQLite、AppError、运行输出和质量检查 |
| frontend 分题 | directory-structure、component-guidelines、hook-guidelines、state-management、type-safety、quality-guidelines 均为模板 | 五题落地；hooks 归并并删除 |
| 业务契约 | backend/usage-evidence-contract、frontend/local-web-contract 已覆盖 v0.2.0 | 保留业务语义并核对 |
| 跨层指南 | `guides/cross-layer-thinking-guide.md:66` 的入口只验一次会误导事务内重检；`:128` 后讨论 Trellis 自身模板 | 区分输入校验与权威检查，用 aha 链路替换 |
| 复用指南 | `guides/code-reuse-thinking-guide.md:65` 使用 TS，`:153` 引用不存在的 cli_adapter.py | 用实际领域函数、Store 和 DOM 举例 |
| README | `README.md:49`–`:88` 已有检查与构建说明，缺 spec 入口 | 补导航，业务说明只按需要校准 |

## 架构和规则证据

路径均相对仓库根，表中省略的源文件前缀为 `src/aha/`，测试前缀为 `tests/`。

| 领域 | 当前依据 | 规范要点 |
| --- | --- | --- |
| CLI 与运行 | `__main__.py:18`、`:26`、`:52`、`:69`；`server.py:469` | 独立 data-dir、本机端口、私有 runtime、所属运行退出清理 |
| 来源导入 | `sources.py:63`；`sql_dump.py:240`；`test_sources.py:296` | 只读备份含 WAL，SQL 只解析允许子集 |
| 数值日期 | `domain.py:97`、`:159`；`analysis.py:197`、`:217`、`:249`；`test_analysis.py:45` | Decimal 字符串、三种 token 语义、北京时间、不重算历史成本 |
| 归属 | `projects.py:46`、`:113`、`:154`；`test_projects.py` | 路径规范化、最长完整前缀、内容绑定覆盖、revision 失效 |
| 留存分享 | `archive.py:162`、`:233`；`test_storage.py:55`；`test_evidence.py:79` | 单 capture、允许字段投影、私有依据与分享范围分离 |
| 持久化 | `storage.py:49`、`:105`、`:145` | Store 门面、RLock 与 BEGIN IMMEDIATE、回滚、原子文件和原件校验 |
| 占用版本 | `claims.py:175`；`batches.py:400`、`:645`；`test_batches.py:70`、`:235` | 统一评估、同库独占、有效版、幂等、按所有者释放 |
| 并发故障 | `test_claim_concurrency.py:116`、`:130`、`:138`、`:151` | 多进程竞争、同请求同版本、提交失败保留旧版与原占用 |
| 迁移 | `migrations.py:55`、`:71`；`storage.py:339`；`test_migrations.py` | schema23 与 schema2 分开、验证备份、逐条 DDL、旧 writer 拒绝和保守 holds |
| 原证据包 | `evidence.py:85`、`:317`；`batches.py:763`；`test_evidence.py:35` | 四文件、BOM、公式保护/HTML 转义、精确合计、原 ZIP 校验下载 |
| HTTP | `server.py:43`、`:469`、`:531`、`:537`、`:564`、`:576`；`test_http.py:174` | 参数、Host/Origin/CSRF、端口 Cookie、安全错误 |
| 输出与历史 | `__main__.py:91`；`server.py:485`、`:499`；`batches.py:307`；`migrations.py:48` | 禁用默认访问日志/traceback；AHA_URL 是私有凭证输出；审计事件在库内 |
| DOM 与样式 | `web/app.js:16`、`:31`、`:40`、`:365`；`web/index.html`；`web/style.css:16`–`:35` | DOM/textContent、dialog、可见反馈、系统字体和现有字号 |
| 状态请求 | `web/app.js:4`、`:56`、`:85`、`:103`、`:134`、`:530`、`:562`、`:700`、`:730` | state/失效、run 串行、重试身份、修订主体、先保存后下载 |
| 数据边界 | `web/app.js:13`、`:476`、`:480`、`:541`；`server.py:43`、`:59`；`evidence.py:85` | 金额字符串、空与零不同、可选字段省略、前端辅助校验与后端强制规则 |
| 构建 | `scripts/build_windows.py:21`、`:40`、`:129`；`README.md:69` | Windows x64 隔离环境、先目录包再 OneFile，构建不能替代运行验收 |

## 未归档工作与历史证据

- `00-bootstrap-guidelines/task.json` 为 `in_progress`、docs、P1，初始化来源备注完整。
- 对应 `prd.md:24`–`:26` 三项均未勾选；清单仍有 ORM、hooks、TypeScript 等初始化提示。
- `.trellis/tasks/archive/2026-10/10-27-codex-usage-evidence/verification.md` 明确此前只补部分真实规范，未冒充初始化完成。
- `.trellis/tasks/archive/2026-10/10-27-usage-exclusive-claims/verification.md` 记录 v0.2.0 的原生 Windows、浏览器、迁移副本、Excel/打印验收，说明正式资料未迁移、当前进入试用。
- `.trellis/workspace/NightingaleWK/journal-1.md` 的两次会话与这些状态一致，历史记录保持原样。

## 本轮基线检查

使用现有 `.venv`，未安装或更新依赖。

| 范围 | 实测结果 |
| --- | --- |
| `.venv/bin/python -m unittest discover -s tests -q` | 124 项通过，10.505 秒 |
| `.venv/bin/python -m ruff check src tests scripts` | 通过 |
| `.venv/bin/python -m mypy src/aha` | 通过，15 source files |
| `.venv/bin/python -m compileall -q src/aha` | 通过 |
| JavaScript | Windows Node v26.12.1 从 WSL 按路径检查遇到 UNC package config 错误；改在 Windows 文件系统 cwd，以 `--input-type=commonjs --check` 从标准输入检查同一 app.js 后通过 |

Node 初次失败属于调用环境，不是已确认的产品语法缺陷。不要将个人 Node 安装路径写成项目要求。本轮未重建 EXE、未运行真实浏览器或 Excel/PDF 验收。

## 结论

需要补的是规范和工作记录，11 个模板不代表 11 个待开发功能。现有契约继续复用；重点防止模板误导、规则散落、重复维护，以及把历史验收写成本轮结论。本盘点没有新增产品能力或认定新的产品缺陷。
