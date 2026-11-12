# 完整备份核心与CLI实施回执

日期：2026-11-12。子代理负责核心/CLI，未访问真实用户库、CCS或默认资料目录，未执行Git提交。其他代理的来源绑定、HTTP和页面更改均保留。

## 更改范围

- `src/aha/backup.py`：只读既有资料、SQLite backup一致快照（含committed WAL）、快照引用的所有修订原ZIP（含旧版/作废版）及objects、manifest/文件SHA、限额分块打包/校验、新目录还原。
- `src/aha/storage.py`：仅增加`create_backup`与静态`restore_backup`门面，绑定门面由另一个代理负责。
- `src/aha/__main__.py`：离线`--data-dir DIR --backup FILE`及`--restore-backup FILE --restore-dir NEW_DIR`；操作后退出，不启动服务、托盘或同步。现有启动参数保持兼容。
- `tests/test_backup.py`与`tests/test_backup_cli.py`：19项针对真实失败边界和业务恢复结果的合成回归。

## 固定接口与限制

`create_backup(data_dir, destination, *, cancel=None, shutdown=None)`返回`archive_path/sha256/size/created_at/format_version/store_schema_version/counts`；`restore_backup(archive, destination, *, cancel=None)`返回`destination/archive_sha256/restored_at/format_version/store_schema_version/counts/interrupted_runs`。

ZIP容器，manifest `format=aha-full-backup/format_version=1`，现有应用schema3不变。压缩包4GiB、展开16GiB、文件100,000、清单8MiB、中央目录64MiB、操作600秒；文件流1MiB分块。SQL上传128MiB协议不参与本模块。

清单与源资料均不含新增凭据；完整DB本身保留项目、源路径、历史设置等私有恢复信息，不是费用分享包。runtime、运行锁、temporary、嵌套备份目录、本机安装标识不打包；未知根持久文件会明确阻断，不静默丢弃。所有packages来自快照revisions的完整登记；未登记孤包不恢复也不删除。

还原必须是不存在且不嵌套于其他aha资料中的新目录。Windows `os.rename`、Linux `renameat2(RENAME_NOREPLACE)`做原子无覆盖发布；竞争者即使只创建空目录也不被覆盖。提取始终在同级独占staging，校验全部路径、大小/SHA、schema/不可变保护DDL、完整性/外键和原材料引用后才发布。

`restore-info.json`为恢复结果旁车：`format_version:1/restore_id:新UUID/restored_at/archive_sha256`，与来源代理约定据此要求重新绑定。无running/stage时恢复DB原字节与归档SHA一致；有未完成同步时，只在恢复staging标failed/sync_interrupted、清sync_stage/pricing，不改归档或已发布事实/版本/项目/报销/原ZIP。

## 实际验证

运行环境：原生Windows CPython3.12.16 x64 / SQLite3.53.1，任务自有qa312环境；通过父任务`research/run-native.py`运行，不放宽SQLite门禁。

- `python -m unittest discover -s tests -p 'test_backup*.py' -v`：**19项全部通过**，最终一轮13.368秒。
- Ruff检查本模块、CLI、Store及两个新增测试文件：通过。
- strict mypy `src/aha`，专用`mypy-backup`缓存：通过（运行时24个源码文件）。
- compileall本模块、CLI和Store：通过。
- Git diff空白检查：通过；只读检查到其他代理更改未回退。

覆盖：项目/规则/人工归属/会话、原事实/版本、有效占用与不可变事件、3个原ZIP（原版本、修订作废、有效报销）、所有旧包字节；committed WAL及源WAL字节不变；大文件生成时独立writer可提交且不污染快照；running恢复不阻塞首次同步；缺包/损坏/重哈希后坏schema/外键/恶意trigger、路径穿越/Windows保留名/重复/符号链接、包/展开/中央目录/文件数限额、操作前/中途取消、发布失败、并发目标抢占与已有用户目录保留。

## 交接与实际限制

- 父会话负责真实保护副本、真实原库只读备份与独立恢复验证、最终EXE/桌面交付；HTTP/UI代理负责认证、流式上传/下载和浏览器操作。本回执不冒称这些已通过。
- 独立review尚待父会话派check执行。
- Windows和Linux支持安全原子目录发布；其他平台当前明确失败，不使用可能覆盖目标的退化路径。
- 数据库完整结构按当前生产DDL校验；父会话需用真实旧schema3副本复核兼容性，若发现差异须定位真实结构原因，不以只看user_version替代校验。
