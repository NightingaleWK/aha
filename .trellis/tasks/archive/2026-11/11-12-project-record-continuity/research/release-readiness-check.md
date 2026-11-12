# v0.5.0 发布前只读复核

复核时间：2026-11-12 15:42，北京时间。角色：独立 trellis-check。只读取源码、Git 对象、规范与已有验收记录；本轮唯一写入为本报告，没有修改产品/测试/门禁、操作远端或打开真实业务库。

## 结论

**可以继续已授权的功能合入、发布 PR 和候选构建；当前证据尚不能直接公开 v0.5.0。** 未发现新增阻塞性源码问题。缺口是新生产运行时的适用验收与正式候选身份绑定，而不是发布授权。用户已经明确授权现在发版、合并 main、push、收尾和归档，并确认自己的功能实测正常；不应重复请求同一授权。

本轮使用固定源码 `da826a723b81e76f805e3d8e13e0679dff9bbddf`。公开基线沿用主会话本轮 GitHub 只读核对结果：v0.4.1，源码 `8898451cde00956d32edd0585b8b68690ea3307d`。本子代理没有重新查询 GitHub，真实 PR、仓库设置、Actions 状态和公开资产仍由主会话核验。

## 累计变化与候选版本

相对 v0.4.1，发布脚本实际枚举到四个新增中文片段，和两个产品 `feat:` 提交的最终行为相符：

| 片段 | 用户可观察变化 |
| --- | --- |
| ccs25-compatibility | 读取 CCS 23/24/25 与 SQL25，保留严格结构校验和实际来源版本 |
| device-data-continuity | 换机来源明确接续，保存旧事实/目录依据，完善核对和全历史查看 |
| full-backup-restore | 完整台账备份、独立目录还原，保留归属/核对/占用/各版本原包 |
| project-record-continuity | 持久逐笔关系、持续会话默认、历史依据恢复、跨页待归属处理、项目费用及冻结覆盖说明 |

新增完整备份和归属工作清单属于功能变化，**v0.5.0 是适当候选**；不能按最后一个修复单独形成 0.4.2。当前源码和桌面本地成品仍为 0.4.1，正式版本应由可信 Release Please 发布 PR 统一生成。累计预览 `whats-new-preview.md` 没有漏掉上述片段，也没有将尚待确认的消费冒称全部分配完。

升级说明已明确 schema3→4 前完整回退备份、旧程序不能打开新库、旧完整备份仍能在新目录恢复；多候选/无依据及日汇总保持待办。真实修复的 37,165 条不能写成所有用户的固定恢复数量；本次仍有 3,438 明细和 110 行参与统计的日汇总待确认，不是发布失败，也不是全部归属完成。

## 源码、构建与正式提交的绑定

对固定提交重算 `scripts.release.fingerprints`，结果与构建前及构建后的留档完全相同：

| 范围 | SHA256 |
| --- | --- |
| full | `710753fd2f5b8e8dea4562d2f8c59c6f7551e1f69ded1aaff2965865a46413a1` |
| tray | `0422a08425df526bf10bff636f345a5b5ffb19683f11ca72a87486cd797ffbbd` |
| materials | `48bcab624b49fc104f08a67ed50f006d735a3373e01eeaf7a60a69119f586857` |
| recipe | `bc1b83967159c74e11c8372ca9a5c8d596efb345a05735ef944f0d7f613402df` |

另外将 `product-file-sha256.json` 的 39 个产品/构建文件逐个与该提交的 Git blob 比较，**全部逐字节相同**；当前 WORKTREE 的四组指纹也相同。这足以将此前按工作树执行的本机检查追溯到现已提交的同一份源码。无需为纯任务归档或日志提交重建产品。不能把检查时间改写成提交时间，或把该功能提交冒称未来正式发布 merge SHA。

已有本地 Directory SHA 为 `c9934c01f2f41bef9c329c8439a7bf0cc33de1623928a1dcadd1e726d3e739ae`；OneFile/桌面副本 SHA 为 `9ccd827d1dc4edbbda8b4a8bf30abe3867143950b828a7ffc5217c97e334e97a`。这些是本机 0.4.1 标识、Python 3.12.16 的已验收字节，不能改名充当正式 0.5.0 资产。

发布 PR 合并后必须记录独立的 M，按 M 构建与生成说明，标签也指向 M。只改权威版本数字会被专项指纹规范化；若其他产品内容变化，重新判断对应证据。人工回执可以随后合入可信 main，再恢复同一候选 M 和同一份资产，不能把新 main 混入 M。v0.5.0 并非首次公开版本，门禁不强制重走首次版本专有的 candidate_source_sha/artifact_sha256 字段要求；仍应记录所测产物与实际运行时，并独立核对最终下载字节。

## 旧回执可复用范围与实际缺口

读取 `.release/acceptance/` 的三份回执并以发布脚本验证其源码身份成功。旧正式 `v0.4.0-first-cloud.json` 的完整记录真实存在，包括用户物理托盘操作；本轮不能否认那次已完成的检查。

但当前 full、tray、materials 均已变化，只有 recipe 与旧回执一致。`required_checks(当前提交, v0.4.1)` 的实际结果是 **directory / onefile / browser / tray / excel / print 全六项**，不仅是材料专项：新增 associations、project_links、backup、source_bindings 等生产模块使现有保守策略要求全面检查。即便传入旧回执相同的 runtime 摘要，`acceptance_missing` 仍返回全六项。因此本轮不存在可用旧正式托盘回执直接放行的分支，也不应修改门禁以回避这次失效。

