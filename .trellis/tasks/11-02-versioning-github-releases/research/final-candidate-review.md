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

`.github/workflows/release.yml` 由 main push 触发。完整新回执合入 main 后，`discover` 会发现同一未公开 M，三资产完整时 `needs_build=false`，跳过重建；`stage` 核对原资产并从固定的最新可信 main 提交读取回执。六项通过后立即 `PATCH /releases/431280323`，令 `draft=false`、`make_latest=true`，随后将 PR 标记为 tagged。因此合并完整回执是实际公开动作的入口，不能以“仅补文档”解释为没有发布影响。

当前用户明确确认了人工验收通过；正式公开仍按当前可审阅结果和明确发布选择执行。新回执 PR 可先准备、审阅及运行只读 CI，未经本次公开决定不合并该 PR、不调用 `stage` 或手动工作流恢复。保持本轮候选 EXE 字节与源码 M 不变。

## 检查结果

- Ruff：`ruff check --no-cache src tests scripts` 通过。
- mypy：`mypy --cache-dir=/dev/null src/aha` 通过，22 个生产源文件无问题。
- `git diff --check`：通过。
- 首版门禁：远端现有 main 上旧部分回执缺六项；分支上的完整新回执经真实代码调用返回 `[]`，正负场景通过，等待用户公开选择及受审阅合并。未运行真实 `stage`。
- 完整 251 项 Python 和现有 JavaScript 基线：本轮无产品改动，不重复执行；远端 M 对应候选质量检查成功。
- 未发现需要修改产品源码或工作流的问题。新回执最终复核通过；公开发布和公开下载核验尚未执行，相关范围保留未完成，不能提前归档任务。
