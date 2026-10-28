# Research: 来源同步、身份与明细覆盖契约

> 主会话范围更新（2026-10-28）：用户已确认历史用量安全并入、冲突待核对；旧试用项目、报销、占用和材料可清理，新库不承担旧业务协议兼容。下文提到的旧占用接续仅作为调研事实；去重、防重建绕过及冻结规则适用于新台账中今后形成的业务。原始 CCS 来源与清理前保全的历史用量保持受保护。当前范围以 PRD 和 design.md 为准。

- Query: CCS 清理/重建期间如何安全采集并长期留存 Codex，用何种身份及覆盖规则避免修订遗漏和跨快照双计？
- Scope: mixed；只读仓库及官方上游，写入仅限本研究文件；未访问用户 CCS、私人 SQL 或正式资料。
- Date: 2026-10-28
- 状态：规划研究；以下算法为实现建议，不是已完成功能或额外产品授权。

## Files Found

| 文件 | 已确认职责及锚点 |
| --- | --- |
| `src/aha/sources.py:24` | 当前源限额 5 秒、512 MiB；允许三个来源表 |
| `src/aha/sources.py:63` | `mode=ro`、`query_only`、`trusted_schema=OFF`、内存 backup 后读取 |
| `src/aha/sources.py:51` | 当前 `fetchall()` 返回整表列表，局部修改后仍有全量内存成本 |
| `src/aha/sql_dump.py:188` | 仅解释允许表字面量 INSERT，跳过私有配置表；不执行导入 SQL |
| `src/aha/sql_dump.py:240` | SQL 128 MiB 限额、版本声明、完整字段和原文件指纹 |
| `src/aha/domain.py:171` | 明细身份为 app_type/data_source/request_id；汇总身份为六维来源主键 |
| `src/aha/domain.py:182` | 来源内容指纹与身份分开；项目名不参与来源身份 |
| `src/aha/domain.py:243` | 两种输入共用归一化与重复主键拒绝边界，当前最终还会整体排序 |
| `src/aha/claims.py:29` | 旧占用 scope 比完整汇总键更宽，不含 request_model/pricing_model |
| `src/aha/claims.py:185` | 原始 key、疑似重建语义、跨粒度覆盖及 legacy hold 的保守阻断 |
| `tests/test_sources.py:296` | 已提交 WAL、原件哈希不变、只保留允许字段的现有断言 |
| `tests/test_sources.py:366` | 超时明确失败；`:375` 验证同身份内容变化及汇总维度差异 |

## Findings

### 1. 上游事实与不可推导项

研究固定到 CCS commit `e55d8a21b3897b595b746e9f2139716b2931641d`，不声称等于用户当前安装版本。

