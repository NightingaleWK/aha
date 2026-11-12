# 当前唯一资料的一致保护副本

- 时间：2026-11-12 09:39:16，北京时间。
- 路径：`C:\Users\djsyw\AppData\Local\aha-recovery\device-continuity-20261112-093916-f77800da`。
- WSL路径：`/mnt/c/Users/djsyw/AppData/Local/aha-recovery/device-continuity-20261112-093916-f77800da`。
- 脚本：[protect-current-data.py](protect-current-data.py)。Windows原生SQLite只读事务与backup API，包含已提交WAL；未运行源checkpoint或迁移。
- `aha.sqlite3`：176,910,336字节，SHA256 `84495e4f1e7d1e0f7a48c5883d92dbdc24ec53a17ef37c9dc1ac33f6a7a37216`。
- manifest complete=true；quick_check=ok；foreign_key_violations=0；detail=39,346/rollup=117与源一致；revisions引用包0。
- objects/packages/backups完整保留（当次空）；未复制runtime认证、运行锁、临时目录、CCS或聊天。
- 这是持久恢复资料，不能随任务临时文件清理。原库未替换；尚未做新程序业务恢复验收，不能把SQLite完整性检查说成整个恢复流程已通过。

## 实施前原生复核

2026-11-12 09:49:10重新建立第二份副本 `C:\Users\djsyw\AppData\Local\aha-recovery\device-continuity-20261112-094910-741c6b9d`；同样176,910,336字节、SHA与上文完全相同、quick_check=ok、外键0、detail39346/rollup117。进一步通过Windows原生Python与PowerShell列目录确认两份副本均存在；WSL DrvFS目录视图未显示新建恢复目录，不能据该视图断言Windows文件丢失。原生复核时旧aha已退出，无runtime/WAL，真实台账未被本任务更改。
