# v0.5.1正式发布与桌面更新

## 授权及完成结果

用户于2026-11-13明确要求“现在发布 v0.5.1，桌面 EXE 也更新为正式版”，并选择沿用现有记录、不新建Trellis任务。本记录补充此前只准备候选的阶段，不回写历史验收事实。

- 正式发布：[v0.5.1](https://github.com/NightingaleWK/aha/releases/tag/v0.5.1)，北京时间2026-11-13 10:05:56公开，非草稿、非预发布。
- 发布PR #12已合并，标签与正式源码均为 `f044119cb683ac7c118abf7b7abe00e3f0416452`，PR已正确标记`autorelease: tagged`。
- [发布流水线43348039818](https://github.com/NightingaleWK/aha/actions/runs/43348039818)全部成功，固定同一源码完成质量检查、Directory/OneFile构建与原生验证、资产校验、公开及状态回写。
- 发行内容仅为已确认的CCS26兼容修复：支持26数据库/SQL用量备份，继续兼容23、24、25，保留历史、归属、占用及材料。What’s New与已审阅候选的SHA一致。

## 正式资产及桌面成品

- 下载并独立核对GitHub正式EXE、`build-info.json`和`SHA256SUMS.txt`的资产digest、文件SHA、字节数、源码、版本与源码指纹；没有以本机旧包更名代替正式资产。
- 正式EXE与桌面副本SHA256均为 `af79950072a347461f686f2c986d1a36182ceccab178aa3d8d926f49ca6dd01f`。
- 桌面位置：`C:\Users\djsyw\Desktop\aha.exe`，通过Windows系统桌面接口确认。文件属性与HTTP均为**0.5.1**；从实际桌面文件执行过独立验证。
- 本次桌面旧文件确认为上一轮临时修复版，SHA为`77894d2128ddcd44eb130065ac39154d58439bbd7f08896a0492f3771aaab83b`。恢复副本保留在`%LOCALAPPDATA%\aha-program-backups\before-v0.5.1-77894d2128dd\aha.exe`，有独立归属标记。
- 更新时无正在运行的桌面aha实例，无须结束用户进程；真实aha台账未打开、迁移、还原或重建。

## 实际验收及边界

云端主线质量与构建作业分别通过351项Python测试、Ruff、strict mypy（29个源码文件）、compileall和53项JS状态测试；Directory和OneFile分别实际运行通过。完整云端原始日志保存在`release-v051-cloud-*.log.gz`，解压后内容完整，保留行尾空白；原始/压缩SHA见`release-v051-cloud-logs.json`。

正式下载的EXE和实际桌面副本分别再次在原生Windows中启用托盘，使用独立合成profile/data-dir验证：PE/HTTP版本、资源字节、23→24→25→26同步、SQL26、未知27失败/26恢复、历史与占用、冻结原包、完整备份/独立还原、重开、完整重启和退出/描述符清理。证据分别为`release-v051-official-verification.json`与`release-v051-desktop-verification.json`。

实际成品构建运行时摘要为`2d64ab084e0aa6c3d8ffab874ef7a08fd35b4fbf452dc1353e89d06dc7ea8642`，与已验收生产运行时一致；从核对过正式EXE字节的build-info读取并按固定配方重算。QA解释器另为Windows x64 Python3.15.2 / SQLite3.53.1，仅用于生成夹具和驱动外部EXE，不冒称它是冻结程序内部SQLite。

本次只在已验收产品基础上统一升版本，相关指纹与已有材料/托盘专项及运行时匹配；沿用既有适用专项记录。本次没有重新声称物理托盘点击、浏览器交互或Office专项通过。

## 清理及后续

验收完成后核实归属、文件边界与运行占用，删除本轮轻量QA环境、正式资产下载副本、合成验证库等15,081,888字节（14.38MiB），保留实际桌面成品、必要旧程序恢复副本、原始日志、校验清单、构建信息和小型报告。任务Windows临时根目录已不存在，桌面SHA在清理后仍匹配；真实业务资料与主解释器保留。

v0.5.1已正式发布，本轮用户可感知变化全部发布；本轮无额外待发功能、无新版本或What’s New片段需求。发布及交付已获授权并完成，无需重复征求同一发布授权。
