> 实施批准：用户已于2026-10-27在更新后的完整方案后明确回复“开始实现”。下文规划阶段状态语句保留为决策过程；以本批准记录为准。

# 用量独占技术设计

状态：已按用户批准范围实现并交付 `0.2.0`，验收见`verification.md`。应用库 schema `2`，CCS 来源仍为 `23`，留存对象格式与旧 ZIP 不变。

## 架构与数据

一个贯通任务实现占用、有效版本、可用预览及旧资料升级。`storage.py` 为唯一数据库结构/迁移/事务所有者，新增 `claims.py` 集中身份与覆盖规则；`analysis.py` 继续唯一核算；`batches.py` 负责生效、撤回、作废、幂等和原包；服务/界面不另算账。

| 对象 | 契约 |
| --- | --- |
| `batch_control` | batch_id PK、active_version、lifecycle(active/voided/legacy_review)、generation、作废时间与原因；有效指针必须指向本批次版本 |
| `usage_claims` | record_key PK NOT NULL、batch_id/owner_version、kind/scope_key/semantic_key/member_json，版本与批次外键 |
| `legacy_holds` | 旧候选批次/版本/成员及范围，可有多个旧持有者；阻止新使用但不伪装有效申请 |
| `claim_events` | 追加型版本切换、撤回、作废、迁移确认记录，含原因、时间、前后有效版/状态 |
| settings.claim_revision | 独立于项目归属 revision 的单调占用修订号 |
| revisions 追加列 | claim_protocol DEFAULT 0、write_generation DEFAULT 0，用于旧客户端防护；不改原 frozen JSON/ZIP |

scope/kind、非空 semantic_key、batch ownership 建索引。同日不同明细允许分别占用，不能把 date/model 全局唯一化。明确身份靠唯一键，跨粒度/疑似身份靠同一写事务的覆盖检查。

## 身份和可用过滤

- 明细沿用 domain.record_key，不包含项目、价格、capture、文件名等可变值。统一现 `_member.semantic_key` 与 `_semantic()` 的字段差异，迁移/预览/保存共用纯函数。
- 疑似请求键重建标记“无法确认独立”，不宣称肯定相等；与已占用特征相同则待核对排除。不以“同秒同 Token”自动合并/删除独立明细。
- 完整汇总检查原键及来源/日期/模型覆盖，与其他占用汇总/明细交叠时整条排除，不按比例相减。
- 内部 detail+rollup 或不同键 rollup+rollup 覆盖冲突组整体待核对排除，其余互不冲突成员仍可用；不任意选其中某个粒度为真实费用。保存对传入集合再次拒绝内部冲突。
- legacy_holds 与有效 claims 同样参与可用判断。只免除修订目标批次自身的占用，不能免除其他批次。
- 过滤在唯一分析循环累计前进行；summary/daily/models/members/Token/金额共同计算。返回 raw matched、available、excluded 三类统计，区分实际行、明细和汇总代表请求数。
- `availability_mode=available` 为新建默认；`all` 只读，不创建新报销。0可用不能新建，不解释为零消耗。

## 稳定门面

```text
Store.claim_snapshot(exclude_batch_id=None)
  -> {claim_revision, claims, legacy_holds, owners}
Store.create_batch(analysis, claim, idempotency_key, batch_id=None,
                   expected_generation=None, expected_active_version=None)
Store.withdraw_batch(batch_id, expected_generation, reason, idempotency_key)
Store.void_batch(batch_id, expected_generation, reason, idempotency_key)
Store.resolve_legacy(batch_id, selected_version, expected_generation, reason,
                     idempotency_key)
```

命名如在实现阶段收敛，应先通知依赖协作者；行为不能弱化。签名的稳定字段/返回契约先由持久化实现者与主会话冻结，再让依赖模块接入。

## HTTP 与界面契约

| 路由 | 契约 |
| --- | --- |
| POST /api/analysis | 原筛选 + availability_mode；仅绑定新建/只读主体，返回 claim_revision、真实可用结果和排除信息 |
| POST /api/batches/{id}/analysis | 专用修订预览，筛选 + expected_generation/base_version；仅有效草稿，可含自身占用 |
| POST /api/batches/preview | blocking conflicts，无“仍然继续” |
| POST /api/batches | 原幂等键/claim/analysis_id，仅新建可用主体 |
| POST /api/batches/{id}/revisions | 冻结有效版或本批次修订预览 + expected_generation/active_version，不能借别的批次免除主体 |
| POST /api/batches/{id}/withdraw | 原因、generation、幂等键；已提交撤回草稿，保留占用 |
| POST /api/batches/{id}/void | 同上，作废有效/待核对批次，按 owner 释放，终态 |
| POST /api/batches/{id}/resolve | selected_version、原因、generation、幂等键，旧候选明确确认，仍检查其他持有者 |
| 原 status API | 仅有效版本；禁止 paid→draft 和历史版写状态 |
| 原详情/下载 | 原包不变；追加 is_effective/lifecycle/active_version/generation/can_* 供界面动作 |

复用 Host/Origin/CSRF、JSON/长度校验；原因/用途上限4000。客户端不传任意分析对象。冲突只返回安全编号、版本、数量、范围和原因，不输出源路径。

建议稳定错误：usage_claimed、usage_ambiguous、usage_internal_overlap、availability_changed、stale_batch、batch_voided、inactive_revision、migration_conflicts、store_busy。冲突/过期为可操作409。

界面保留全部查看与原包，增加可用筛选、排除原因/批次、有效/历史/作废区分。草稿的“按当前筛选修订”调用专用预览，明确显示实际成员与金额后保存；新建不能借其豁免。已提交先带原因撤回，已报销仅查询/下载/带原因作废。普通状态切换不释放。

