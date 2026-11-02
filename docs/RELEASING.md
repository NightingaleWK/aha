# 版本与发版维护

## 日常迭代

1. 在功能或修复分支完成改动，由Codex随代码编写 `.release/changes/<稳定标识>.json` 中文说明，执行相应检查和本机专项。
2. 功能PR合入 `main` 后，Release工作流准备或更新一份发布PR，自动递增版本、更新技术CHANGELOG并生成中文版What’s New。
3. 在发布PR中审阅版本、用户变化、升级事项及最终HEAD的CI。修改文案时修改源片段并合入main，让机器人重新生成；不要手改生成文件。
4. 合并发布PR后，GitHub对该PR的实际merge SHA构建Windows x64程序，依次检查Directory和OneFile，再上传草稿资产；所有适用门禁通过后自动公开。
5. 从 [Releases](https://github.com/NightingaleWK/aha/releases) 下载对应版本EXE，可使用同版 `SHA256SUMS.txt` 核对文件。

正式发版由合并发布PR决定，机器人不自动合并发布PR。应用本身仍离线运行，本流程不实现应用内更新检查、自动安装或代码签名。

## 每项工作完成后的引导

Codex先完成本次已授权的修改、检查、适用的桌面交付和清理，再向维护者给出发版评估与选择，不需要维护者额外提醒。具体约定见 [发布合同](../.trellis/spec/backend/release-contract.md#每项工作收尾的发版评估)。

| 实际变化 | 默认建议 |
| --- | --- |
| 影响核算、资料安全或正常使用的已验证修复 | 优先尽快发布修复版，并说明影响和升级事项。 |
| 已完成且可独立使用的新功能 | 建议发布功能版；也可按维护者安排积累多项后发布。 |
| 小型体验改进或非紧急修复 | 可积累到下一版；保留中文说明和相应验收记录。 |
| 无产品影响的文档、测试、工作日志或内部整理 | 本次通常无需单独发版；已有待发功能仍需单独报告。 |
| 仅提出需求、尚未实现，或适用检查/验收未齐 | 说明尚未就绪，先准备和补齐条件。 |

每次评估说明：本次用户能感知什么、最近真正公开的版本、累计待发内容、建议版本和原因、What’s New预览、实际检查结果及缺口。本机运行版本和建议发布版本分开写；未核实远端时明确说明。已有待发功能优先决定版本级别，不按每个任务机械升号；最终版本仍由发布PR统一递增。

例如以下是未来一次修复后的引导示例，版本和内容均为假设：

> 已修复导出金额舍入问题，并完成相关验证。假设最近公开版本是0.4.0、没有其他待发功能，建议发布0.4.1，因为修复影响费用核对。What’s New和待合入PR已准备，本地交付及当前阶段应完成的检查、专项验收已通过。请选择：**现在发布0.4.1（推荐） / 积累到下一版**。合并后仍须通过云端构建和自动检查才会公开。

若已知检查失败或必需人工证据仍缺失，尤其首次托盘和云端候选本机验收未完成时，改为“**先补齐发版条件（推荐） / 暂不推进发布，积累到下一版**”，列出需要补的项目；纯文档任务则推荐“**本次无需单独发版**”，并说明之前积累的待发版本是否仍有未完成事项。常规发布中计划在合并后执行的云端构建、自动检查按原流程运行，无需为给出启动选项提前执行；“现在发版”表示进入流程，所有门禁通过后才能公开，不是成功声明。

选“现在发版”前，给出拟合入的功能PR、发布PR、候选版本和公开动作供审阅；有明确覆盖这次动作的既有授权就继续执行，不重复询问。选择积累则记录决定并保留片段，发布PR保持未合并。没有用户影响的任务无需新建What’s New片段；有用户影响但延期的内容不能因此省略。未答复不等于同意公开，用户选择也不能代替真实验收。

决定记录在当前任务中。普通功能任务已满足自身标准时可以正常收尾；本任务若要求验证真实发布，则公开发布之前继续保留相应验收项未完成。这套引导由本地开发对话执行，程序本身不增加发布提示。

## 版本号

`src/aha/__init__.py` 的 `__version__` 是唯一产品版本来源。Python包元数据、页面和材料版本、Windows文件属性及发布标签从它读取或生成。Release Please的manifest是候选版本状态，CI要求它与产品版本一致，不手工在多处改数字。

- `fix:`：修复问题，例如0.4.0→0.4.1。
- `feat:`：新增兼容功能，例如0.4.0→0.5.0。
- 0.x期间的破坏性变化：升次版本并提供醒目的升级说明。进入1.0由维护者明确决定；1.0之后的破坏性变化升主版本。
- 内部归档、工作日志和无产品影响的纯文档不单独发空版本。

首版配置以未公开的0.3.1为基线，bootstrap范围自 `f98df67df38a534fb240d20a79dda843297f4437` 之后开始，本轮功能预期形成0.4.0。首次What’s New单独说明既有能力与近期变化，不补造旧版Release。

## 中文说明片段

```json
{
  "id": "stable-unique-change-id",
  "kind": "feature",
  "title": "用户能理解的标题",
  "description": "说明实际交付的变化、使用场景及可观察结果。",
  "highlight": true,
  "upgrade_notes": []
}
```

`kind`支持feature、improvement、fix、breaking和internal。breaking必须有非空升级事项；internal必须填写reason说明为什么没有用户影响。id在整个历史中唯一，已发布片段不改写，纠错用新片段。撤销尚未发布的功能时移除相应未发布片段，并为代码回退提供带reason的internal片段；它只解释本次源码变化，不进入用户栏目，也不单独产生空版本。最终生成以候选源码树为准。

What’s New按真实内容生成兼容性提醒、本次亮点、新增功能、体验改进、问题修复、升级说明和下载/完整变更；空栏目省略。产品正文在发布PR里审阅，正式发布只补充真实机器信息，不再调用模型另写一稿，也不要求额外模型密钥。

本地预览示例（写到本任务证据目录，预览不代表已发布）：

```text
python scripts/release.py render --ref WORKTREE --version 0.4.0 --output <任务目录>/whats-new-preview.md
python scripts/release.py validate --ref WORKTREE --base main
```

## 首次全面验收和以后专项

首次公开前，必须真实完成Directory、OneFile、浏览器、托盘物理交互、Excel及A4打印预览/PDF验收。云端首次候选EXE还须下载到本机核对字节、版本和运行结果。自动消息、启用托盘启动或HTTP通过不能写成物理点击；导出字节校验不能写成Excel/打印验收。

以后每版始终执行自动测试、原生EXE/HTTP/资源/材料/复开/退出检查；相关源码指纹变化追加本机专项：托盘/生命周期链需要托盘和浏览器，材料生产链需要Excel和打印，运行时/打包配方或未知新模块变化要求全面验收。单纯版本数字不会让人工指纹失效。CI核对回执与指纹，不声称云端重做过人工操作。

取得指纹：

```text
python scripts/release.py fingerprints --ref <已验收的源码提交> --output <任务目录>/fingerprints.json
python scripts/release.py runtime --ref <已验收的源码提交> --output <任务目录>/runtime-proof.json
```

真实完成后，将小型回执写入 `.release/acceptance/<验收标识>.json`。下面是字段说明，不是通过记录，不可原样提交：

```json
{
  "schema_version": 1,
  "source_sha": "已实际验收的40位提交SHA",
  "candidate_source_sha": "首次GitHub候选的40位merge SHA",
  "artifact_sha256": "首次GitHub候选EXE的64位SHA256",
  "runtime_sha256": "实际验收Windows环境的runtime命令输出",
  "completed_at": "实际完成时间，ISO8601并带时区",
  "fingerprints": {
    "full": "指纹命令输出",
    "tray": "指纹命令输出",
    "materials": "指纹命令输出",
    "recipe": "指纹命令输出"
  },
  "checks": [],
  "evidence": []
}
```

checks只能填写实际执行的directory、onefile、browser、tray、excel、print；每项都要有 `{"scope":"对应check","sha256":"安全验收记录的64位摘要","description":"实际检查和结果"}`。不要放个人路径、真实数据、Cookie、启动token或完整私有日志。

runtime命令须在实际Windows x64验收venv执行，摘要覆盖完整Python修订版本、SQLite、平台/位数及固定构建依赖（含固定的传递依赖）。它不包含aha版本数字或无关Office/PDF等QA工具，常规升号不会触发全量重验；实际SQLite等运行时相较前版发生变化则要求全面验收，旧环境回执不能复用。build-info仍保留完整已安装依赖清单供追溯。

首次还要求candidate_source_sha及artifact_sha256与当前候选完全一致；缺少物理托盘等任何项就保留草稿。可以在候选M生成后，通过仅增加回执的受审阅PR更新可信main，再恢复相同M/相同字节的发布。后合入的代码不能因此混进M；候选EXE重建后SHA变化，旧首次回执失效。

## 失败、草稿与重跑

工作流使用确切源码SHA，不打包执行时最新main。测试、版本、说明、运行时或产物失败时不公开；人工证据缺失时会明确返回 `awaiting_acceptance`，含缺少的检查和候选标识，这表示候选就绪、未发布成功。

- 修复失败原因或补齐真实回执后，在 [Release工作流](https://github.com/NightingaleWK/aha/actions/workflows/release.yml) 选择Run workflow，或等待下一次main提交触发。每轮扫描最早未发布的可信已合并发布PR，能够恢复错过的main事件。
- 上传先保存build-info，记录同次Actions资产及run id。上传中断时下载原运行的已验证资产补传，保留原EXE字节，不用新打包结果冒充同一候选。原运行资产保留14天。
- 原运行资产过期、草稿已有冲突文件或标识不一致时停止，维护者审阅后处理自有未公开草稿再重建；重新生成的EXE需要重新匹配回执。程序不自动删除不明草稿。
- 已公开版本只允许核对后返回已有成功；资产或提交不匹配立即失败，不移动标签、不覆盖文件。修复公开版本应发新patch。
- 未处理完的候选期间不继续准备可能混淆版本基线的新发布PR。
- 如果公开成功后标签更新中断，下一轮会先核对已公开版本的提交、正文和资产，再修复pending/tagged标签，最后才让Release Please准备下版。删除已经缺失的pending标签视为幂等成功。

main的push检查使用事件before SHA作为比较起点；手动运行或初始零SHA使用最近已公开版本源码，尚无公开版本时使用显式bootstrap，不能把当前HEAD当作默认起点跳过实际变更。

`build-info.json`记录版本、源码SHA、产品/专项/配方指纹、完整实际运行时及其摘要、EXE SHA256和自动验收范围。机器JSON和SHA256SUMS固定UTF-8/LF，源指纹规范化文本换行，二进制及最终EXE按原字节校验。`SHA256SUMS.txt`同时校验EXE与build-info。PyInstaller不承诺跨次构建字节完全相同，发布和验收始终以最终选用的同一份字节为准。

## 一次性仓库设置

核对仓库 [Actions设置](https://github.com/NightingaleWK/aha/settings/actions)：允许本仓库工作流运行，允许使用固定的官方actions和Release Please，允许GitHub Actions创建PR。各job在YAML中按需申请权限，普通PR测试不拥有仓库写权限。

如果日志显示 `GitHub Actions is not permitted to create or approve pull requests`，在上述页面的Workflow permissions中勾选“Allow GitHub Actions to create and approve pull requests”并保存。开启后让正在运行的下一次准备流程继续，或只重跑已失败的准备作业；成功的质量检查无需整轮重做。

无需个人电脑常驻或预置个人访问令牌。默认GITHUB_TOKEN创建的机器人PR事件可能等待人工批准，所以流程在生成文件更新完后显式dispatch CI到最终HEAD；分支继续变化后旧成功结果无效。若配置必需检查，应在真实运行后选择正确的Windows quality检查，并确认它绑定最终HEAD，不通过取消保护规则绕过失败。

设置PR和首次发布PR合并前，保留维护者审阅决定。真实GitHub检查、候选构建、人工验收和正式公开发布分开记录；仅本地测试通过不等于已验证整条远端链路。
