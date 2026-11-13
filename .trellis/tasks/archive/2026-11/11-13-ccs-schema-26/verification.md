# 验收与交付：CCS 26

## 结果与源码依据

- 2026-11-13（Asia/Shanghai），实施、检查、原生交付与临时文件清理均完成。用户已批准两组本地提交及归档，并选择先补齐0.5.1发版条件，授权创建修复PR、CI及候选准备；公开发布未获授权。
- 分支：`codex/ccs-schema-26`，起点 `4a8baf1a071b70c8990ac72c6f4a958a65f20a9f`。唯一产品源码修改是 domain 的显式外部版本集合增加26；内部投影23、应用schema4、材料manifest4不变。
- 构建基于工作树；产品full指纹 `55e634caa45d7cff1471ab7f8313350509a67719328ef405e2ed6ceed2ce8569`。构建、交付与清理后均核对一致，未在最终构建后修改产品源码。
- 代码提交 `48939350113fb9918413623e7b6b4e000b0d7644` 的产品指纹与被测工作树逐项一致，成品可据此追溯。
- 运行时为Windows x64 CPython3.15.2 / SQLite3.53.4及固定构建依赖；摘要 `2d64ab084e0aa6c3d8ffab874ef7a08fd35b4fbf452dc1353e89d06dc7ea8642`，与真正公开v0.5.0相同；主解释器保持原样。

## 检查与AC映射

| 范围 | 实测结果 | AC / 证据 |
| --- | --- | --- |
| 全部Python测试 | 351项通过，无跳过/失败 | AC1–4；research/check-full-tests.log |
| 针对性来源/Store/HTTP/材料 | 26+29+18+6=79项通过，包含在完整suite中 | AC1–4；research/implementation-report.md |
| Ruff / strict mypy / compileall | 通过，mypy检查26个源码文件 | AC5；research/check-report.md |
| JS语法/状态 | 三个脚本语法检查通过，53项状态测试通过 | AC5；research/node-checks.json |
| 中文片段与发布校验 | v0.5.0→WORKTREE校验通过 | AC5；research/check-release-wsl.log |
| Directory | 真EXE、HTTP/资源、23→24→25→26、SQL26、27失败/26恢复、旧包/完整备份、重开/重启/退出通过，托盘启用 | AC1–5；research/directory-verification.json |
| OneFile | 同上述独立检查通过 | AC1–5；research/onefile-verification.json |
| 实际桌面文件 | 独立重跑原生验证、主要功能/原包/重开/重启/退出通过，交付SHA与OneFile相同 | AC5；research/desktop-delivery.json、desktop-verification.json |
| 原生Edge页面 | Directory/OneFile/桌面分别验证26启动成功、27错误仍可查询历史、26手动恢复及无重复 | AC1/3/5；research/ui-*.json、ui-*.png |
| 原生Excel | Directory/OneFile分别以Excel COM打开两个CSV，逐单元格核对、无公式 | AC4/5；research/office-*.json |
| A4打印 | Directory/OneFile分别生成一页A4 PDF，精确金额保留，渲染图已查看 | AC4/5；research/a4-*.png、office-*.json |
| 真实CCS26 | 只读同步至本任务隔离台账成功；改为未确认来源被正确拦截且历史保留；不访问真实aha，不记录个人用量值 | AC1/3/5；research/real-source-verification.json |

Excel/打印为本次新执行；托盘/构建配方指纹未变，且生产运行时一致，没有把历史托盘确认冒充本次物理点击。`local-acceptance.json`记录真实证据与工作树指纹；`.release/acceptance/ccs26-materials.json`已绑定上述代码提交，使用标准acceptance_missing核对相同运行时后，当前适用专项缺口为空。此结果不代表未来云端候选已构建或发布。

## 成品

- 位置：Windows系统桌面 `C:\Users\djsyw\Desktop\aha.exe`，双击运行的单文件程序。
- SHA256：`77894d2128ddcd44eb130065ac39154d58439bbd7f08896a0492f3771aaab83b`。
- 目录版SHA：`0b0eafe80e2db9f61c535681ca62f7ae6f585ae1590b9f2e686213db65b6bcea`；目录版完成验收后才构建OneFile。
- 当前源码/PE产品版本仍为0.5.0；这是带26修复的本机工作树构建，不能冒充新的公开0.5.1版本。正式版本由发布PR统一递增。
- 桌面原同名文件不存在，无覆盖未知文件；从实际桌面路径启动过，全部验收实例已退出，私有运行描述符已清理。

## 验证脚本问题的处理

- Windows Git对WSL UNC仓库的release元数据命令失败；相同校验改由WSL本机Git执行并通过，原失败日志保留，没有放宽产品规则。
- 第一次浏览器脚本用字符串JS等待被产品CSP拒绝；改为Playwright元素断言后全流程通过，未修改CSP。原失败日志 `directory-ui.log` 和重跑日志均保留。
- 真实源测试最初把切到另一个不存在的路径预期为source_unavailable；现有合同先要求来源绑定，实际正确返回source_binding_required。修正测试预期后通过；没有改产品迁就错误夹具。
- 清理首次检测到Edge在合成profile中创建的6个Content.IE5目录联接而拒绝继续。逐项查明目标均为同一合成profile的IE缓存后，仅解除联接自身，再盘点和清理；未跟随联接目标删除外部资料。

## 清理

核实任务归属、全部路径及进程占用后删除任务自有Windows根目录，包含额外venv、私有运行时、构建目录、缓存、合成资料和真实来源的隔离验收副本，共657,622,734字节（627.16MiB）。保留桌面EXE、源码、原始自动检查/构建/验收日志、小型JSON报告、截图及来源指纹。真实CCS、真实aha、主解释器及恢复资料均在清理范围外。

清理后任务根目录不存在，桌面SHA仍相同，主解释器文件SHA未变。证据：research/cleanup-inventory.json、cleanup.json、cleanup.log。

归档文本按仓库`.gitattributes`统一LF，保留完整stdout/失败及重跑内容；JSON证据摘要在换行规范化后重新计算。PNG、EXE及业务原包的SHA均按原始二进制字节核对。

## 发布评估

最近真正公开版本为v0.5.0（2026-11-12），远端main之后仅有验收/归档/日志，无新产品代码或变化片段；本次累计待发用户变化只有CCS26兼容修复。建议尽快发patch v0.5.1，解决正常同步被阻断的问题。

What’s New预览：**支持 CC Switch 26 的用量同步**——修复结构版本26无法同步，支持数据库与SQL备份，保留23/24/25兼容及既有历史、归属、占用和材料。

本机适用检查齐全；本地提交/归档已获批准，随后按新授权继续功能PR/CI和候选准备。发布PR、固定候选的云端构建/自动验收仍按真实流程执行；公开发布尚未获授权。详见research/release-assessment.md。
