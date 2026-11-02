# 独立检查记录

日期：2026-11-02。检查代理：`trellis-check`。已在实施代理交接后完成最终全范围2.2复核；范围包括版本来源、Windows构建/验证脚本、发布CLI、三份工作流、说明片段及相关规范。单仓库backend/frontend索引与质量规范均已读取。

## 审查发现并已修复

以下问题由实施代理/主会话按审查意见修复，最终代码和回归已重查：

1. **人工回执来源**：`acceptance_missing()`校验真实测试提交并重算完整指纹；`ensure_commit()`在main取回仍找不到时按完整SHA取回，支持squash/rebase后的测试提交。错误来源或手填不符的指纹不能放行。
2. **已公开标签身份**：`stage()`返回 `already_published` 前核对实际tag类型和M；已移动标签不能当成成功。
3. **公开后的标签恢复**：`reconcile`在写权限prepare job、Release Please动作前校验已公开版本源码/说明/tag/资产并幂等修复tagged/pending；已公开重跑也修复标签，DELETE404可重入。覆盖公开成功但标签写入失败后的完整恢复，避免上游工具永久因merged/pending阻断。
4. **真实main校验范围**：push传入 `github.event.before`，缺失或全零时通过 `validation-base`选择最近公开源码/bootstrap，避免直接main提交默认检查HEAD到HEAD。普通PR继续使用实际base SHA。
5. **实际构建运行时绑定**：主会话固定实际构建传递依赖；`bundle_runtime()`记录和校验Python完整patch、SQLite、venv及实际包版本。`runtime_sha256`只纳入平台/解释器/SQLite及固定构建包，不受无关QA工具或正常应用版本递增影响；人工回执必须匹配该摘要，实际运行时相对前版漂移要求全项验收。

最终复核阶段由检查代理直接修复：

6. **重复元数据provider覆盖活动版本**：`installed_runtime()`初稿遍历字典时，后遇到的旧源码egg-info可覆盖实际安装的dist-info。改为对唯一规范化发行名调用 `importlib.metadata.version(name)`，与解释器的活动provider一致；真实临时dist-info/egg-info双provider回归及原生实际0.3.1核对通过，没有清除主环境或共享egg-info掩盖问题。
7. **WORKTREE删除预览**：`files_at(WORKTREE)`初稿把缓存索引中已删除的文件也返回，撤销未发布功能时读取不存在片段而失败。现按实际存在文件枚举；增加删除未发布片段、以internal理由解释代码回退、且不生成虚假用户内容/空版本的回归，维护说明同步明确这一入口。

这些修改沿用已批准的版本、可追溯性、幂等恢复及首次/专项验收政策，没有引入新的业务范围。

## 最终独立验证

- Linux `unittest discover -s tests -p test_release.py -v`：最终25项发布回归通过，10.329秒；覆盖说明、版本/指纹、源提交、默认令牌最终HEAD dispatch、草稿/正式版本、上传及标签恢复、运行时漂移和新增两项回归。
- 原生Windows3.15.2对最终新增两项回归独立运行：2项通过，13.474秒；另核对实际活动 `aha-usage` 元数据和inventory均为0.3.1。
- `ruff check --no-cache src tests scripts`：通过。
- strict `mypy src/aha scripts/build_windows.py scripts/verify_windows_artifact.py scripts/release.py`：25个源码文件通过。
- 官方 `actionlint v1.7.12`：最终三份工作流实际校验通过；下载包SHA256 `8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8`与官方Release资产digest一致。
- Windows PowerShell实际核对资产名插值：预期 `aha-assets-<source SHA>-<attempt>`。
- `git diff --check`及本次维护/合同/报告的相对链接检查：通过。

复查确认普通PR/构建只读，PR写入/dispatch/发布按job分别授权；不以默认令牌标签事件触发构建，不用后来的main代码混入M；机器人生成完说明后才dispatch最终HEAD。UTF-8/LF机器文件与实际资产SHA逐字节校验一致，保留既有journal union规则。

## 未修复的代码问题与证据边界

本次最终复核没有留下需修复的已知代码阻断问题。完整原生Python/JavaScript、Directory/OneFile、浏览器、Office和桌面交付由主会话执行并另行记录，此处不冒称已独立重复执行。

物理托盘点击因桌面控制入口初始化失败仍未完成；没有伪通过回执，首次正式公开发布须保留该门禁。设置PR及首次发布PR的main合并、真实GitHub检查/构建和正式Release下载仍需按既定授权与AC分别留证，不能用本地通过或本报告代替。

## 审查临时文件清理

最终检查完成且工具进程已结束后，已删除本检查代理自有的actionlint二进制/下载包、mypy缓存和临时上下文副本，逻辑文件大小共12,534,636字节。保留本报告、源码、主环境及主会话的成品/证据；未按忽略规则批量删除任何路径。
