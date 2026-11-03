# 实施计划与验收顺序

## 0. 开始实施的门禁

- [x] 用户同意创建任务并进入规划。
- [x] 发布PR节奏、自动What’s New及首次全面/以后按影响专项的政策已确认。
- [x] PRD需求和AC、技术设计、研究及子代理上下文清单已形成。
- [x] 用户回复“好的”，批准最新完整规划；本任务已进入实施。

本任务已于2026-11-03完成并归档，最终状态为 `completed`。下列清单已依据 [最终验收记录](verification.md) 和 [任务元数据](task.json) 同步；原实施顺序及回退约定保留作为历史记录。

## 1. 实施前核对及分工

- 核对 `git status --short --branch`、远端main/标签/Releases及当前任务，保留用户改动和本地CCS24修复。从已核实的f2e77cb基线建立 `codex/versioning-github-releases`，不重置旧分支。
- 获批准后加载Phase1.4/Phase2.1并启动本任务；原生Codex分派优先使用 `trellis-implement` / `trellis-check`，提示首行 `Active task: .trellis/tasks/11-02-versioning-github-releases`。
- 主会话负责需求、设计、规范同步、跨层整合、原生验收、提交及收尾；实施代理负责产品/构建/自动化代码和对应测试。按版本构建接口稳定后再接入发布编排，不在同一文件并行写入。
- 告知任何实施代理它不独占代码库，不回退其他代理或用户修改；加载 `implement.jsonl`，检查代理加载 `check.jsonl`，原生注入不可用时在子端读取任务及规范。
- 确认任务临时Windows/Linux目录及归属，主环境、个人来源、正在使用的EXE和真实data-dir不得用于试验或清理。

## 2. 权威版本与构建身份（R1、R3）

- [x] 将pyproject版本切换到setuptools动态属性，保留 `aha.__version__` 为唯一产品来源；验证安装/wheel元数据和运行时一致。
- [x] 按Python策略和generic extra-file配置Release Please，处理 `aha-usage` 与 `aha` 不同名，设置0.x规则及首版0.4.0引导。
- [x] 扩展既有Windows构建入口生成PE版本资源，保留SQLite/venv门禁、固定依赖、许可证、Directory先验收再OneFile。
- [x] 明确成品/校验/构建信息格式；分开“源码SHA”“产品指纹”“产物SHA256”，不互相替代。
- [x] 增加有意义的版本不一致、非法版本、PE资源生成和原门禁保留回归。

## 3. What’s New与人工验收回执（R8–R11）

- [x] 实现JSON片段校验、稳定筛选/去重和中文版Markdown生成；采用设计中的栏目与省略规则。
- [x] 只取对应候选最终树和最近成功公开Release之间的内容；首次范围显式引导，不造旧标签。
- [x] 明确未发布功能撤销、已发布片段不变、缺失说明、internal排除理由和breaking升级说明的行为；给出正常、多项、空/错误及重跑回归。
- [x] 将预览写入版本化说明及发布PR专用区，保留工具识别标记；源片段为文案编辑入口，正式正文不二次自由改写。
- [x] 实现生产范围/配方指纹与人工回执校验。版本数字规范化仅用于专项证据复用；新增模块、影响不明和构建环境变化不得自动免验。
- [x] 写PR模板、开发约定及维护说明，使未来每项开发由Codex随代码提交中文片段，不要求用户发版时手工作文。
- [x] 用已确认的政策统一更新backend quality/delivery/主契约、frontend quality及索引；新增必要的版本发布合同，不能只改任务文档留下旧规范冲突。

## 4. 每版自动检查与Windows成品验证（R2、R3、R8）

- [x] 在原生Windows x64隔离环境准备固定3.15.2，实际探测SQLite，验证与固定构建依赖兼容；失败修复环境，不降低门禁。
- [x] 增加原生EXE验证入口，使用独立合成用户目录/data-dir，自动核对HTTP、页面资源、版本、来源23/24、真实job终态、保存下载/材料、复开、退出、端口/描述符。
- [x] Directory真实验证通过才调用OneFile；对OneFile独立验证并核对PE字段、文件SHA及构建信息。
- [x] 打包任务使用确定源码SHA，输出必要小型摘要，启动凭证不入日志/资产，超时只清理本任务进程及文件。

实施后运行以下现有检查；原生环境路径用实际任务环境，不把个人路径固化进配置：

```text
<任务Python> -m unittest discover -s tests -v
<任务Python> -m ruff check src tests scripts
<任务Python> -m mypy src/aha
<任务Python> -m compileall -q src/aha scripts
node --check src/aha/web/app.js
node --check src/aha/web/form-controls.js
node --check src/aha/web/time-range-picker.js
node --test tests/web_state.test.cjs
git diff --check
```

新增脚本按真实接口加入类型/静态检查及相关回归，工作流用适用校验器检查语法/表达式；不以字符串搜索代替执行逻辑或HTTP验收。

## 5. GitHub编排、权限及恢复（R4、R5、R12）