- [schema.rs:205](https://github.com/farion1231/cc-switch/blob/e55d8a21b3897b595b746e9f2139716b2931641d/src-tauri/src/database/schema.rs#L205)：明细主键 request_id；有事件 created_at，没有 updated_at、CDC 序号或可靠递增导入 ID。
- [session_usage_codex.rs:2308](https://github.com/farion1231/cc-switch/blob/e55d8a21b3897b595b746e9f2139716b2931641d/src-tauri/src/services/session_usage_codex.rs#L2308)：created_at 来自日志事件时间，解析失败才退到当前时间；新导入记录可以具有旧日期。
- [session_usage_codex.rs:2225](https://github.com/farion1231/cc-switch/blob/e55d8a21b3897b595b746e9f2139716b2931641d/src-tauri/src/services/session_usage_codex.rs#L2225)：request_id 来自 rollout/root 标识及事件后缀；同一会话的物理重写/重导不能由路径或时间水位排除。
- [session_usage_codex.rs:576](https://github.com/farion1231/cc-switch/blob/e55d8a21b3897b595b746e9f2139716b2931641d/src-tauri/src/services/session_usage_codex.rs#L576)：存在重置全部 codex_session 明细及 _codex_session 日汇总的路径。
- [session_usage_codex.rs:2203](https://github.com/farion1231/cc-switch/blob/e55d8a21b3897b595b746e9f2139716b2931641d/src-tauri/src/services/session_usage_codex.rs#L2203)：重导每 1000 条一批事务，最后一批才推进该文件游标。
- [mod.rs:156](https://github.com/farion1231/cc-switch/blob/e55d8a21b3897b595b746e9f2139716b2931641d/src-tauri/src/database/mod.rs#L156)：启动调用 rollup_and_prune(30)。
- [usage_rollup.rs:79](https://github.com/farion1231/cc-switch/blob/e55d8a21b3897b595b746e9f2139716b2931641d/src-tauri/src/database/dao/usage_rollup.rs#L79)：清理前可能回填费用；回填发生在清理 SAVEPOINT 之外。`:89` 至 `:110` 将汇总与删除作为一个原子操作提交或回滚。
- [usage_rollup.rs:148](https://github.com/farion1231/cc-switch/blob/e55d8a21b3897b595b746e9f2139716b2931641d/src-tauri/src/database/dao/usage_rollup.rs#L148)：日期由 SQLite localtime 决定，维度含 request_model/pricing_model，NULL 归一为空串；新旧汇总叠加。
- [usage_rollup.rs:140](https://github.com/farion1231/cc-switch/blob/e55d8a21b3897b595b746e9f2139716b2931641d/src-tauri/src/database/dao/usage_rollup.rs#L140)：上游汇总成本经过 REAL 求和后转 TEXT，因此与 aha 对逐条保存金额的精确 Decimal 和可能存在尾差。
- [usage_stats.rs:479](https://github.com/farion1231/cc-switch/blob/e55d8a21b3897b595b746e9f2139716b2931641d/src-tauri/src/services/usage_stats.rs#L479)：汇总调用的 effective filter 会排除与 proxy 重叠的会话行。aha 当前只筛 codex_session，未照搬该规则；这是覆盖核对风险，不能自行改变已确认统计口径。

关键区分：一次源事务的隔离成立，不代表 CCS 整轮重导完成。某次一致快照可能恰好位于两批重导之间；计数变少或为零也不能成为删除本地历史的依据。

### 2. 同步策略应准确命名

建议定义为：**全量核对当前允许来源投影、仅差异写入本地**。

- 每次打开/手动同步完整读取当前仍存在的 codex_session 明细、对应日汇总及需要的价格依据；不读取 aha 的全部历史明细来逐条做 Python 对比。
- 本地利用稳定 key、内容 hash 和带索引的 staging/current 表比较；新增写一条事实，变化写修订，完全相同仅更新必要观察信息。
- 最大 created_at、文件 mtime/大小、当前库文件 hash、只回扫最近几天均不能作为“不会漏历史修订”的依据。
- 近期窗口可成为后续优化提示，但本期不能依赖它取代当前允许投影的完整核对；也不能声称实现了严格增量拉取或 CDC。
- 同步成本与 CCS 当前允许投影规模及查询计划有关，不应与 aha 多年历史规模成正比；来源仍可能保留大批旧数据，30 天是清理参数，不是始终已清理的硬上限。
- 数据库/单次导入的资源限额与“本地可保存千万条”是两项能力，应分别公布和验证，不能用本地规模验收暗示任意大来源可一次导入。

### 3. 来源读取方案比较

| 方案 | 一致性与锁 | 成本与边界 |
| --- | --- | --- |
| 当前整库内存 backup | 成功后得到一致副本；每步短期持源读锁，外部写入可使备份自动重启 | 复制所有应用和私有配置页到内存，随后 fetchall；成本随 CCS 无关数据膨胀；当前有整库 512 MiB 限额 |
| 同一只读事务流式读取允许表 | `BEGIN` 后首次读建立视图，所有表/分页必须共用该连接和事务；WAL 中读写可并行，回滚日志模式下读事务可能延迟写提交 | 工作集可按块限制，只提取允许投影；必须限制源事务时长，不能跨页结束事务后继续假装同一快照 |
| 可选的短查询与 data_version 栅栏 | 在同一只读连接、事务外读取前后 data_version，中间分块短查询；若外部发生提交则丢弃整轮并有限重试 | 减少连续读锁，但活跃写入时可能反复失败；这是乐观一致性候选，不是持久水位，也不能跨连接比较 data_version |

推荐以第二种作为主设计候选，并在真实 DELETE/WAL 双模式验收锁持有时间；不要假定源库一定是 WAL，也不要替 CCS 改 journal_mode。

上游 [Database::init](https://github.com/farion1231/cc-switch/blob/e55d8a21b3897b595b746e9f2139716b2931641d/src-tauri/src/database/mod.rs#L99) 所核对初始化段未强制 WAL；应在只读连接查询实际模式。

[schema.rs:3771](https://github.com/farion1231/cc-switch/blob/e55d8a21b3897b595b746e9f2139716b2931641d/src-tauri/src/database/schema.rs#L3771) 已有 app_type/created_at 索引。来源查询应使用可利用该索引的过滤与排序，验证执行计划；不得为加速给源库加索引。不要在 WHERE 对 created_at 每行做日期函数而放弃索引。

流式方案必须同时替换 sources._table_rows 的 fetchall 列表、build_source_data 的全量 seen/sort；可复用逐行 normalize/hash，用 staging 唯一约束拒绝重复 key。仅把最后一次 INSERT 改为 executemany 不足以获得有界内存。

### 4. 可执行同步边界

1. 按本地单例锁/数据库 run 租约保证同一台账只有一个同步发布者；手动重复点击返回已有进度。
2. 建立只读源连接，保留 mode=ro/query_only/trusted_schema=OFF；不启用 read_uncommitted、shared-cache 或 live immutable。
3. 在同一源一致视图内验证 schema=23、允许表/列，分块读明细、汇总和价格；只把允许投影写入自有 staging，绝不落地全库 SQL/凭证副本。
4. busy_timeout、墙钟预算、SQLite progress handler 和块间检查共同限制等待/执行；超限明确失败，不截断数据后报成功。
5. 对 staging 校验主键唯一、金额/Token/语义/日期和覆盖；重复源 key 必须拒绝，不用 INSERT OR IGNORE 吞掉非法重复。
6. 源连接及时关闭；来源元数据扫描仅补充所需 session ID 的目录依据，不读取聊天正文，不因统计查询再次访问来源。
7. 本地按 key/hash 差异构建事实修订与受影响范围。新事实与派生统计在发布前不可被普通查询看见；读者继续使用上一已发布 generation。
8. 在受控本地写事务中完成可见版本发布、同步成功进度及统计版本的关联；失败保持旧可见事实、原占用和成功进度。不能对 staging 每批 commit 就宣布整轮同步成功。
9. 允许合法空来源；曾有数据后明显缩水/汇总回退时记录异常观察、保留旧事实，不能将“空”直接当做业务完整或来源删除命令。
10. 只追加每轮一次的同步摘要、必要变更及异常信息；无变化时不为每条历史记录新增重复观察/修订，避免同步频率导致本地二次膨胀。

### 5. 身份、代际与事实新旧

- `source_id` 是 aha 本地登记的采集配置 UUID；来源路径可保存在私有配置，不进入分享材料。文件名和投影 hash 都不是稳定来源身份。
- `epoch_id` 记录观察到或人工确认的来源重建代际；文件替换、大幅缩水、汇总回退、相同事件出现新 key 是风险信号，不能保证自动发现所有重建。
- 没有从允许三表发现可靠的源 UUID、重建序号或全局业务版本；代际未知应如实标记，不能仅靠文件路径未变而宣称连续。
- 兼容 `domain.record_key` 的既有业务 key；来源 ID/代际只承担溯源职责，不能给旧请求换个 source 前缀就绕过 usage_claims。
- 同 key、同 hash：复用事实；同 key、不同 hash：保留修订并维持原占用；不同 key 仅语义相似：记录疑似别名/重建冲突，不自动去重真实不同请求。
- 计数、时间戳、Token 或费用相同不证明同一请求。现有 semantic_key 可用于筛选冲突候选，不能作为全局唯一键。
- 活库同一已确认来源链的本次成功观察可推进其当前事实；已删除行不撤销本地事实。
- SQL 备份今天被导入，不代表其内容比昨天已采集活库新。缺少可信版本先后时，建议补齐缺失事实并保存不同内容为修订候选，不自动降级活库当前值。
- 旧 capture 仅保存安全来源名和指纹，不能仅凭它们证明来自同一源代际；迁移如何并账需要在主设计中明确。

### 6. 跨粒度覆盖与统计基准

覆盖核对键至少包含：逻辑来源链/代际状态、来源日期及其时区依据、app_type、provider_id、model、规范化 request_model、pricing_model；不加入项目名。

- 明细按源时区分组后，汇总向量为 request_count、归一 fresh input、output、cache read、cache creation；成本另以精确 Decimal 核对。
- 原始汇总 date 原样保留。源用 localtime，但备份不携带历史时区；当前 aha 按北京时间是既有业务约定，不能冒充从源备份验证出的时区。跨时区/日期边界不明时不得自动确认覆盖。
- 计数和所有 Token 向量一致，只证明聚合一致，不能证明请求成员全集相同；存在重建、新 key、过滤差异或旧资料来源未知时仍为待核对。
- 成本尾差、清理前最后一次补价未被 aha 捕获、上游 effective filter 与 aha 口径不同，都必须留下差异依据；不能把汇总差额分摊回明细。

| 观察情况 | 可确定的行为 | 不可自动推导 |
| --- | --- | --- |
| 只有已采集明细 | 保留并查询其逐条事实；显示观察覆盖 | 没有其他请求、当天完整或缺日为零 |
| 只有来源日汇总 | 保留完整汇总的来源粒度，沿用整条归属规则 | 拆分到会话、小时或凭空造逐条记录 |
| 明细与汇总存在明确、可信的成员覆盖依据 | 统计采用一种粒度，另一份作为核对依据；原始依据均保留 | 把两份相加、重算旧报销 |
| 数量/Token 一致但成员或代际不明 | 标记聚合已对上、成员覆盖待核对，保留双方 | 仅据数值相同自动认证完整覆盖 |
| 部分覆盖或冲突 | 保留双方依据、显示缺口/差异，不相加、不比例拆分；冲突成员组不进入可报销用量 | 用“汇总减明细”制造剩余请求或独立项目用量 |

用户已同意不双计、保留依据并提示核对及原占用不绕过。技术上可采用保守阻断，无需再问是否允许造明细或自动删数据；展示时可将冲突组两种依据分别标为不可加总，避免给出虚假的唯一总额。

任何新的统计基准都不能缩窄旧 claims.scope_key 的防重范围；旧的同日/模型 rollup 占用仍须阻断相关新明细，源代际切换和同 key 内容修订也不能使它释放。

### 7. 建议验收反例

| 场景 | 必须观察到的结果 |
| --- | --- |
| 新事件具有比上次水位早的 created_at | 本次全量核对允许投影仍发现它 |
| 一个月前可见记录费用从 0 回填 | 保存修订，日常当前值推进；冻结包和旧占用不变 |
| CCS 汇总/删除事务与采集交错 | 同轮取得一个已提交视图或明确失败，不混接两个时点的表 |
| CCS 清空后重导，只完成第一批 | 保留旧历史，出现重建风险提示，不把部分提交叫整轮完整 |
| 无关应用表增长 10 倍而允许投影不变 | 不整库复制；报告来源查询计划、读取量、内存及锁时间 |
| 重复同步 100 次且内容不变 | 当前事实/内容修订条数不增加，只有有界同步摘要增长 |
| 旧明细 60 条、来源汇总代表 100 条 | 不计成 160，不造 40 条；保留缺口并阻断歧义申请 |
| 100 条明细与 100 次汇总数值匹配但 key 重建 | 不能仅按计数确认完整；旧占用继续生效 |
| 成本只有浮点汇总尾差，或清理前补价差异 | 原金额保留、差异可见，不重定价或静默覆盖逐条金额 |
| request_model/pricing_model 不同或跨时区午夜 | 不粗按日/模型合并成同一确定覆盖组 |
| 旧 SQL 今日导入，与活库旧 key 金额不同 | 保存来源和候选修订，不以导入时间自动覆盖当前值 |
| 源忙、读取超时、staging 失败、发布 commit 失败 | 成功进度及旧可见数据/统计/占用均不改变，重试不会重复 |

## External References

- [SQLite 隔离](https://www.sqlite.org/isolation.html)：跨连接只读到已提交状态；WAL 为快照隔离，回滚日志通过锁协调读写。
- [SQLite 在线备份 API](https://www.sqlite.org/c3ref/backup_finish.html)：分步持锁、BUSY/LOCKED、外部写入导致自动重启；完整成功前不能使用未完成目的库。
- [SQLite URI](https://www.sqlite.org/uri.html)：mode=ro 与 immutable 的语义；live 来源不能跳过锁和变化检测。
- [SQLite data_version](https://www.sqlite.org/pragma.html#pragma_data_version)：仅比较同连接的前后值；不是跨连接/跨启动的持久业务版本。

## Related Specs

- `.trellis/spec/backend/usage-evidence-contract.md:42`：来源、精确金额、日期、冻结、占用与失败合同。
- `.trellis/spec/backend/database-guidelines.md`：连接、事务、备份、不可变文件及迁移要求。
- `.trellis/spec/guides/cross-layer-thinking-guide.md`：来源、核算、占用、保存、导出需要共同核对。

## Caveats / Not Found

- 未访问用户源库，未验证安装版本、实际 journal_mode、历史时区或真实数据分布；没有进行性能或迁移验收。
- 不存在仅靠当前三表即可完全可靠识别所有重建、补价和请求成员覆盖的证据；不能把启发式信号写成强保证。
- 本文件不决定新增 proxy 去重口径，不把上游过滤规则悄悄加入当前 Codex 会话统计。
- 优先需要用户决定的是旧 capture 的并账兼容策略：建议验证后自动并入无冲突的同身份事实；来源/修订先后/覆盖不明的资料保持旧依据可查并进入待核对，不静默按 capture 时间选赢家。
- 主设计需明确该兼容策略及冲突组展示方式；其余来源删除不删本地、有限等待、保留占用、未知覆盖保守阻断均属于已确认边界的技术落实。
