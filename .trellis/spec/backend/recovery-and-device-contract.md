# 换机接续与完整备份还原

## 1. 范围与触发

修改来源身份、核对、目录依据、备份/恢复、相关HTTP/CLI时阅读。aha历史台账独立于当前CCS快照；程序位置不决定资料位置。完整恢复与CCS用量导入分开，当前只支持单向迁移/独立目录恢复，不协调两个独立业务库的报销占用。

当前应用schema4，支持schema3完整备份的严格校验与新目录无损升级；逐笔归属、历史目录恢复和升级回退以[项目归属合同](./project-association-contract.md)为准。消费归属和项目费用是业务终点，保住来源/目录并不等于已恢复失效的项目统计。

## 2. 签名与所有者

```text
source_bindings.binding_status(store, path, *, installation_id=None)
source_bindings.bind_source(store, path, reason, *, installation_id=None)
Store.source_binding_status(path, **kwargs) / Store.bind_source(path, reason, **kwargs)
backup.create_backup(data_dir, destination, *, cancel=None, shutdown=None)
backup.restore_backup(archive, destination, *, cancel=None)
Store.create_backup(destination, *, cancel=None) / Store.restore_backup(...)
aha.exe --data-dir EXISTING --backup NEW.aha-backup
aha.exe --restore-backup FILE.aha-backup --restore-dir NEW_DIRECTORY
```

离线备份/恢复执行后退出，不创建Store、不启动服务/自动同步；restore-dir只能配restore-backup，不与data-dir混用。

HTTP使用既有Cookie/Host/Origin/CSRF边界：

- `GET/POST /api/source/binding`：可选path（缺省本机CCS），POST必须有非空reason，最长4000。
- `POST /api/backups {}` → job；`GET /api/backups/{id}` 查询；`GET/HEAD .../download`下载；`POST .../cancel`取消。
- `POST /api/restore-uploads {size}` → id/chunk_bytes；`POST .../{id}/chunks`使用`application/octet-stream`、`X-AHA-Upload-Offset`和有界Content-Length；`POST .../{id}/restore {destination?}`创建恢复job。
- `POST /api/restore-uploads/{id}/cancel`及遗留上传清理入口只清本次应用持有的上传；`POST /api/backups/{restore_id}/open`启动恢复目录实例，不更改默认data-dir。

## 3. 数据合同

### 来源和历史依据

- 安装UUID在账本外的本机`aha-device/installation.json`，Windows基于LOCALAPPDATA，Linux基于XDG_STATE_HOME或`~/.local/state`。不上传/进入材料或完整恢复包；测试必须patch或隔离profile。
- `settings.source_bindings_v1`为`{format_version:1,bindings:{key:entry}}`；key结合安装ID、规范路径和当前restore_id。profile仍放source_profiles，来源实例ID不直接等于路径。
- 旧库已有SQLite来源而缺当前绑定，或恢复副本没有匹配restore_id的绑定时，`source_binding_required`在创建run前返回；原历史保持可查，不把全部旧历史挂pending。空新库或只有SQL历史的首次SQLite接入可建新实例，异源事实冲突仍保留候选。
- 绑定前先独立恢复已知失败/过期run，再检查有效同步，保留有界writer等待与“恢复提交不被后续竞争回滚”的契约。
- 全局消费key、旧内容版本、claims与冻结包不批量改写。同key同内容幂等；来源确认不等于接受已有/曾明确保留当前值的revision候选。不同来源同值汇总仍需确认重叠（rollup_origin），未知成员范围不盲加。
- 当前机器没找到旧会话头，不撤销已保存matched cwd/项目；真正不同目录进入directory候选。current保留旧目录，candidate采用已确定的新目录；缺唯一候选时不提供candidate。候选尚开放而当前会话parent等元数据变化时，旧case必须过时/被替代并保留可处理的新候选，不能留下永远stale_case的开放事项。

### 完整恢复包

