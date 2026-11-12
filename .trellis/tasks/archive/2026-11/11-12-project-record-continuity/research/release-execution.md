# 正式发布执行记录

用户明确授权：现在发版、合并main、git push、提交/归档/日志；本人功能实测确认无问题。

## 当前公开基线

GitHub只读核对latest仍v0.4.1，source 8898451cde00956d32edd0585b8b68690ea3307d；远端main bd15745270dda6e3b6fb8dc0e96953fbe5e8d7c8，当前无打开PR。累计计划v0.5.0，中文候选预览已包含4组产品变化。

## 执行边界与推进

1. 本地功能提交并推送功能分支，审查/合入main；机器人生成正式发布PR统一递增版本。
2. 核对发布PR最终HEAD CI、版本与累计What’s New后合并；冻结merge SHA M，云端Directory/OneFile构建。
3. 本机原生3.15.2/SQLite3.53.1可用，建立新任务环境，与云端候选实测绑定；旧3.12.16证据保留，不冒充新运行时。
4. 托盘人工场景已向用户请求缺失事实，复用已有总体发布授权，不重复审批发布。
5. 正式公开与资产核对完成后，交付正式EXE、清理本轮发布资源、归档任务/记录日志并推送最终main。

## 已实际完成的推进

- 功能提交da826a7；首轮PR CI在Windows8.3短/长路径断言失败（350/351），只修测试与质量规范后提交9dcf2e9；最终PR CI运行43178513550全部通过。
- 功能PR #9已合入main，merge cb8c6da0f4996a6370fa016b08236b4d607f5506；main Release运行43179495935质量/inspect/prepare通过。
- 机器人发布PR #10正确生成0.5.0：仅权威版本/manifest、技术CHANGELOG、四片段候选登记与累计中文版说明。最终HEAD64399a3d68827875119729d7ee26c0aa766b67e3的显式dispatch CI43180484300通过；机器人pull_request事件的action_required未冒充测试通过。
- 发布PR #10已合并，固定生产源码M=12d213b5b3c3c505d24f73fc7888966f24435337；本地main已ff到M，normalized四组指纹与已测功能源码完全一致，release inputs通过。
- 本机生产匹配环境：可信只读支持workflow临时分支编译官方固定zstd0.25.0的cp315 wheel；公开0.4.1 EXE哈希验证后只提取SQL3534文件到任务私有运行时，未执行旧EXE、未修改base/global。最终installed runtime2d64ab084e0aa6c3d8ffab874ef7a08fd35b4fbf452dc1353e89d06dc7ea8642与生产匹配。
- 本机3534环境对9dc源码351项全部通过（477.472秒），Ruff/mypy/compileall通过；检测前后产品指纹相同。M只改变版本字符串，指纹等价已独立重算，0.5.0成品仍需实际构建和验证。
- 用户明确确认已交付版本三项托盘正常，记录于release-user-tray-confirmation.json；该版本实际为本机3.12.16的9ccd字节，不将其改写成未来315候选已物理测试。
- M的实际云端Release运行43181532576正在执行；正式产物/适用验收/公开及最终交付与归档均未提前记通过。

## 最终正式发布与收尾

- v0.5.0 已正式公开：https://github.com/NightingaleWK/aha/releases/tag/v0.5.0 ，发布时间2026-11-12T08:51:47Z；实际tag/source均为12d213b5b3c3c505d24f73fc7888966f24435337。功能PR#9与发布PR#10均已合入main，六项验收回执提交cae26d6已推送。恢复workflow43185710907质量/inspect/candidate/prepare全部成功，build跳过，复用原草稿字节。
- 正式云端EXE/实际Desktop及D盘既有程序SHA均8991fa71cadd906678cb1b76d302921d1e874f022918f854a0540f2bb3d0e4d5，版本0.5.0；公开build-info与SUMS独立下载核对，源码/notes/runtime及标签一致。见release-publication.json。
- 新生产匹配Python3.15.2/SQLite3.53.4：351项Python全部通过、Ruff/mypy/compileall通过；Directory与确切云端OneFile分别完成原生检查及9项归属UI、Excel/A4与逐页图检查；实际桌面同SHA文件再次完整原生检查通过。六scope回执.release/acceptance/v0.5.0-project-continuity.json绑定真实M、生产runtime与实际证据，不修改旧312记录。
- 用户明确确认当前桌面最终v0.5.0三项物理托盘正常，见release-user-tray-v050.json；与先前312测试分开记录。
- 原实施root逻辑1,364,373,147字节已先清理；本次发布root另585,271,718字节已清理，D盘acceptance-records-v0.5.0保留1,798,354字节小型合成材料/QA记录。真实默认库、全部持久备份/回退EXE、最终成品、基础解释器和源码均保留。清理后默认程序健康并能重开同一服务，见release-cleanup.json及release-after-cleanup-runtime.json。
- 当前没有已知待发布产品改动；收尾仅规范、验收记录和Trellis归档/日志，不据此新增0.5.1。剩余人工待归属仍按业务清单继续处理，不伪造全部消费已归属。
