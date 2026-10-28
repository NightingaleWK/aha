# 文档校准执行计划

## 实施前门槛

- [x] 用户同意新建任务并进入规划。
- [x] 核对源码、测试、spec、README、未归档任务和相关历史记录。
- [x] PRD 收敛：目标、范围、验收和边界完整，无阻塞业务决策。
- [x] prd/design/本计划及三份研究文档已形成。
- [x] 真实 implement/check JSONL 校验通过，各 3 条研究上下文。
- [x] 展示最新最终规划摘要，用户于 2026-10-27 回复“开始执行”，明确批准。
- [x] 批准后重查工作区与相关文件，JSONL 校验通过，`task.py start` 已进入 `in_progress`。

用户已批准最新规划摘要，以下执行项按实际结果更新；不扩大已批准的文档范围。

## 1. 规范整理（AC1、AC2）

- [x] 按 `research/spec-file-map.md` 填齐 backend 五份分题，中文整理索引和契约。
- [x] 填齐 frontend 五份分题及主要契约，数据边界按 JavaScript/HTTP 规则表达。
- [x] 删除 hooks 模板，适用内容归并到状态与组件规范。
- [x] 分题提供源码/测试入口、短例子、常见错误和验证方法，不重复整份业务契约。
- [x] 逐项核对来源、核算、占用、版本、迁移、幂等、原包、隐私和本机边界。

## 2. 指南与导航（AC3）

- [x] 三个 guides 使用 aha 链路、共享函数和检查实例，修正入口只校验一次的泛化规则。
- [x] 索引覆盖最终 17 份 spec，移除已删 hooks 文件的现行引用。
- [x] README 增加 spec 导航，按实际需要校准已有事实。

## 3. 初始化遗留工作（AC4）

- [x] 保留旧任务身份、目录、创建信息、`in_progress` 状态和初始化来源。
- [x] 更新中文目标、清单和说明元数据，说明此前部分契约和本次补齐关系。
- [x] 新增初始化 `verification.md`，逐项关联最终规范和实际检查后才勾选。
- [x] 保持未归档，写清完成情况和待用户验收的收尾条件。

## 4. 质量检查与交付（AC5、AC6）

- [x] 按 `research/documentation-checks.md` 检查占位、链接、索引、源码引用和契约一致性。
- [x] 复核变动范围，包含未跟踪文件；产品和历史记录与基线一致。
- [x] `git diff --check` 和当前 JSONL validate 通过。
- [x] 需要时派发 Trellis 检查代理，提示 Active task 路径和 check 上下文，禁止扩大产品实现。
- [x] 本任务 `verification.md` 按 AC1–AC6 写实际结果，区分本轮与历史证据。
- [x] 展示差异与初始化状态，不自行提交、归档或推送。

## 检查命令

```bash
python3 .trellis/scripts/task.py validate .trellis/tasks/10-27-spec-current-state-alignment
git diff --check
git diff --name-status 434c785
git status --short
```

占位/链接/路径检查用一次性 Python/rg。源码基线已验证 124 项测试、Ruff、mypy、compileall 和 JS 语法；无源码改动或新问题时不重复全套，不增写产品测试。

## 风险与回退点

- 中文整理可能遗漏契约细节：按 design 表核对签名、错误码、边界场景。
- 删除模板可能留下引用：全仓检索，改现行入口，保留历史归档记录。
- 初始化过早宣称完成：按交付及检查勾选，保持 `in_progress`，归档不在授权内。
- 发现产品问题先记录说明，不擅改实现。
- 只反向应用本任务差异，不 reset/clean 或删除其他会话和个人资料。

## 收尾授权与提交分组（2026-10-28）

用户已明确批准提交、推送和归档，覆盖当前任务及已完成的初始化任务，无需再次请求同一操作的许可。

1. 工作提交 `docs: 校准项目规范与初始化工作`：README、17 份最终 spec 及旧 hooks 模板删除、两项任务的文档/说明元数据。
2. 归档提交 `chore(task): archive spec alignment and bootstrap guidelines`：用 Trellis 归档两项任务，修复目录迁移后的 Markdown/JSONL/相关文件引用并复查。两项工作均无 PR，以真实分支信息配合 `--skip-branch-validation`，不伪造功能分支。
3. 会话日志提交：记录工作提交、检查与归档结果；之后将全部本次提交推送 `origin/main` 并核对远端和本地 HEAD。

归档使用 `--no-commit` 暂缓工具自动提交，以便相互引用的两项任务和路径修正进入同一条完整归档提交。没有产品代码变化，不重跑已通过的产品基线，只做必要的文档/上下文、范围和 Git 检查。原实施阶段的禁止自动提交/归档由本节显式授权扩展，其他边界保持。
