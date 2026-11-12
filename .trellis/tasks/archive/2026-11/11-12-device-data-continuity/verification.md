# 最终集成验收（2026-11-12）

实施、当前真实资料接续与Windows桌面成品交付均已完成。用户已确认具体清单并完成36文件工作提交`c7c6acc87531df6ebb8ed5bc346a624490e8ac0a`，提交源码与交付产物对应的指纹一致，见research/commit-association.json。父子任务随后按Trellis流程归档，最终状态以同目录task.json为准。发布选择为“积累到下一版”；没有推送或公开发布。

## 真实资料结果

- 用户仅使用新电脑；旧电脑已格式化。本次从现有台账恢复可用历史，不依赖旧机，不从日汇总编造明细。
- 最初“页面无数据”的直接原因是所选当天无记录，同时新CCS25同步不受支持；用户确认来源缩水并未删除历史。现已兼容25，并增加空时段说明与查看全部历史入口。
- 写入前使用SQLite一致备份保护数据库及已提交WAL；先在恢复副本验证，再对当前默认资料进行用户已授权的来源绑定与同步。
- 旧39,463条事实（39,346条明细、117条日汇总）、全部项目归属与5个项目均逐项保留；117条汇总中原有7条被明细替代，110条继续参与核算。
- 本次实际补入2,757条新明细，368条相同记录去重，修订0、待核对0；随后重复同步新增0、修订0、待核对0。
- 接续完成时有42,103条明细、110条有效日汇总，覆盖2026-06-17至2026-11-12；当天605条。全历史按既有口径计77,603条代表用量，该数不是物理明细条数。
- 当前默认资料位于`C:\Users\djsyw\AppData\Local\aha`。从桌面成品启动，并通过Explorer再次打开验证复用同一ready实例；保留运行供用户使用。

终态证据：[primary-continuation.json](research/primary-continuation.json)。

## 完整备份与实际存放

持久恢复目录：`D:\aha-backups\20261112-device-continuity`，不按任务临时数据清理。

| 文件 | 用途 | SHA256 |
| --- | --- | --- |
| `aha-latest-before-continuity-836ce844.aha-backup` | 最后一次真实接续前完整备份 | `b225af73cebcb2f42baabeb74049484f6cf84ddfc3e2ea5fa9cd08f62f0e467d` |
| `aha-after-continuity-20261112-110508-ee88dc.aha-backup` | 接续后的完整备份 | `3cf244a9fbf861308909c2e2115319c6d35c3f234ff32d034882d3efa512f068` |
| `aha-before-continuity-20261112.aha-backup` | 较早的原始台账保护备份 | `5279dfdc7b35e43a7324dc52177a94c71bb984b96c46257bc989e3ce9c5cb7b3` |
| `aha-0.4.1-before-continuity.exe` | 原程序回退副本 | `0c25c25da9df56f7b82e7fe4cbce9f20613e1e82172c2ac9b620c2b77b0e8f58` |

完整备份包含台账、项目、归属、核对、占用和全部历史/作废原包，区别于CCS SQL用量导入。还原校验后生成独立新目录，保留当前库；恢复副本与默认目录独立，须按恢复结果的命令再次打开。设备标识独立于台账且不进入备份，新设备需要确认新来源；历史消费继续去重，有差异时保留核对。实现范围是单向迁移接续，不是多个报销业务库的双向合并。

原生AppData保护快照曾被Windows重定向到Codex的LocalCache，已核实原件仍在；另行保存上述D盘完整备份，避免恢复只依赖应用缓存。原始保护快照也保留，具体路径见[recovery-snapshot.md](research/recovery-snapshot.md)及[persistent-recovery.json](research/persistent-recovery.json)。

## 检查与最终成品

- 最终冻结源码：Windows CPython3.12.16 x64 / SQLite3.53.1，完整Python测试317项通过，失败0、错误0、跳过0。60个产品、测试和verifier文件起止SHA一致；Ruff、strict mypy24文件、compileall、3个JS语法、Node34项及diff检查通过。完整日志、失败夹具修复说明见[独立检查报告](research/check-report.md)。
- Directory与OneFile各自实际执行原生验收，覆盖CCS23/24/25、SQL25、未知26拒绝且保留历史、完整备份下载/分块上传/新目录恢复/重新绑定/去重、报销占用与冻结原包、重开和退出清理。
- 两个最终构建均使用真实Edge157，5种宽度无横向溢出/JS错误；完整备份还原、来源绑定、核对后按原意图自动重预览及可见combobox焦点通过。Excel16 COM核对3行23列、39项精确数值及文本；A4单页材料精确金额保持。证据位于`.aha-data/device-continuity/directory-ui-final`及`onefile-ui-final`。
- 最终OneFile已复制到系统桌面`C:\Users\djsyw\Desktop\aha.exe`及原程序位置`D:\Program Files\aha.exe`，Windows与WSL逐字节SHA一致；实际桌面副本又独立执行完整原生验收，并已启动真实资料接续。
- 最终OneFile：10,089,470字节，SHA256 `5f34fe26f9efda64c46aed32a8eacb90af4af9c54426650f4b1f48fa5fcef888`。
- 最终Directory：SHA256 `23bded8a1d8324b456ed029c79ae2083c4375b1c58bcca21162c0be0bd16f348`。
- 产品版本仍为0.4.1，本机成品是未公开发布的修复构建；版本由发布PR统一递增。本轮最终源码依据为WORKTREE，full指纹`5e5a934c156b8056b79a5596f85d40d20341c2f834e3a312025eee6c10f5c0f1`，具体运行时/其他指纹见[delivery.json](research/delivery.json)。

## 清理与发布边界

任务自有Windows根（失败/成功QA环境、隔离profile、副本、构建物和缓存）按明确清单、进程占用和链接边界核实后清理；保留主环境、最终成品、真实资料、设备配置、所有持久恢复资料和必要验收证据。实际结果见[cleanup.json](research/cleanup.json)。

最近公开版为[v0.4.1](https://github.com/NightingaleWK/aha/releases/tag/v0.4.1)。公开版之后其余main变化为文档/交付记录，本次累计用户变化为完整备份还原、换机接续、CCS25兼容，保留3条中文片段。建议候选v0.5.0，原因是新增完整恢复能力并修复数据安全与正常同步问题；建议补齐条件后尽快发布。中文预览见[whats-new-preview.md](research/whats-new-preview.md)。

正式发布尚缺：云端固定Python3.15.2配方与本地已验收3.12.16运行时对齐、对应云端候选及门禁、物理托盘点击验收。Computer Use在初始化阶段被宿主sandboxCwd URI错误阻断；无输入发生，不能将HTTP生命周期或托盘已启用计为物理点击。未推送分支、未创建发布PR、未公开Release；用户已选择“积累到下一版”，保留全部待发片段与上述发布缺口；本次不继续发版准备，不推送或公开发布。