- [x] 配置ci/release/windows-build入口，固定经过核对的action SHA。测试、PR写入、dispatch和正式发布权限按job拆分，普通PR只读。
- [x] main合入触发Release Please准备/更新发布PR，补齐What’s New后取得最终HEAD再dispatch CI；验证 expected SHA，分支前进时旧结果失效。
- [x] 合并发布PR后固定merge SHA M构建，不打包最新main；验证可信同仓库发布PR身份、版本文件/manifest/说明及人工回执。
- [x] 草稿→资产上传/核对→正式公开分步执行，最后一步前任何失败都不显示正式成功；资产含EXE、SHA256SUMS和build-info。
- [x] 实现同版幂等、部分草稿恢复、公开版本不覆盖、旧/错误标签阻断及并发/排队事件恢复。不要只依赖工具的release_created输出。
- [x] 用隔离假GitHub接口/命令适配器回归失败矩阵；本地回归不得创建真实Release或移动远端标签。

必要失败矩阵：版本/正文不匹配、SQLite不合格、目录包失败、OneFile失败、人工证据缺失/失效、上传中断、已有匹配或冲突草稿、已公开版本重跑、迟到main事件、机器人PR更新后旧CI结果、标签由默认令牌创建不触发后续workflow。

## 6. 独立检查、首次全面本机验收与桌面交付（AC1–AC10）

- [x] 分派 `trellis-check` 按整个PRD/design/implement范围复核，修复问题并针对变更重测；主会话复核版本→说明→构建→资产及失败链路。
- [x] 首次全面验收已完成：Directory、OneFile、真实浏览器、托盘物理交互、Excel及一页A4 PDF分别留证。用户于2026-11-03确认托盘重开、菜单退出及Excel结果，六项检查已记录于 [完整首版回执](../../../../../.release/acceptance/v0.4.0-first-cloud.json)。
- [x] 通过Windows桌面接口确认交付位置，核对同名文件归属和运行占用，交付与最终源码一致的单文件EXE；从交付位置实际启动、保存下载、重开及退出，确认SHA一致。
- [x] 留存小型验收回执、产品/配方指纹、运行时及报告；若专项未实际执行，不标成通过或解除发布门禁。

## 7. 可审阅设置PR与首次真实发布（AC11、AC12）

- [x] 本地代码和验收通过后准备设置PR，清楚说明包含未合main的0.3.1 CCS24修复、单一版本和自动发布机制；推送/开PR按用户已授范围执行。
- [x] 实际Actions、机器人PR创建权限及分支规则已核查；用户已开启工作流创建PR，后续真实CI、候选构建及发布恢复均有执行记录，见 [最终验收记录](verification.md)。
- [x] 设置PR#1的main合并：用户要求清理同步后，核对d1fcacf最终HEAD CI通过，以23977da合入main。
- [x] 首次发布PR#2经用户审阅决定，在最终HEAD `db155bd12e64028385154434bad5fd1b21c4eed6` 的 [CI 41419894652](https://github.com/NightingaleWK/aha/actions/runs/41419894652) 通过后合入main，确切发布源码M为 `01703aea603549c3d39e64a25a57218c42215b58`。
- [x] 真实机器人发布PR中的0.4.0版本、中文预览和最终HEAD CI均已核对；[独立候选审阅](research/final-candidate-review.md) 与最终验收记录保留实际检查依据。
- [x] 首次云端候选EXE已下载到本机，核对SHA、PE/HTTP版本及独立启动/业务结果；完整首版回执绑定M、确切EXE及构建运行时，首次全面验收完成后按用户明确选择正式公开。
- [x] [v0.4.0](https://github.com/NightingaleWK/aha/releases/tag/v0.4.0) 于2026-11-03 09:30:55（北京时间）正式公开，正式下载于09:32:42通过原生验收，SHA与桌面副本一致。原M和资产字节保持不变；[恢复运行41562176404](https://github.com/NightingaleWK/aha/actions/runs/41562176404) 通过并恢复发布PR#2的tagged状态。

## 8. 清理、提交及收尾

- [x] 更新必要规范和验收记录，确认源码最后一次修改之后的成品已重建且匹配。
- [x] 核对并停止本任务已无用进程，逐项清理任务环境、合成资料、构建中间物和缓存；保护真实资料、主环境、用户EXE、必要证据和最终成品。
- [x] 已按用户授权完成提交、任务归档及journal；归档提交 `b805e90` 和会话提交 `de49406` 均已同步至远端main。
- [x] 已分别记录本地实施、桌面成品、GitHub配置与正式Release的执行结果，全部13项AC满足。最近公开版本为0.4.0，累计用户待发内容为空，本轮维护收尾无需另发0.4.1，详见最终验收记录及会话日志。

## 风险文件及回退点

- 动态版本/PE打包不兼容：在版本PR合入前修复或回退相应改动，保留原可用成品，不改业务存储。
- What’s New生成不一致：回到源片段和候选范围修正，重新生成/检查，不手改正式版掩盖差异。
- 权限或机器人CI触发异常：停止在待审PR/草稿阶段，修复精确权限或dispatch；不降低分支保护或让无检查版本公开。
- 草稿部分上传失败：按相同版本和M恢复；正式版有冲突则发布新patch，不覆盖或改写已发布标签/资产。
