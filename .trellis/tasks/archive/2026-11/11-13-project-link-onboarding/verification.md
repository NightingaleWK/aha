# 目录整体项目关联验收

日期：2026-11-13。状态：产品实施、本机验收、桌面交付和临时物清理完成；功能已提交803bffc，按批准执行归档/会话记录，用户选择积累到下一版。未推送、未公开发版。

## 实际交付

- 系统桌面接口确认位置：`C:\Users\djsyw\Desktop\aha.exe`，单文件EXE，双击使用；当前源码版本仍为0.5.1，本机改进构建不冒称新的正式公开版本。
- SHA256：`f04c016789ee03c75d8e3b2d21722aefc616968826e7811bc11d2d80bd76fb3c`；桌面副本与验收OneFile逐字节一致。
- 分支：`codex/project-link-onboarding`；功能提交`803bffc6cf6a21a5b4b6decc6038f76ef144d703`与构建时最终工作树指纹一致，源码依据见[指纹](research/source-fingerprints.json)。最终源码指纹复核未变。
- 原生Windows x64 CPython3.15.2、SQLite3.53.4及固定构建依赖与当前公开成品运行时一致，runtime SHA为`2d64ab084e0aa6c3d8ffab874ef7a08fd35b4fbf452dc1353e89d06dc7ea8642`。未修改基础解释器DLL。
- Directory、OneFile和实际桌面副本分别原生启动，HTTP资源与最终源码逐字节比对，业务、材料、重开、完整备份独立还原、退出和描述符清理均实际执行。对应[目录版](research/directory-verification.json)、[单文件版](research/onefile-verification.json)、[桌面副本](research/desktop-verification.json)及[交付记录](research/desktop-delivery.json)。

## 产品结果与验收映射

| 范围 | 实际证据 |
| --- | --- |
| R1–R3 新建/编辑、目录整体历史、旧人工例外 | 17项新增业务测试；原生Edge从UI选择目录、预览65条跨页历史（含旧人工分到其他项目的1条），取消无写入，确认全部统一归入 |
| R4 自动接续 | 65→67条：旧会话和新会话新增自动归入；迟到目录识别后67→68条；未人工逐条选择 |
| R5 目录转移 | 第二个项目接收整目录68条，原项目目录和成员同步移除；继续同步新增后新项目69条 |
| R6–R8 换机、旧项目接续、缺依据 | 唯一有效历史依据、Windows/UNC和Linux边界、新机路径追加、旧日志缺失、停用目录、零历史绑定及超限均有业务测试；不猜无目录日汇总 |
| R9 旧入口与常用UI | 普通记录表只读，旧人工控制收纳高级区；已纳管目录的相反旧接口被明确拒绝；常用编辑不出现逐条/整会话开关 |
| R10 守恒与材料 | 业务测试含80条已占用明细整体迁入与旧ZIP不变；真实一致副本验证事实/版本/claims/总费用不变；原生材料与Excel/PDF另见下节 |
| R11 异常状态 | 66项Node状态测试含关闭/替换/迟到成功409断连、未知提交同key重试、已提交刷新失败只读重试；检查代理发现并修复提交后关联刷新漏传调用方身份的问题，新增两条修复前失败的回归 |
| R12 成品 | Directory/OneFile/Desktop分别完成原生程序和真实Edge新流程，1440/1366/1280/430/375视口、长名称、Escape、无JS异常、退出清理均通过；物理托盘输入未声称通过 |

## 源码检查

- 全量原生Python unittest：369项，退出码0，[持久报告](research/check-full-final-result.json)、[完整日志](research/check-full-final.log)。
- Node页面状态：66项通过；三份JavaScript语法、Ruff、strict mypy、compileall、git diff --check通过；[全范围复核](research/review-result.json)。
- 首次完整套件已输出369项OK，但外层长命令报告器被终止，未伪造退出码；随后使用独立进程/持久报告器重新完整执行并取得退出码0。
- 发布输入校验在Linux对真实公开基线提交和WORKTREE执行通过，[报告](research/check-release-final-result.json)；没有把未拉取的本地v0.5.1标签或Windows UNC Git失败写成通过。

## 真实副本及证据

- 原用户库只以SQLite `mode=ro/query_only`创建一致副本，不在原库初始化Store；只在任务私有副本上应用新目录整体确认。
- 副本中目标记录原为1,004条（用户在此前排查后已归入项目），确认后仍为1,004条，全部更新目录整体依据；事实/版本/报销占用及总费用保持。
- 原用户packages为空，本次真实副本没有旧ZIP可验证，不能把“0个原包”宣称为真实材料回归。合成80条占用/旧ZIP不变测试，以及三种真实EXE的材料保存/重下/还原另有实际证据。
- 详见[真实副本回归](research/real-copy-regression.json)。没有直接改写真实项目归属。

## Excel、打印与物理输入边界

- Directory和OneFile的合成CSV分别通过原生Excel COM打开并逐单元格核对，明细4行、每日汇总2行，未产生公式或金额损失；浏览器生成A4 PDF并检查精确费用、页面尺寸和渲染。对应[目录版](research/office-directory.json)、[单文件版](research/office-onefile.json)。
- 全部新流程截图保留在Codex本机visualizations目录，不进入Git；[桌面UI报告](research/ui-desktop.json)记录实际路径。
- 原生EXE均保留托盘并自动验证启动/退出；物理托盘双击和菜单点击未完成。Computer Use初始化被WSL sandboxCwd错误阻断，见[缺口](research/physical-tray-gap.json)。没有用程序发送消息冒充物理交互，也不声称物理Office点击。

## 清理与运行状态

- 核实根目录任务标记、来源、无运行占用和全部目录项后，清理独立venv、私有运行时、pip/检查缓存、合成库、真实私有副本及构建中间物，删除11,912个文件，共743,234,710字节（708.80MiB）。
- 10个浏览器兼容junction均先核对目标仍在任务根内，再仅解除链接；没有遍历到外部路径。
- 桌面成品、真实CCS/aha及恢复资料、基础解释器和源码均保留；清理后桌面SHA再次相同。详见[清理记录](research/cleanup-result.json)。
- 检查最终默认实例时没有正在运行的旧默认服务，无需强制停止或触发真实来源同步，见[实例状态](research/old-instance-transition.json)。

## 发版与提交状态

最近公开版为[v0.5.1](https://github.com/NightingaleWK/aha/releases/tag/v0.5.1)。公开源码至本次任务前HEAD无其他待发产品变更；累计用户变化为本次目录整体关联。建议积累到下一版，候选v0.6.0（feat升minor），产品号由后续发布PR统一更新。

[中文What’s New预览](research/whats-new-preview.md)与[发版评估](research/release-assessment.json)已准备。正式发布仍缺物理托盘专项和功能/发布PR、云端候选门禁。用户已确认[提交计划](commit-plan.md)，选择积累到下一版；按计划完成本地提交、归档和会话记录，具体提交以归档task.json及开发日志为准。未授权推送或公开发版。
