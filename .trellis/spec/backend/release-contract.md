# 版本与 GitHub 发布合同

## 1. 范围与触发

修改版本、构建、GitHub工作流、发布说明或发版门禁时阅读。权威产品版本仅在 `src/aha/__init__.py::__version__`；包元数据由setuptools动态读取，页面/HTTP/新材料沿用现有消费者，PE资源从同值生成。历史文档版本和冻结材料不回写。

普通功能PR随代码提供中文变更片段；main合入后Release Please准备发布PR，维护者合并发布PR才决定发版。程序本身仍离线，不新增资料上传或自动安装。

### 每项工作收尾的发版评估

开发代理在完成本次已授权的实施、适用检查、桌面成品交付和清理后，主动准备以下内容，再集中给用户选择。仅设计/文档任务按其交付范围执行，不为询问发版制造EXE或重复已有验收。

1. **实际变化及建议**：按最终代码和用户影响判断“建议尽快发布 / 可积累后发布 / 本次无需单独发布”，说明理由。影响核算正确性、资料安全或正常使用的已验证修复优先建议尽快发；小型改进可积累；无产品影响的说明、测试、日志和内部整理通常无需单独发版。需求或方案尚未实施不能计入已交付功能。
2. **累计范围及版本**：核对最近真正公开的Release、已合入但未发布的内容，以及本次尚在分支上的变化。分别说明实际版本与建议候选版本，累计待发内容按最高适用级别决定版本；没有公开前版时明确首次发布。纯文档任务无需单独发版，不代表之前积累的功能也无需发布；本机版本、标签或草稿不能冒充公开基线。无法查询远端时标为“尚未核实”，不虚构版本。
3. **具体可审阅结果**：保留用户可感知改动的中文片段，提供与候选范围一致的What’s New预览、可审阅PR/提交及实际验收结果，列出尚缺的CI、云端候选或本机专项。仅当前分支的预览必须标明范围，不能冒称完整累计版本。没有用户变化的任务说明“无需新增用户发布说明”，不编造亮点。
4. **用户选择及执行**：按当前状态给出清晰推荐，并在同一次提问中说明动作范围，选项含义如下。用户已有明确覆盖同一版本和动作范围的授权时直接复用；否则未回复不代表授权，不自行合并发布PR或公开Release。

| 选择 | 执行与边界 |
| --- | --- |
| 现在发版 | 本地交付及当前阶段应完成的检查、人工证据齐备时提供，表示进入已审阅的发布流程；明确拟合入的功能PR、发布PR、候选版本及公开动作。合并后的云端构建和自动检查仍须执行并通过，用户选择启动不等于发布成功。 |
| 先补齐发版条件 | 已知检查失败、缺少必需权限或人工证据、首次云端候选尚待本机验收时替代“现在发版”；列出缺口，继续范围内准备，正式公开仍受真实门禁及发布授权约束。 |
| 积累到下一版 | 保留已验收改动及未发布片段，记录累计待发内容，后续任务合并评估；仅按既有授权处理普通功能PR，发布PR保持未合并。 |
| 本次无需单独发版 | 适用于确认无产品影响的本次工作；保留既有待发内容及说明。用户可感知改动即使暂不发布，也必须保留片段并按“积累到下一版”记录，不能借此静默遗漏。 |

用户选择、建议版本、待发内容和验收缺口写入当前任务记录。延期发版不阻塞已满足自身验收标准的普通功能任务收尾；若真实发布本身属于本任务验收标准，保持相应项未完成，不以用户选择延期宣称发布成功。此评估发生在本地开发对话中，不增加程序弹窗、后台任务或新的GitHub发布开关。

## 2. 命令签名

