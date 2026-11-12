# v0.5.0 最终回执只读复核

结论：**Ready，可提交本次回执和仅文档的元数据缓存说明，push 可信 main 后按既有流程复用原草稿发布。** 用户已经授权正式发布；这次明确的 v0.5.0 托盘事实也已补齐，无需重复审批。尚未在本子代理中执行公开动作，正式 Release/标签/资产状态以主会话实际执行为准。

本轮仅写本报告，未修改产品、测试、门禁、回执或 Git/远端。核对目标：`.release/acceptance/v0.5.0-project-continuity.json`，SHA256 `ada7c19107a1439e6b19541c6ed2ac04c6de39fb6348e169601ce805af25d24c`。

## 身份与字节

- 源码 M：`12d213b5b3c3c505d24f73fc7888966f24435337`；产品版本 0.5.0。
- 云端 EXE：`8991fa71cadd906678cb1b76d302921d1e874f022918f854a0540f2bb3d0e4d5`。
- 实际生产运行时：Python 3.15.2 / SQLite 3.53.4 / Windows AMD64，固定构建依赖摘要 `2d64ab084e0aa6c3d8ffab874ef7a08fd35b4fbf452dc1353e89d06dc7ea8642`。

独立读取已下载的 EXE、build-info.json、SHA256SUMS.txt 三份实际字节，SHA 全部与 `release-cloud-assets.json` 一致，SUMS 完整文本逐字节正确。build-info 绑定 M、该 EXE、版本与四组指纹；按 M 的固定依赖配方重算 runtime 与回执一致。

从 Git 对象重新计算 M 的 full/tray/materials/recipe 四指纹，均与回执一致，当前 WORKTREE 产品指纹也等于 M。将实际已测功能提交 `9dcf2e9efeb800d0b7e735107745f26af742571e` 与 M 比较，产品/配方仅权威版本字面量由 0.4.1 变为 0.5.0，规范化指纹相同；没有以旧 3.12 环境结果冒充新生产运行时检查。

另独立读取本机 Directory 与两份已交付程序的实际文件字节：Directory 匹配 `ecc8ce5ac743ac1e8413881d19cdbd4d5a92fb8cc5db006a2cc92b43f8e4df46`，桌面及既有程序位置均匹配该云端 8991…EXE。未打开真实业务库。

## 六项证据

逐个计算 evidence.sha256 对应报告的原始字节哈希，六项全部命中正确报告，没有悬空摘要或拿旧报告填新源码。

| scope | 实际证据与复核结果 |
| --- | --- |
| directory | `release-directory-verification.json`：M 本机生产匹配 Directory 的 PE、HTTP、资源、CCS23/24/25、备份/独立恢复、原包、重开退出均通过；独立 UI/Excel/A4 报告同样绑定 ECC8…字节 |
| onefile | `release-cloud-onefile-verification.json`：确切云端 8991…字节完整原生门禁通过；`release-desktop-verification.json` 再次完整通过，PE/源码/runtime/指纹一致 |
| browser | `release-native-ui-cloud-onefile.json`：确切云端 EXE 的 9 项归属流程、跨页80、未来继承、历史恢复/例外、五种宽度、81条材料与重开原包通过，console/page 错误均0 |
| tray | `release-user-tray-v050.json`：用户明确对当前 v0.5.0 回复“这份 v0.5.0 三项均正常”，对应菜单打开、双击重开、菜单退出后图标消失；M/8991…/runtime 与本次桌面交付记录 SHA 一致 |
| excel | `release-native-materials-cloud-onefile.json`：该云端合成材料经 Excel16 COM 逐格核对，81行23列明细、1行17列日汇总、日期语义及无公式通过；不声称物理 Office 输入 |
| print | 同一材料报告明确原生 Edge 一页 A4 PDF，精确金额、81成员及待归属说明保留；主会话实际逐页查看渲染图并记录结果，不声称纸质打印 |

新托盘确认的时间在新回执完成时间之前，交付报告哈希精确匹配。它是用户报告的物理操作事实，本子代理没有冒称亲自操作；先前 3.12 的确认没有被改填成此次证据。旧自动报告中的 `tray_physical_checked=false` 与这份随后独立的用户事实没有冲突。

真实默认库的前置全备份、事实/版本/项目/归属/审核/占用不变与同服务重开来自 `release-desktop-delivery.json`；本轮没有要求重新恢复或改写真实库。公开回执仅保留安全摘要，不包含该内部报告中的个人路径和业务聚合。

## 失效检查、权限与文档

实际调用 `acceptance_missing(root, M, WORKTREE, prev889…, 8991…, runtime2d64…, previous_runtime2d64…)`，并禁止任何隐式 fetch，结果为 `[]`。required_checks 仍是六项全量，没有修改门禁或借旧回执跳过新指纹检查。

拟附带的 release-contract 改动仅解释 PEP660/PYTHONPATH 活动 provider 与使用固定 setuptools 正常重建 egg_info 的处理，继续禁止手改版本、删除元数据伪造通过；与本轮实际 active provider、模块版本和 PE 检查一致，不改变生产配方、验收范围或发布权限。当前产品/配方与 M 无漂移；本轮未发现工作流改动。

回执字段、时间、源码及 digest 形状、六项 scope 和对应证据完整，正文人工检查与敏感字段/路径扫描均未发现个人路径、真实消费、启动 URL、Cookie、CSRF、令牌或其他凭据。可以公开该小型回执和上述文档补充；该结论不等于允许把包含私有运行凭证的内部临时文件一起提交。

## 首次 OSError 的边界

`release-cloud-onefile-first-failure.json` 真实保留 `verified=false`、`OSError`。它没有 errno/winerror、步骤栈或底层诊断，**根因仍未定位**，不能声称已证明是 Windows 环境、锁竞争或夹具问题。后续新增隔离 case 的同一完整 verifier 通过，确切云端 EXE 的 UI/Excel/A4 通过，实际交付文件又独立通过完整门禁；未为重试修改产品或验证脚本。

现有事实没有形成可复现的未修产品缺陷，也没有缺少规定的成功门禁，因此本复核不要求为这一条未复现观察再阻断发布。保留失败记录与成功 case 身份；如果再次出现，按已准备的安全观测方法记录当次 errno/winerror、失败步骤栈及所属子进程结果后调查，不能覆盖首轮失败或虚构已定位根因。

## Verification

- 回执/六 scope 报告哈希、M 指纹、实际三项云端资产字节与 SUMS、runtime 重算、实际交付文件 SHA：通过。
- 实际 acceptance_missing：空；回执及文档公开内容检查：通过；git diff --check：通过。
- Ruff、strict mypy、351 Python、新 UI/材料/物理操作：本次不重复执行，分别核对已有新生产运行时报告和用户事实；没有把读取报告写成重新测试。
- Git 提交、push、草稿恢复、正式公开与远端最终资产核验：本子代理未执行，由主会话继续已授权流程。
