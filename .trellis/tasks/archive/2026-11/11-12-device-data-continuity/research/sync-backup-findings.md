# Research: 换机同步、核对与完整备份还原

- Query: 旧 aha 资料搬到新电脑，新机 CCS 为全新、清空、重建或同路径时如何合并；单选核对的影响；设备身份、去重、目录依据与完整备份恢复边界。
- Scope: internal；仅源代码、规范、已有测试的只读研究；未打开用户数据库，未执行同步或测试。
- Date: 2026-11-12

## 结论

1. 当前同步不因来源缺失而删除 `usage_records`。只有一个选项的核对是 `source` 类型，前端标签为“确认此来源，保留本地历史”；操作当时只确认观察基线并刷新派生状态，不能根据该操作就断言清库。
2. 当前实现没有设备身份。SQLite 来源按种类与绝对路径生成 ID，复制库到另一台电脑且路径相同时会把新 CCS 当成原 live 来源。确认缩水基线后，后续同 key 不同值的 live 同步允许自动换成新值；日汇总 100→10 的现有测试明确验证了这个行为。换机是现有 same-source 模型的真实缺口，不能只增加 CCS25 白名单。
3. 不同来源 ID 也没有解决所有合并：日汇总消费身份、覆盖组和占用 scope 都没有设备/来源维度。独立设备同日同模型的汇总可能被当作同一行的不同版本；值相同时甚至直接去重。日汇总并无成员证据，不能一律相加，也不能一律当作重复。
4. 普通启动不重新扫描已经 matched 的历史会话，因此通常保留旧 cwd；但手动刷新目录会重新扫描所有会话，在新电脑找不到旧日志时把旧 matched 变 missing、cwd 清空，继而丢失按目录的项目归属。已保留历史依据与当前本机文件可用性需要分开。
5. “导入备份”实际只导入 CCS `.sql` 的允许用量字段，不是 aha 备份/恢复功能。仓库没有通用完整 aha 备份/恢复入口。数据库之外还要保护所有历史修订 ZIP，不能只有主库文件。

## 文件与所有者

| 文件 | 职责 |
| --- | --- |
| `src/aha/sync.py` | 来源身份、原子比较发布、缩水基线、候选、会话依据写入 |
| `src/aha/ledger.py` | 当前事实、身份别名、覆盖与可用性、核对处理、派生统计 |
| `src/aha/domain.py` | 全局 detail/rollup 消费 key、内容指纹、受支持外部版本 |
| `src/aha/claims.py` | 冻结成员、scope/语义身份、占用冲突 |
| `src/aha/storage.py` | 事务、连接、相对成品路径、资料目录 |
| `src/aha/migrations.py` | schema3、来源与事实/核对/统计表 |
| `src/aha/batches.py` | 报销及不可变修订，ZIP 引用/哈希/原包下载 |
| `src/aha/session_meta.py` | 当前机器 Codex 会话头只读扫描 |
| `src/aha/server.py` | 默认 CCS 和 `.codex` 来源、有限同步任务、SQL 上传 |
| `src/aha/web/app.js` | 核对选择、提交后预览失效、启动同步、状态文案 |
| `src/aha/web/index.html` | 当前“导入备份”与数据来源入口 |
| `tests/test_storage.py` | 留存、缩水、基线确认、同 key 修订、身份重建的现有断言 |

## 当前来源与事实合同

### 1. 路径身份而非设备身份

- `sync.py:126-128`：`source_id` 缺省为 `content_hash([kind, location or name])`。
- `sync.py:774`：SQLite location 是 `str(path.resolve())`；`sync.py:817-824` 不提供外部 `source_id`，并统一以 `trust='live'` 发布。
- `sync.py:145-163`：新来源 profile 插入 `ON CONFLICT DO NOTHING`，既有同 ID 仅校验 kind 一致，不校验物理设备/来源实例。
- `server.py:106`：默认会话元数据根为本机 `Path.home() / '.codex'`；默认数据库由 `server.py:229-231` 选择。替换电脑时两者天然都变成新机器资料，即使字符串路径相同。
- `migrations.py:40-48`：source_profiles/epochs/runs 没有 machine/device/source-instance 字段。epoch 是“已确认 run”而非新的事实 namespace。

### 2. 缩水与单选确认