| 已有记录 | 能证明的范围 | 对新正式候选的作用 |
| --- | --- | --- |
| python-final / node-final / final-code-review | 原生 3.12.16、SQLite 3.53.1 的 351 Python、Ruff、26 源文件 strict mypy、compileall、53 Node 状态回归及语义审查 | 可追溯到当前提交；正式 3.15.2 CI 仍须运行，不能冒称已测新运行时 |
| directory/onefile/desktop-verification | 各真实 EXE 的 HTTP、资源、CCS23/24/25、备份/恢复、材料、重开/退出 | 自动检查证据完整，但当前云端 3.15.2 构建字节另需验证 |
| native-ui-onefile / native-materials-onefile | 新归属实际 Edge 流程、Excel16 COM 逐值核对、A4 PDF 与逐页图检查；明确没有物理输入 | 3.12.16 已测行为的有效证据；不可将运行时字段改成 3.15.2 直接复用 |
| final-native-state / primary-recovery | 真实历史保留、恢复、交付、备份及清理；正常新增与原历史逐键分别核对 | 本地实施和恢复已完成，不要求再次迁移原库来证明正式构建 |
| 用户“本人测试没问题” | 本次总体功能实测确认与发布意愿 | 不能推断未点名的托盘操作、确切候选 SHA、生产运行时和 Office 场景 |

主会话已在 `release-execution.md` 记录准备原生 3.15.2。只要新验收实际使用相同已固定产品源码、构建依赖、Python/SQLite/架构，并且 runtime 摘要与候选 build-info 相等，其真实适用回执可按普通后续版本规则复用；不强制每次都重新执行首次候选专属流程。另一个可行路径是下载并核对确切云端候选，在其上执行尚缺专项，回执引用已核验的 build-info runtime，而不是无关 QA 解释器的 runtime。

尚未见到本轮新运行时的六项正式回执，也未见到明确覆盖当前源码/产物的物理托盘菜单打开、双击重开、菜单退出/图标消失事实。`--no-tray`、托盘启用、合成 Windows 消息或 Computer Use 初始化失败均不能代替物理操作。补事实无需重新询问发布权限；可以准确记录用户实际完成的具体动作。材料方面已有有效的原生 Excel/A4 方法，换到生产运行时执行后留真实证据即可，不要求额外纸质打印。

## 工作流与权限

本地源码审查未发现本轮工作流缺陷；`.github/workflows/`、发布脚本、构建配方与运行时配置相对 v0.4.1 均未改变。

- 普通 PR/质量/构建只读，checkout 不保留凭证；可信发布编排才申请写权限。
- inspect 有 `contents: write`，能在实际 job 令牌下看到草稿；candidate 和 prepare 都覆盖 PR/Issues 标签回写，prepare 另有 Actions dispatch 权限。
- 机器人身份精确限制同仓库组件分支、main 目标和 github-actions 作者；发布候选另核对已合并、标签及其在可信 main 的祖先关系。
- prepare 在生成中文说明后显式 dispatch 最终 HEAD；CI 比较 expected_sha，旧 HEAD 的绿色不能放行新 HEAD。
- 候选冻结 M，Directory→OneFile 依次验收；完整草稿恢复复用原资产，缺人工回执时返回 awaiting_acceptance，已公开资产拒绝覆盖/移标签。

这里证明的是源码中声明和实现一致，不代表本轮实际 Actions、仓库“允许 Actions 创建 PR”设置或写权限已执行成功。主会话仍须检查真实功能 PR、机器人 PR 最终 HEAD、构建报告和发布/标签回写结果。如补验期间工作流发生变化，发布前再比较 M 与可信 main 的工作流差异，遵循原合同的 Workflows 权限与原候选恢复约束。

## Findings（未修改）

1. **发布门禁：新运行时/候选与适用回执待完成。** 当前产品可进入发布流程；公开前必须把新六项检查绑定正确源码、实际生产 runtime 和证据。旧正式回执不匹配当前指纹。此为阶段条件，主会话已获授权补齐，不是新增产品决策。
2. **记录一致性：部分任务正文仍保留延期和未授权描述。** PRD“范围外”、implement 第7节、verification 的旧状态及 release-assessment 写着未授权推送/保留积累选择。`release-execution.md` 已准确记录新授权。收尾时应保留历史 chronology 并更新当前结论，不能让旧状态覆盖用户这次指令；本子代理按只写本报告的范围未修改它们。
3. **远端状态尚非本复核证据。** 未执行新 PR/main/push/Actions/公开下载，不能在此报告写成成功。正式完成后由主会话记录真实 M、tag、公开 URL、三项资产 SHA、回执引用和正式 EXE 交付，再完成发布验收项及归档。

没有要求用户重新批准已授权操作，也没有建议降级门禁。此前代码缺陷的修复/回归与最终原生检查另见 `final-code-review.md`、`python-final.json` 和 `verification.md`。

## 本轮实际验证

- 已按 check.jsonl→PRD→design→implement 读取，并复核后端/前端质量索引、相关合同、当前 release-contract 与 docs/RELEASING。
- 固定提交 `validate_changes`：通过；四片段的不可变/唯一身份检查通过。
- 提交/既有构建留档四组指纹相等：通过；39 个记录产品文件与提交逐字节相等：通过；当前 WORKTREE 产品指纹相等：通过。
- 三份旧回执由实际 acceptance_missing 路径校验源码/格式；当前缺失六项的计算：已复现。
- 工作流、权限、候选身份及恢复路径：静态审查通过，远端执行由主会话验证。
- Ruff / strict mypy / 产品测试：本次报告审查没有重跑；沿用对应固定源码的已通过记录，不能把它们标成新的 3.15.2 结果。