```text
python scripts/build_windows.py --build-root PATH --stage Directory
python scripts/verify_windows_artifact.py --exe PATH --source-root ROOT --data-root PATH --report FILE
python scripts/build_windows.py --build-root PATH --stage OneFile --directory-verified
python scripts/release.py validate --base REF [--ref HEAD]
python scripts/release.py render --ref REF --base REF --version X.Y.Z --output FILE
python scripts/release.py fingerprints --ref REF --output FILE
python scripts/release.py runtime --ref REF --output FILE
python scripts/release.py validation-base [--ref REF]
python scripts/release.py discover --output FILE
python scripts/release.py reconcile
python scripts/release.py prepare-pr
python scripts/release.py bundle --exe FILE --directory-report FILE --onefile-report FILE --runtime FILE --candidate FILE --output DIR
python scripts/release.py stage --candidate FILE [--assets DIR]
```

完整参数以实际 `--help` 为准。`discover/validation-base` 使用 `GITHUB_REPOSITORY` 与令牌做只读远端查询；`prepare-pr/reconcile/stage` 具有明确远端写入作用，分别更新发布PR/CI、修复PR标签和处理草稿/正式发布。其他数据生成入口不能暗中创建正式Release。构建沿用既有原生Windows x64 venv及SQLite门禁。

## 3. 数据、权限与验收合同

- 版本PR统一升号：fix升patch、feat升minor；0.x破坏性变化升minor且明确升级说明，1.0需要显式审阅。Release Please显式更新真实导入包，不从发行名 `aha-usage` 猜成 `aha_usage`。
- `.release/changes/*.json` 的稳定id、分类、中文标题/说明及必要升级事项须与实际交付一致；已发布片段不可原地改写。What’s New按最近公开版本至候选最终树生成、去重，空栏目省略；在发布PR预览，正式发布时只填真实资产信息，不再自由改写产品描述。
- 发布代码SHA M固定为可信同仓库发布PR的merge SHA，版本、说明、EXE和标签必须对应它。后续main推进不能混入旧候选。默认令牌创建标签不会保证触发后续构建；同一编排直接执行，并显式dispatch最终机器人PR HEAD的只读CI。
- CI验证报告 `schema_version=1`，成功须有 `verified=true`、`executable_sha256`、`version`、`pe_version` 和实际检查范围。无桌面 `--no-tray` 不证明物理托盘操作；失败不得输出成功标记。
- 人工回执含 `schema_version`、实际测试源码 `source_sha`、北京时间 `completed_at`、full/tray/materials/recipe指纹、实际生产/构建运行时 `runtime_sha256`、真实 `checks` 及小型证据摘要。首次公开还须绑定 `candidate_source_sha=M` 和确切云端EXE `artifact_sha256`；缺少真实托盘点击不能把tray列入已通过。指纹须从真实测试提交重算，与目标候选核对；不存在的源码或手填不符指纹不能放行。
- 构建依赖及实际使用的传递依赖全部固定在 `scripts/requirements-build.txt`。实际运行时摘要包含Python完整patch、SQLite、位数/平台及这些固定构建包的实际版本，排除不随产品打包的QA工具；运行时变化须重新验收，不能只核对配方文件未变。
- 包版本清单按 `importlib.metadata.version(name)` 的活动provider解析；不能让后枚举的旧egg-info覆盖已安装dist-info，也不能删除主环境元数据来掩盖不一致。
- Git文本统一LF，发布JSON、Markdown和SHA256SUMS使用显式UTF-8/LF字节写入，避免Windows默认CRLF导致远端校验不一致。专项源码指纹允许规范化文本的CRLF/LF和唯一版本数字，二进制保持原字节；实际资产仍逐字节校验SHA256，不能借源码规范化放宽资产检查。
- 首次全面本机验收包括Directory、OneFile、浏览器、托盘、Excel及A4打印预览/PDF；以后每版自动验证原生EXE/HTTP/资源/材料/复开/退出。相关代码变化使对应专项失效，构建配方/运行时或未知生产模块变化保守要求全项；仅版本数字可在专项指纹内规范化，不能掩盖其他改动。
- 人工回执可后补到可信main，再恢复同一草稿M；它不改变打包源码。草稿EXE变化使其资产回执失效。CI只校验回执匹配，不声称自己重新执行Office或物理交互。
- 普通PR及构建只读；PR准备、dispatch及发布job按需要分别授权。不得在不可信源码执行中暴露写令牌，不拼接PR文案为shell，不记录运行凭证。