- `sync.py:349-373`：同 source_id 以最新 completed run 或 confirmed epoch 为基线；明细小于原数量一半且汇总不增长、汇总行数减少或同 key 汇总代表数减少，任一触发 source 核对。
- `sync.py:374-396`：创建 source 核对并收集原来源范围；并不删除缺失记录。
- `ledger.py:306-314`：开放 source 核对会把其来源当前事实标为 pending；`ledger.py:328-335` 重建可用性与日统计。因此“可用用量”可能暂时为零，而原事实仍在。
- `ledger.py:421-429`：coverage 为 detail/rollup、revision 为 current/candidate、identity 为 same/independent；其他即 source 仅 `['current']`。
- `app.js:990`：source/current 对应“确认此来源，保留本地历史”。
- `ledger.py:621-647`：确认仅为该来源最新 needs_review run 插入 confirmed epoch，关闭 case，记原因/事件，推进数据修订并重分类、刷新可用性。不删除事实，不替换版本，不改 ZIP。
- `tests/test_storage.py:255-271`：空重建源需要核对，旧明细数量保持；确认后可用用量恢复，重复空同步完成。

### 3. 确认后的延迟修订风险

- `sync.py:485-514`：存在当前事实且备份来源、处于缩水或另一 live 来源时，保留旧值并创建 revision candidate。
- `sync.py:515-534`：其余 live 情况直接 `set_current`，包括“已确认新基线后，再次同路径同步”的同 key 修订。
- `ledger.py:114-117`：`set_current` 用 upsert 更新当前事实；旧 `usage_versions` 保留，并非原始版本彻底删除。
- `tests/test_storage.py:341-358`：日汇总 request_count 从100变10，第一次产生 source+revision；选择 source/current 后，再同步自动采用10并清 revision。这对真正同一源纠正值是既有合同，但不能套到独立设备。
- `tests/test_storage.py:360-376`：来源少一行汇总，旧行不删除；确认后重复同步只更新仍存在的行。
- `sync.py:442-448`：相同全局 key + content_hash 会先被判 unchanged，与来源是否独立无关。

### 4. 全局身份、重建与独立汇总

- `domain.py:183-191`：detail key = app_type/data_source/request_id；rollup key = `ROLLUP_KEY_FIELDS`。
- `domain.py:47-54`：rollup identity 是日期、应用、provider、model、request_model、pricing_model，不含来源/设备或汇总成员范围。
- `ledger.py:49-58`：coverage_key 同样只有日/app/provider/模型维度；`claims.py:31-34` scope_key 也无设备。
- `sync.py:543-570`：新增 detail 若语义 hash 与其他来源相同，或同来源旧 key 本轮缺席，会创建 identity 核对。语义由 `claims.py:37-58` 的 session/time/model/token 等构成，不含金额。
- `ledger.py:574-620`：确认 same 才记录 alias、suppress 候选；内容不同继续出 revision case。未确认前不随意合并消费。
- `tests/test_storage.py:316-339`：同源等量换 key 被怀疑重建；同源同一轮并存、同秒同 Token 的不同 key 则保持独立。
- `ledger.py:176-240`：同 coverage group 同时有明细与汇总一律先核对覆盖；不能相加，确认 detail/rollup 后只选该粒度。新设备明细与旧设备同日日汇总也可能被阻塞，即使业务上独立；要解决必须有足够来源范围依据。

## 目录依据和项目的迁移风险

- `sync.py:258-280`：普通同步只读取本轮 staged session 且本地没有 matched 状态的项，已匹配历史不再扫描。
- `sync.py:283-319`：传入 missing 会生成 cwd=None 并更新 sessions，没有“历史已知而当前设备未发现”的保护。只有非 live 且两个非空 cwd 冲突时会特殊标 conflict。
- `sync.py:831-842`：手动刷新选择本地全部 sessions，并以 live 写入。
- `session_meta.py:229-231`：每个被查会话初始状态 missing；新机器没有旧会话文件时维持 missing。
- `ledger.py:275-290`：matched cwd 才用于目录规则；一旦 missing，原目录规则项目就重置未归属。手工归属只在 override_hash 恰等于当前 content_hash 时保留。
- `projects.py:17-43`：目录字符串按其自有平台规则规范化，跨 Windows/Linux 不会误当同一绝对路径；允许一个项目有多个目录，因此旧目录规则与新目录规则可以并存，无需改写历史 cwd。
- 建议：保存过的历史 cwd 是证据，当前扫描未发现只更新“本机可用性/最近尝试”，不撤销旧依据。真正冲突保留候选并说明来源；新增新机器路径为同项目的附加规则。

## 页面“消失”的可解释部分

