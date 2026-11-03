# 首次 0.4.0 候选与验收回执独立审阅

核查时间：2026-11-03 08:58（北京时间）。本轮仅审阅候选、既有证据和回执门禁；未修改产品源码、工作流、既有回执或远端状态。

## 候选身份和远端状态

- GitHub `main`、发布 PR [#2](https://github.com/NightingaleWK/aha/pull/2) 的实际 merge SHA 均为 `01703aea603549c3d39e64a25a57218c42215b58`（M），权威版本为 `0.4.0`。PR 来自预期同仓库组件分支、作者为 `github-actions[bot]`，已于 2026-11-02 合并。
- [候选工作流 41420947881](https://github.com/NightingaleWK/aha/actions/runs/41420947881) 对应 M，已成功完成质量检查、候选发现、Windows 构建和候选资产处理；下一版本准备作业因当前候选等待验收而跳过。
- Release `431280323` 的版本为 `v0.4.0`，`target_commitish=M`，`draft=true`、`published_at=null`。当前没有真正公开的 Release。
- 远端三项资产均已上传：EXE `701236613`（12,734,507 字节，SHA256 `48d5d469da803f77f797d3a1fa51035950eb16669fdeeaa9e333e0db29ca81f5`）、`build-info.json` `701236534`、`SHA256SUMS.txt` `701236589`。EXE 的 GitHub 原生 digest 与下载核验报告一致。
- 草稿正文与 M 的中文说明对应，内容包括首次公开概览、Windows 按版本下载、CC Switch 23/24 兼容和试用资料重建目录保护；尚未公开不能写成已发布成功。

## 既有本机证据

已逐项核对当前 `aha-release-qa` 证据区中的报告内容和 SHA256，未把早期 0.3.1/中间构建报告作为本次云端候选证据。

| 范围 | 当前报告 | SHA256 | 已有证据界限 |
| --- | --- | --- | --- |
| Directory | `directory-0.4.0-check.json` | `07111e691351420846f1e7a01704f2443c90812bb22b44db39eb31eb48ec397b` | M 的本机目录构建，版本/PE、HTTP、来源23/24、SQL24、材料、复开/重启及退出清理；未声称物理点击。 |
| OneFile | `onefile-0.4.0-check.json` | `07529912571bd1fa2506f9f209d9774f096e29a6fce5395527263c5bcf53d9e4` | 实际云端 EXE 的独立自动检查，字节身份为 `48d5…81f5`。 |
| 桌面交付 | `desktop-0.4.0-check.json` | `672c8ca2fa95e241a8300d89a99558035b3901eebedbb201d0d87a5706d53179` | 从实际桌面同一份云端 EXE 再次运行验证。 |
| 浏览器 | `browser-0.4.0-report.json` | `67f5121a7b115392b886e1c954b64a53c29a9bbabf08fc4f11497b91362463c4` | 原生 Edge 156 的实际 DOM 操作、保存/原包重下、页面退出和客观清理；属于浏览器验收，不是托盘物理点击。 |
| A4 PDF | `onefile-0.4.0-print.json` | `5f7d06b17ed7be80d9f87a50199e75cab6c4025f03b7c630c191d7736cb0d71a` | 实际云端 OneFile 材料经原生 Edge 输出一页 A4，精确金额/Token、文字和渲染已检；没有纸质打印声明。 |

用户于本轮补交 v0.4.0 页面、托盘图标和菜单截图及三行合成 CSV，并明确确认双击重开、右键退出且图标消失、本机 Microsoft Excel 中文和金额均正常。新回执应引用本轮真实人工反馈及当前核验记录。昨天 `manual-0.4.0-session.json` 只记录实例就绪，原监测会话已不存在，不能补写未被客观观察的退出码或伪称旧监测捕捉了今天的物理操作。

## 回执字段和离线校验

首次新回执须同时包含：`schema_version=1`；实际测试 `source_sha=M`；`candidate_source_sha=M`；确切 EXE `artifact_sha256=48d5…81f5`；已核验构建信息的 `runtime_sha256=2d64ab084e0aa6c3d8ffab874ef7a08fd35b4fbf452dc1353e89d06dc7ea8642`；带 `+08:00` 的实际 `completed_at`；四项真实指纹；六项 `checks`；每项至少一条具有 `scope`、真实证据摘要 `sha256` 和准确 `description` 的证据。不放个人路径、真实资料、截图正文、Cookie 或启动令牌。

独立重算的 M 指纹：

```json
{
  "full": "c43a3c1f6f0133671bf225eecd75297c234fa6f57eb2eb91f5df55813ecc404b",
  "tray": "6341e2a0ad0d1f303f463908ba4a0f3f4f640c1a9f62f9db1875d920e0e22019",
  "materials": "5071859342983ed67ac1b794ef7938f359e43a616c9bdd9801234c9742b2b084",
  "recipe": "bc1b83967159c74e11c8372ca9a5c8d596efb345a05735ef944f0d7f613402df"
}
```

已实际调用 `required_checks` 和 `acceptance_missing`：首次需要 `browser/directory/excel/onefile/print/tray` 六项；在当前远端 M 上读取原有部分回执，仍返回缺少全部六项，因为原回执未绑定首次候选 M 和资产。该行为符合预期，不得修改旧部分回执冒充本轮完成。

新回执写入后，可直接调用 `acceptance_missing(root, M, "WORKTREE", None, artifact_sha, runtime_sha)` 离线核对。此调用不会连接 GitHub 或执行公开操作。本轮已在主会话整理新文件后完成下述最终复核；不能把本报告等同于最终公开授权。

### 新回执最终复核

- 实际文件 `.release/acceptance/v0.4.0-first-cloud.json` 的 SHA256 为 `cd75f88401ad8a3b4f5e0815c7f4e7ba417df7c98a39d85a6713e3445127ee8d`。源码/候选 M、EXE、运行时、实际完成时间和四项指纹一致；六项证据摘要分别与实际安全报告字节匹配。
- `human-0.4.0-acceptance.json` 的 SHA256 为 `431d11d053f8826d965dbfb4a5334b325c4ec6eedd82fe398e2dedd635f782c0`，准确区分用户亲自操作及代理事后核对，没有冒称桌面自动控制或历史监测观察到了本次退出。
- 独立复核本地只读主机观测：桌面 EXE 的 SHA 为云端候选 SHA，无 `aha.exe` 存活，普通资料实例的描述符不存在，Excel 进程为零；六份桌面验收材料的字节摘要均与创建时 owner 标记相同。原合成监测的遗留描述符被明确保留为历史局限，不用来证明今天的正常退出。
- 用真正的 `build-info.build_runtime` 按 M 的配方独立重算运行时摘要，得到 `2d64ab084e0aa6c3d8ffab874ef7a08fd35b4fbf452dc1353e89d06dc7ea8642`；本地三份云端资产的摘要与 GitHub 原生资产 digest 逐项相同，四项产品指纹与 M 重算结果相同。
- 对实际工作树回执调用生产 `acceptance_missing`，返回 `[]`。独立用内存副本/mock 数据分别改变首次候选 M、EXE SHA、运行时 SHA，均返回缺少全部六项；移除托盘检查与对应证据，返回 `['tray']`；保留检查但移除托盘证据、伪造 full 指纹，均被拒绝。负例没有修改真实回执或写入远端。

## 合并和公开边界

`.github/workflows/release.yml` 由 main push 触发。按代码路径，完整新回执合入 main 后，只有 `discover` 所使用的令牌能看见同一未公开 M 的草稿时，三资产完整才会得到 `needs_build=false`、跳过重建；`stage` 核对原资产并从固定的最新可信 main 提交读取回执。六项通过后立即 `PATCH /releases/431280323`，令 `draft=false`、`make_latest=true`，随后将 PR 标记为 tagged。因此合并完整回执是实际公开动作的入口，不能以“仅补文档”解释为没有发布影响。初轮只使用高权限连接器查看草稿，未覆盖 job 只读令牌的可见性差异；后续真实运行揭示的问题见下节。

初轮审阅时用户确认人工验收通过、公开选择尚待给出。此后用户已明确授权公开 0.4.0，验收 PR #5 已合入 main `2aacb30a1e24cc8970727476cbe83dd19b0b1695`；既有授权直接复用，不再重复询问。保持本轮候选 EXE 字节与源码 M 不变。

## 检查结果

- Ruff：`ruff check --no-cache src tests scripts` 通过。
- mypy：`mypy --cache-dir=/dev/null src/aha` 通过，22 个生产源文件无问题。
- `git diff --check`：通过。
- 初轮首版门禁：当时远端 main 的旧部分回执缺六项，分支上的完整新回执经真实代码调用返回 `[]`，正负场景通过。此后回执已随 PR #5 合入 main；真实恢复状态见下节。本审阅代理没有执行真实 `stage`。
- 完整 251 项 Python 和现有 JavaScript 基线：本轮无产品改动，不重复执行；远端 M 对应候选质量检查成功。
- 初轮未发现产品源码或回执问题，但漏查了草稿发现令牌权限差异；后续真实运行需要修复该工作流权限。公开发布和公开下载核验尚未完成前，相关范围保持未完成。

## 真实恢复运行揭示的草稿可见性问题

补查时间：2026-11-03 09:20（北京时间）。[恢复运行 41558110567](https://github.com/NightingaleWK/aha/actions/runs/41558110567) 已完成 main 质量检查。inspect job `125663387139` 的真实日志记录 `Contents: read`、`PullRequests: read`，随后调用 `release.py discover`。build job `125663477787` 被启动，说明该轮发现结果要求重新构建；此时高权限连接器仍可查看到同一草稿的原三项完整资产，EXE 资产 ID、大小及 SHA256 均未变，Release 仍未公开。

GitHub 官方 [List releases](https://docs.github.com/en/rest/releases/releases#list-releases) 明确：公开版本向所有人可见，草稿列表仅向具有仓库 push 访问权的调用者提供。端点的通用 `contents:read` 要求不能推出草稿也可见。结合实际 job 权限、执行分支和代码，根因为 inspect 的只读 `GITHUB_TOKEN` 看不到草稿，`discover` 得到 `existing=None` 后将其当作尚无资产，输出 `needs_build=true`。这里没有提取或重放 job 令牌，也没有把高权限连接器的可见性冒称只读 job 已验证。

最小修复是仅把可信发布编排的 `inspect.permissions.contents` 改为 `write`，并写明是为读取草稿可见性而需要；`pull-requests` 保持 `read`，顶层默认、普通 PR 质量检查和构建仍保持只读。发现脚本本身仍只发 GET 请求，不增加写 API、个人令牌或额外资产替换逻辑。`actions/checkout` 继续 `persist-credentials:false`，写令牌不交给不可信 PR 执行。

当前错误重建不能成为替换已验收字节的理由。后续 `stage` 用具备写权限的令牌看见原草稿时，会对已存在同名资产逐字节核对；新构建的 build-info 或 EXE 与原字节不同即失败，不能覆盖原资产或用旧回执放行新 EXE。该行为是代码路径核查结论，旧运行尚未结束时不声称已观察到该最终失败。

同一官方页面的 [Update a release](https://docs.github.com/en/rest/releases/releases#update-a-release) 还说明：若目标提交相对默认分支修改 `.github/workflows/` 文件，发布更新可能要求 `workflows:write`，而 Actions `GITHUB_TOKEN` 不能取得该权限。因此将权限修复先合 main 后再公开旧 M，需要留意这一权限边界；具体历史祖先提交是否命中该限制尚未实测，不能断言一定拒绝。可在受信任的修复分支上显式运行 Release 工作流、保持默认 main 的工作流仍与 M 一致，成功公开同 M 后再合修复。该路径仍须核对实际执行结果，不以文档推断代替真实发布成功，也不要求另换个人令牌。

### 权限修复落地后的复核

- 用 PyYAML 解析修复前后的整个 `release.yml` 并做语义比较，唯一语义变化为 `jobs.inspect.permissions.contents: read → write`。顶层 `contents:read`、inspect 的 `pull-requests:read`、其他 job 权限和 `persist-credentials:false` 全部不变。
- 产品源码、构建入口与实际 Windows 配方未变；工作树四项指纹与 M 全部一致，因此不需要另建 EXE 或重新做人机专项。
- 原新回执文件的 SHA256 仍为 `cd75f88401ad8a3b4f5e0815c7f4e7ba417df7c98a39d85a6713e3445127ee8d`；实际调用 `acceptance_missing(M, WORKTREE, None, 48d5…81f5, 2d64…8642)` 返回 `[]`，旧候选资产绑定保持有效。
- `release.py validate --base HEAD --ref WORKTREE` 和 `git diff --check` 均通过。没有新增产品源码，不重复 251 项基线；此前 Ruff 和 mypy 的通过范围未发生代码变化。
- 本机没有 actionlint，未声称执行该检查；YAML 解析和权限语义比较已实际执行。
- 新权限令牌在 GitHub 上能看到草稿、跳过重建并成功公开原资产，仍须后续真实运行确认。本代理未发起、合并、公开或替换任何远端资产。

### 精确受信分支临时入口审阅

当前连接器没有可用的工作流 dispatch/cancel 写入口。主会话采用同一 `release.yml` 的临时精确 push 分支作为一次性恢复入口，先从受信分支运行修复后的 inspect，避免提前改变默认 main 的工作流；不另建发布链或更换资产。实际审阅的临时 YAML SHA256 为 `d7988c532682ee167b746bf6a31f7916a50892a124a74245a8a0a49a358294fe`。

- PyYAML 解析和前后语义比较确认：除 inspect 的必要 `contents:write` 外，仅把 `push.branches` 从 `[main]` 临时改为 `[main, codex/release-draft-discovery]`。没有新增 `pull_request`、`pull_request_target`、通配分支或可执行任意 PR 代码的入口；其他/近似分支名不能匹配。
- 入口是同仓库受信分支的 push，不读取不可信 PR 代码；仍先执行只读 quality，成功后才能执行 inspect。原只读 CI、Windows 构建工作流和发布脚本均未修改。
- 原固定并发组 `aha-main-release` 与 `cancel-in-progress:false` 不变，旧 main 恢复和新受信分支运行继续串行处理同一候选。candidate 仍依赖 inspect/build 的真实结果，不绕过失败。
- 构建源码仍取 `needs.inspect.outputs.source_sha`，而非临时分支 HEAD。discover 仍从可信 main 寻找已合并的真实发布 PR、验证 M 是 main 祖先；stage 仍验证 M 的中文说明、资产来源/字节、实际运行时和固定可信 main 上的完整回执。旧候选或回执门禁没有放宽。
- 只读查询核对 remote main 仍为 `2aacb30a1e24cc8970727476cbe83dd19b0b1695`；本地 Git 对比该提交与 M 的全部 `.github/workflows/` 路径无差异。原草稿仍为 M，原三资产的 ID/SHA256 不变。
- 临时分支工作树四项指纹仍等于 M，原回执的实际门禁结果仍为 `[]`；发布输入校验和 diff 检查均通过。

该临时入口在当前既有公开授权内可执行。公开原 M 后，应立即删除临时分支触发及相关临时注释，恢复 `[main]`，再审恢复后的最终 HEAD 并合入永久 inspect 权限修复。此次结论只覆盖上述精确临时状态；真实运行成功和最终入口移除仍须分别核验。本代理没有推送或修改远端。

## 正式公开、下载验收与最终工作树审阅

### 已公开事实

- [v0.4.0](https://github.com/NightingaleWK/aha/releases/tag/v0.4.0) 已于 2026-11-03 09:30:55（北京时间）正式公开。独立查询 GitHub 确认 `draft=false`、发布标签 `refs/tags/v0.4.0` 为直接 commit 引用且指向 M；三项资产的 ID、大小和 SHA256 均与原候选相同，没有因恢复重建替换已验收 EXE。
- 真实修复运行 [41559607007](https://github.com/NightingaleWK/aha/actions/runs/41559607007) 的 inspect 日志实际记录 `Contents: write`、`PullRequests: read`；inspect 成功、build skipped，证实修正令牌权限后能够复用完整草稿。本轮公开的是原 M 和原资产，并未把临时分支代码打包进去。
- candidate 在公开成功之后发生 `GitHub POST failed with HTTP 403`，真实权限日志仅有 `Contents: write` 和 `Issues: write`。结合 stage 的执行顺序，错误发生在公开后的 `mark_tagged` 阶段；日志没有具体请求路径，不能断言是仓库 label 创建还是给 PR 添加 label 的某个 POST。
- GitHub [标签接口说明](https://docs.github.com/en/rest/issues/labels#add-labels-to-an-issue) 把 Issues(write) 和 Pull requests(write) 列为至少满足其一，不能将本次 403 推导成所有标签操作普遍必须同时授予两者。本项目 candidate 显式增加 `pull-requests:write`，使其覆盖已合并发布 PR 的状态回写并与 prepare 的配置一致；是否彻底解决本次状态回写，仍由后续真实 main 的 prepare/reconcile 及 PR pending/tagged 状态验证，不能提前写成已成功。

### 公开下载和成品核验

- 已独立核对 `public-release-0.4.0-proof.json` 与实时 GitHub 的 Release、标签 M 和三资产元数据一致；记录的公开下载检查文件 SHA256 与实际 `public-release-0.4.0-check.json` 一致，为 `063fdc5f925fcc198235cfe01d16d8ba21db74daf6690b1555753d6b85b48de9`。
- 公开下载的 EXE 已于 09:32:42 通过原生运行、PE/HTTP 0.4.0、资源字节、CCS23/24、SQL24、精确冻结材料、复开/持久重启和退出清理。检查明确保留 `tray_physical_checked=false`、`browser_driven=false`、`office_checked=false`，不把这次自动复验冒充重新做过的物理专项；先前本版实际人工证据继续按原指纹和原资产有效。
- 本审阅代理再次独立计算实际桌面 `aha.exe` SHA256，仍为 `48d5d469da803f77f797d3a1fa51035950eb16669fdeeaa9e333e0db29ca81f5`，与正式下载和原候选相同。
- 清理后再次独立核对保留的 `public-release-0.4.0-build-info.json`、`public-release-0.4.0-SHA256SUMS.txt` 摘要与真实公开资产完全一致；冻结材料 `public-release-0.4.0-frozen-material.zip` 摘要匹配公开原生检查记录，四个成员完整。使用保留的 build-info 重算运行时仍为 `2d64…8642`；任务 QA 根已移除，本轮证据复核不依赖已清理的环境或构建目录。

### 最终 YAML、指纹和文档

- 最终工作树 `release.yml` SHA256 为 `a0ed0704a5e3149f76f92cc21703a722e60c115016812ff3b3a515e13c426959`。与验收 main `2aacb30` 的整份 YAML 做语义比较，永久变化只有 inspect 的 `contents:read → write` 和 candidate 新增 `pull-requests:write`。
- 已实际确认临时分支名称和临时注释全部移除，`push.branches=[main]`，仅保留原有 workflow_dispatch；普通 PR/质量/构建权限、其他作业、固定并发和全部发布门禁未变化。
- 工作树四指纹与 M 完全一致，原完整回执字节 SHA 不变，生产 `acceptance_missing` 仍返回 `[]`；发布输入校验与 `git diff --check` 通过。产品源码和 Windows 构建配方没有改变，无需重建成品或重复已有全面人工验收。
- 审阅新增 Markdown 链接：GitHub 官方草稿可见性、Release 更新权限、标签权限页面与对应发布/运行记录可读，未发现新增本地链接缺失。规范中的本项目权限配置与 GitHub 通用可选权限说明分开记录；关于历史 M 与新默认工作流差异的限制仅作为官方边界，不声称本次已经实测发生该第二种拒绝。
- 主会话已修正 verification 的相关措辞：工作流差异仅记录为依据官方边界采取的预防顺序，祖先 M 在另一种合并顺序下是否发生额外 403 未实测；标签 POST 的确切路径和充分失败原因也没有被无证据确定。

### 实际 actionlint

- 从 [actionlint 官方 v1.7.12](https://github.com/rhysd/actionlint/releases/tag/v1.7.12) 下载 Linux amd64 版本，归档 SHA256 `8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8` 同时匹配官方 checksums 文件及 GitHub 资产 digest；没有全局安装或修改 bundled 依赖。
- 实际执行 `actionlint -oneline .github/workflows/ci.yml .github/workflows/release.yml .github/workflows/windows-build.yml`，退出码 0、stdout/stderr 均为空。临时下载目录经归属校验后已清理。
- ShellCheck 和 Pyflakes 不在本机 PATH，未宣称执行其额外检查。此前 Ruff/mypy 和产品测试基线不因本轮仅 YAML/文档的变化失效，不重复 251 项产品全量测试。

最终独立审阅未发现还需修改产品、候选资产或最终 YAML 的问题。真实公开和公开下载验收已完成；标签状态恢复的实际成功仍待主会话随后确认，再做整个任务的最终归档。本审阅代理始终未执行推送、合并、发布或远端标签/资产修改。