- ZIP容器，`manifest.json`的format=`aha-full-backup`、format_version=1；记录application_version、store_schema_version、created_at、files的path/size/sha256及排除项。
- SQLite backup API从一致读事务复制已提交WAL，释放源后打包；全部revisions引用的ZIP（含历史/作废版）按原hash保留，objects逐文件保全。项目/归属/报销/占用/核对在DB中完整保留。
- 不直接拷贝活动主库，不备份runtime凭证/锁/temporary/嵌套backups/旧restore marker/机器身份。未知资料文件明确阻断，不静默丢弃。生成与恢复默认最多4GiB归档、16GiB展开、100000成员；manifest/中央目录也有独立上限，传输不走128MiB SQL base64协议。
- 恢复按manifest所标schema3/4的权威定义校验表结构、索引/触发器DDL、quick_check、foreign keys、包引用与SHA，清单/DB版本必须一致；拒绝重复或大小写碰撞路径、穿越、绝对路径、保留设备名、链接/重解析点、缺失/多余成员及不支持格式。
- 目标必须尚不存在，且不嵌套源/当前资料目录；独占staging验证后按平台noreplace原子落位，失败清理只限本次staging。当前库始终不在线替换。
- 新`restore-info.json`含format_version1、restore_id UUID、restored_at、archive_sha256，恢复后同机也需新来源绑定。同版本且无running/staging时DB保留原字节；schema3恢复只在独立staging受控升schema4。有未完成run时仅恢复新目录将其failed/sync_interrupted并清暂存，不改归档或已发布事实/原包；旧ZIP在所有路径保持原字节。
- 完整备份为私有资料，与费用分享包不同。恢复目录与默认目录独立；再次双击默认EXE仍打开默认目录，结果需提供再次打开恢复目录的方式。

## 4. 验证与错误矩阵

| 条件 | 结果 |
| --- | --- |
| 旧path复制到新机、恢复后缺绑定 | source_binding_required，旧历史/成功时间不清空 |
| 安装标识/绑定/restore marker损坏 | device_identity_unavailable / source_binding_damaged，不默默生成新权威 |
| 候选未确认或明确选current后重同步 | 原值保持，不能因来源确认静默晋级 |
| 备份目标已存在、恢复目标已存在/竞争创建 | backup_exists / restore_destination_exists，不覆盖 |
| schema/索引/触发器不兼容、缺包/坏hash | invalid_backup / unsupported_backup_store，原库不动 |
| 归档/展开/成员/清单超限、坏分块/offset | backup_too_large / invalid_backup_size / invalid_backup_chunk / upload_offset_conflict |
| 取消、空间失败或超时 | backup_cancelled / backup_failed / backup_timeout；当前库可用，恢复暂存无法清理时明确restore_cleanup_failed |
| 应用退出 | 在同一应用锁内关闭新任务分配并取消有限transfer，等待worker/响应结束、清应用独占上传与临时归档，再释放Store/运行锁 |

公开错误不能包含原始SQL、凭据、路径traceback；本机界面为帮助选择明确展示资料/恢复位置，但不把它们加入费用分享材料。

## 5. 正常、基础与错误场景

- 正常：旧台账完整保留，新电脑明确绑定后补入新key；重复同步不增加，旧cwd和原包保持。
- 基础：新机CCS为空或不支持时仍可查全部历史；早期只有日汇总按整日使用，已经被明细替代的汇总不重复计入。
- 错误：把同路径当同设备、确认来源当全部修订同意、找不到旧日志就清cwd、只备DB不备原包、在线替换当前库、把两份复制账本当自动协调报销。

## 6. 必需测试

- test_device_continuity/test_storage/test_sync_timeout：换机/恢复绑定、空源/缩水、旧key去重/改值、汇总同值异源、开放及已保留候选、目录缺失/冲突、原占用/ZIP、租约恢复与有效run保护。
- test_backup/test_backup_cli：WAL一致、多版本/作废原包、历史归属/核对/占用、running恢复、DDL索引约束、缺包/哈希/穿越/链接/限额、取消/中断/磁盘失败、发布竞争且目标不覆盖。
- test_http_backup/test_http/web_state：鉴权、分块/offset、取消/断连遗留清理、退出、绑定门禁、全历史只读、核对后原意图重查、迟到成功/失败不污染新状态。
- 原生Directory/OneFile、实际页面与真实资料副本回归；真实原库写入前必须先验证独立恢复路径，原包/旧事实与项目不减少。

## 7. 错误与正确做法

```python
# 错误：来源路径相同，所以把新机的较小同key汇总当旧live的合法覆盖。
source_id = hash(absolute_path)

# 正确：位置与权威分开，绑定本机实例，保留消费key和待核对候选。
status = store.source_binding_status(ccs_path)
if status["required"]:
    # 明确确认新来源后再同步；旧历史仍可查询。
    store.bind_source(ccs_path, reason)
store.sync_sqlite(ccs_path)
```