- `app.js:245-260`：台账状态卡计数与范围来自全局本地台账，下面分析来自当前项目/时间/availability；两者可以同时显示“有历史”和“当前范围零”。
- `app.js:997-1000`：保存核对后只刷新台账和核对，调用 invalidate，并不自动 analyze。
- `app.js:160-184`：invalidate 清分析及明细，把指标变成“—”、提示“请更新预览”，并清待保存选择。该流程本身可能被理解为“全没了”。
- `app.js:933-951`：初次加载先查询本地，随后仅本次启动无 job 时自动同步一次。
- 用户截图当天为11月12日，台账截止11月10日；“今天无数据”、CCS25同步失败、核对后待预览，均需与真实库审计分别核验，不能相互替代证据。
- 建议：保留用户时间意图；明确显示“当前所选时段没有记录，已保留历史至X日”，提供可操作的“查看全部历史”。核对成功后自动重新预览原条件或明确一步刷新结果，不把尚未查询显示成确定零。

## 现有备份能力与持久资料边界

- `index.html:36`：“导入备份”的 file input 仅接受 `.sql`；`index.html:91` 数据来源对话框也只称 CC Switch 备份。
- `server.py:211-228`：该入口只是有限128MiB SQL 上传，随后 `sync_sql`，不处理 aha DB/ZIP。
- `sync.py:737-759`：SQL 备份以 trust=backup 导入允许用量；没有恢复 projects/overrides/batches/claims/packages 的路径。
- `tests/test_storage.py:137-150`：备份不同值只创建候选，不以导入时间覆盖较新 live 值。这是导入资料语义，不是整个账本还原。
- `__main__.py:17-22`：Windows资料默认 `%LOCALAPPDATA%\aha`；Linux默认 `${XDG_DATA_HOME:-~/.local/share}/aha`，程序所在目录不决定资料位置；`--data-dir` 可另选。
- `storage.py:40-47`：数据库为 aha.sqlite3，并创建 objects/packages/temporary；`storage.py:56-57` 使用WAL。
- `migrations.py:34-106`：项目、人工归属、来源运行、当前及历史版本、目录依据、核对和统计全在DB；报销/占用在 batches 初始化的附加表。
- `batches.py:80-123`：每个 revisions 含 zip_path/hash，冻结成员和版本字段不可变。
- `batches.py:1109-1123`：原包下载必须实际文件存在且哈希一致，缺ZIP不会按DB重建。因此只搬DB会造成历史材料无法下载。
- `storage.py:206-213`：成品引用是 objects/packages/temporary 下的两段相对路径，可用于独立目录移植。
- `instance.py:34-41`：profile_id 仅是资料目录绝对路径的哈希，用于本机实例认证，不是账本身份或设备身份；不能复用来判断跨设备谱系。
- `instance.py:44-51`：.instance.lock 是运行锁；runtime.json 是临时认证描述符。完整备份不能把运行凭证作为可恢复数据传播。
- `scripts/rebuild_trial_data.py` 的备份用于 schema1/2 试用库受控重建，不能当通用 schema3 备份恢复；本任务不应触发该重建流程。

## 建议最小设计与技术边界（待主会话收敛）

### 安全接续

1. 区分稳定账本ID、当前本机安装/设备ID、CCS来源实例/谱系、文件定位。设备身份应在当前机器的私有应用设置中保持，恢复完整账本不能把旧机器绑定当当前设备。
2. 旧 schema3 未记录设备身份时，在首次建立绑定前视为历史来源未知；检测复制/新机器/来源变化时先保留旧事实，显式提供“新电脑接续，保留旧历史”与“原来源迁移/恢复”的行为说明。禁止凭同路径认定旧live仍权威。
3. 原消费 key/版本/claims/冻结ZIP不批量重写。新增来源观察/绑定可用扩展表或元数据；迁移须校验并备份，不能在已有schema3上仅修改新建DDL却漏掉存量库。
4. 同 request_id相同内容继续幂等；不同内容保留候选；疑似换key继续核对。**不得粗暴给全部detail key加设备前缀**，否则复制/重建的同一消费将重复，且冻结占用关系变化。
5. 同日日汇总按可证实谱系解释。独立设备已证实不重叠才可累计；旧库或备份未知重叠时保留分来源候选并阻止双计。只增加source_id而不改汇总/coverage/claims依据不够。
6. 新设备当前未找到旧会话头时保留旧目录依据；新增设备目录规则附加到同项目，历史材料不重算。

### 完整备份与还原