## 事务、幂等与失效

统一 BEGIN IMMEDIATE：先幂等命中，再核对主体、generation、有效版和 claim_revision，再检查实际成员，生成校验新不可变包，插入版本/占用、切换指针、释放允许删除的草稿成员、写事件和修订号，最后提交。

- 跨进程安全来自 SQLite 写事务和唯一约束，RLock 只负责单连接线程。
- 失败一并回滚版本/指针/占用/事件/幂等；孤立未索引新包不冒充成功。旧版/原包不改。
- 相同幂等请求返回原结果，即使后来作废也不能复活。作废删除必须限定 owner，不释放别人的后来占用。
- 暂态 claim_revision 不污染等价业务 hash，避免无关批次变化产生假新版本。
- 预览绑定一致读取的占用修订号。保存被抢先占用时409要求重新预览，不静默缩成员，也不自动修改人工金额。
- 失效校验与幂等成功重试分开：成功导致修订号增加后，同一丢响应请求仍能取回原结果，不能在进入 Store 幂等查询前就被服务层拒绝。
- 草稿换版才能调整其成员差异；已提交撤回不释放，已报销不直接修订；作废是终态。

## schema1 升级与旧客户端

1. 写锁内重查版本，并发只迁移一次。未知版本/损坏成员明确拒绝。
2. 任何结构修改前，使用不同只读源连接的 SQLite backup API 保存唯一命名的完整 v1 备份并验证可读；真实文件锁顺序、超时实施时验证。备份失败不继续，不漏 WAL。
3. DDL、回填、触发器、user_version=2 在单事务中逐句 execute；不能在已 BEGIN 后调用会提前提交的 executescript。
4. 验证旧 analysis/members 关系，不重建旧包。无冲突的单版本草稿直接有效、纳入占用。
5. 不只取 MAX(version)。旧已提交/已报销、多候选或跨批次重复不安全时，相应批次 legacy_review，所有候选进 holds，不释放旧已报销成员。无关可用成员仍可用。
6. 用户先带原因作废不保留者，再带原因确认保留批次的具体有效版本；确认重查其他 claims/holds，不自动选赢家或全局清空 holds。
7. revisions INSERT 显式 claim_protocol=2，触发器拒绝旧默认0。状态 UPDATE 须递增 write_generation 且目标有效未作废；旧活跃连接的原 SQL 也拒绝。
8. 正式升级前退出旧程序，不自动杀进程。runtime 只辅助提示；schema2 阻止旧程序重新打开，持久化触发器覆盖升级前已打开的旧连接。

迁移失败回滚 schema1；原 objects/packages 不改。恢复旧版先退出程序，使用升级前备份及配套资料，不能直接用旧 exe 读 schema2。开发仅用副本；正式升级由用户启动新成品触发。

## 证据和交付

新 HTML/JSON 冻结可用筛选口径、排除概况及有效版本依据，CSV 为真实成员。后续状态和作废不改任何原包。

## 排版与文案

现有 root14px、table11px、th10px、subline9px、input/button12px 是本次明确改善的基线。保留青绿色重点、深色导航及白色卡片，统一字号/行高/间距变量，移除分散的小字号覆盖；中文正文不用负字距挤压。

| 信息层级 | 目标 |
| --- | --- |
| 正文/输入 | 16px，行高约1.6—1.7 |
| 表格/按钮 | 15px，数字等宽对齐，表格行高及按钮点击区域随之增加 |
| 标签/表头 | 14px，次级标题20—22px，页面标题28—30px |
| 次要信息 | 至少13px，足够对比；必要帮助不隐藏成9—11px浅灰字 |

桌面按钮/输入高度约42—44px，窄窗口按可用宽度重排，不缩小正文；宽表只在容器内横向滚动，关键动作和完整项目/金额仍可见。全局计算字号验证加真实截图，不为纯样式写镜像单测。

统一产品命名示例：

- “把项目用量，留成可复查的证据”改为“用量与费用”；“每次申请，都有原始材料可查”改为“报销记录”。
- “创建批次并下载”改为“保存并下载”；“以此创建新版本”改为“修改报销记录”，弹窗说明保存后生成新版本并保留旧版。
- “重新下载原 ZIP”改为“下载材料”；明确当前/历史/已作废，不把生效规则解释成开发旁白。
- 成功提示先结果；过期/占用冲突用“部分用量已被其他记录占用，请更新预览”等可执行提示，不暴露协议字段。

计价与来源技术细节集中在按需帮助/数据说明；保留“参考成本按 CC Switch 历史记录汇总，报销金额由你填写”的业务区别。新费用说明页同步可读排版与中文时间/简洁说明，打印单独验收；旧包不改。现有DOM稳定标识可沿用，API字段/错误code保持机器契约，用户文案与其解耦。

验收覆盖1440/1366宽桌面100%显示、1280窄桌面和430移动宽度，必要时增加放大布局检查；三页、表格、空态、生命周期弹窗、长项目名、长金额、字段错误均实测。保留优化前后截图，检查计算字体、无整页溢出、实际读写操作与视觉层级。

目标版本0.2.0，先目录包后单文件；新桌面目录 aha-v0.2.0-20261027，已存在则另用新目录。保留 v0.1.0、原件和 QA。更新 README、两份真实 spec 及验证记录，不修改 Trellis 运行时。

备份与锁顺序、跨进程、旧 writer 防护、主体不可借用、旧冲突释放需实施证据。研究的内存实验不当作真实文件/Windows验收。完整范围与验收以 PRD 为准。