## 4. 校验与错误矩阵

| 条件 | 必须发生的结果 |
| --- | --- |
| 本次仅文档，但存在先前待发功能 | 本次无需单独升号；仍报告累计候选、未发内容及既有缺口 |
| 用户选择积累或没有回复发布选择 | 保留待发片段及未合并发布PR，不把开发完成当作正式发布授权 |
| 请求现在发布，但适用验收仍有缺口 | 明确缺口并先准备/补验，不降低门禁或声称已经发布 |
| 版本、候选SHA、说明或产物指纹不一致 | 阻断，不标签错误源码 |
| SQLite/解释器/Directory检查失败 | 阻断OneFile和正式发布 |
| OneFile或资产校验失败 | 不公开，可保留自有草稿恢复 |
| 首次/专项人工证据缺失或失效 | 可生成候选供验收，公开动作必须保持阻断 |
| 机器人PR继续更新 | 旧HEAD的绿色结果不能放行新HEAD |
| 发布说明缺失、重复id冲突或回写已发布片段 | 明确失败，不静默漏项 |
| 本地撤销未公开功能并删除其片段 | WORKTREE枚举排除已删除文件，不残留虚假说明或抛文件不存在；回退理由用internal片段记录 |
| 已公开同版本重跑 | 相同身份返回已有成功；冲突则失败，不覆盖资产或移动标签 |
| 草稿中断/部分上传 | 按版本和M独立恢复，不仅依赖release_created；资产改变须重新验收 |
| 已公开但PR标签更新中断 | 写权限job在准备下一版前幂等修复tagged/pending标签，不能永久堵住后续发版 |

## 5. 正常、基础与错误场景

- 正常：功能及中文片段合入main，机器人更新发布PR并检查最终HEAD；维护者合并后，M的Directory和OneFile通过，适用人工记录完整，上传/核对完成才公开。
- 基础：纯文档或内部归档不生成虚假的用户亮点；没有公开前版时使用明确首次范围和源码链接。
- 收尾：一次兼容修复已验收，最近公开版为0.4.0且没有待发功能时建议0.4.1；若累计已含新功能则建议0.5.0。当前任务若只是补维护说明，则本次无需单独发版，同时报告此前待发版本，不能再凭文档多升一个版本。
- 错误：本地测试通过就宣称GitHub已发版；用旧包改文件名当新版本；先公开空Release再等EXE；伪造Office/物理托盘回执。

## 6. 必须覆盖的验证

版本/元数据/PE一致及原门禁；多片段、撤销未发布功能、空/缺失/重复及breaking说明；精确M、默认令牌dispatch、HEAD迟到结果；草稿恢复/重复正式版/上传中断；人工指纹规范化、相关变化失效及first资产SHA绑定。原生EXE必须实际执行HTTP、材料和生命周期，不以解析脚本或静态字符串替代。

正式验收分别记录源码检查、本机成品、机器人PR、GitHub构建、首次人工门禁和真实Release下载；未执行远端链路时保持对应AC未完成。桌面交付与清理见 [交付规范](delivery-and-cleanup.md)。

收尾规则变更通过文档一致性审阅覆盖“修复单独发布 / 累计功能决定版本 / 纯文档但有待发功能 / 用户选择积累 / 尚缺验收 / 无发布授权”场景；只调整协作规范时检查引用和规则一致性，无需构建EXE或新增自动测试。

## 7. 错误与正确做法

```text
错误：机器人打标签 → 假设另一个工作流自动启动 → 先公开Release → 用旧绿色检查放行新HEAD
正确：固定M → 每版检查和构建 → 同M草稿/资产 → 适用真实回执与校验 → 正式公开
      机器人PR更新生成文件后取得最终HEAD，再显式触发只读CI。
```

发版失败保留证据并修复后重跑自有草稿，已公开内容的修复以新patch发布。