1. 把当前入口重命名为“导入 CCS 用量备份”；增加独立“完整 aha 备份/恢复”入口，显示本机资料目录和备份用途。
2. 完整备份采用 SQLite backup API/一致事务快照，含已提交WAL；从快照DB枚举全部 revisions 原ZIP（含历史/作废版），逐文件校验并写manifest。不要在线单独复制主库，也不要执行源库checkpoint/journal_mode来“方便备份”。
3. manifest记录格式、应用/schema版本、账本谱系、生成时间与文件相对路径/长度/SHA。备份包含个人项目/路径等，是私有恢复资料，不能当费用材料分享；不附CCS凭据、聊天正文或runtime认证文件。
4. 还原先校验manifest、路径边界、ZIP成员重复/穿越/符号链接、大小上限、DB quick_check/foreign_key_check/schema以及每个原包引用，写到独立staging目录。失败不得接触现有资料。
5. 完整恢复是某时点账本恢复，不是把两个分叉的aha账本直接合并。最小安全方式先恢复到新目录并验收；若支持替换当前目录，必须在进程完全退出且持有互斥条件下、先保全当前完整副本，再原子切换，提供失败回退。活动服务不能原地替换其打开的DB和packages。
6. 多设备同时写两份完整账本会产生归属/核对/报销/占用分叉。现有claims只约束同一DB，跨库重复报销无法自动阻止。建议一份主账本负责正式报销，其余设备提供只读/来源导入；无显式需求不要扩成自动双向云同步。
7. 自动备份保留策略需要明确并受限，不能无限复制，也不能把未知真实历史库、用户备份、objects按后缀清除。真实资料不进入Git。

## 用户拥有的关键决策

优先确认：旧电脑是否退役，还是新旧电脑以后还会同时使用？

- 仅迁移：完整账本搬迁+新机器来源隔离接续足以满足主要场景，原机保留一次恢复副本。
- 长期多设备：还需要定义主账本/资料汇合及跨设备历史汇总范围，不能承诺现有复制目录就等于实时合并。
- 还原当前库与还原为新目录的用户体验可作为最终规划一起审阅；不应在调查前选择破坏性“回到旧备份”。

## 建议验收矩阵

| 场景 | 必须断言 |
| --- | --- |
| 旧库+同路径空新源 | 旧事实/项目/占用/ZIP完整，绑定不误指原live，重复同步稳定 |
| 旧库+新机器新增明细 | 旧+新计入；重复同步无重复，仍可下载旧包 |
| 同路径新源同key较小汇总 | 不能确认来源后下次静默覆盖旧设备历史，旧值与候选可查 |
| 不同设备同日同模型汇总 | 相等值不自动丢一份，不同值不直接替换；未知重叠不盲加 |
| 旧备份重叠/换key/修订 | 去重与候选明确，claims与冻结成员不迁移成重复消费 |
| 刷新新机不存在的旧会话 | 历史matched cwd与项目归属保留，新会话仍可识别 |
| 完整备份后还原独立目录 | DB逻辑、项目/规则/人工归属、所有报销/claims/事件以及每个ZIP SHA一致 |
| 恢复损坏/缺包/穿越/中断/有占用 | 失败安全，当前库可用，未登记临时文件清理，回退副本完整 |
| 核对前后实际页面 | 不把待刷新显示成零；旧时间意图保持，可明确查看全历史 |

## 相关规范

- `.trellis/spec/backend/usage-evidence-contract.md`
- `.trellis/spec/backend/database-guidelines.md`
- `.trellis/spec/backend/ccs-source-compatibility.md`
- `.trellis/spec/backend/time-range-contract.md`
- `.trellis/spec/backend/runtime-lifecycle-contract.md`
- `.trellis/spec/backend/delivery-and-cleanup.md`
- `.trellis/spec/frontend/state-management.md`
- `.trellis/spec/frontend/component-guidelines.md`

## Caveats / Not Found

- 未访问用户原库，无法证明该用户哪次核对、是否还有其他操作、真实计数与实际路径；由主会话Windows原生只读审计补足。
- 未执行现有测试；以上测试内容是代码中断言，不是本次已通过的检查。
- 未研究CCS25上游迁移，由独立研究承担；本文件只说明兼容白名单不能替代换机来源修复。
- 未发现通用完整aha备份/还原或分叉aha账本合并产品入口。恢复、合并与CCS资料导入必须明确区分。
- 设备源谱系、独立日汇总身份与范围是设计难点；如果本期只解决单向迁移，必须把长期多设备汇总边界写清楚，不默默宣称自动双向合并。
