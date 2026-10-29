# 北京时间范围、部分日汇总与冻结材料

## 1. 范围与触发条件

修改首页/当前修订的时间筛选、查询统计、游标、冻结或导出时阅读。所有链路复用 `time_ranges.py` 的北京时间半开区间；界面意图只是展示元数据，已解析边界才是选择依据。应用仍为 schema3，不为时间组件增加迁移。

## 2. 签名

```python
Store.analyze_time_range(time_range, project_id="all", *, availability_mode="available",
                         target_batch_id=None, expected_generation=None,
                         expected_active_version=None)
Store.analyze(start_date, end_date, project_id="all", **kwargs)  # 旧整天入口仍支持
time_ranges.resolve(intent, *, now, coverage=None) -> TimeRange
time_ranges.from_analysis(analysis) -> TimeRange
```

`POST /api/analysis`、`POST /api/batches/{id}/analysis` 接受 `time_range` 意图，或旧 `start_date/end_date`，两者互斥。目标修订仍要求 `base_version/expected_generation`，不能将自豁免预览用于新建。

## 3. 请求、响应与持久合同

请求意图示例：

```jsonl
{"kind":"preset","preset":"last_24h","follow_now":true}
{"kind":"preset","preset":"today","follow_now":false,"end_before":"2026-10-29T10:00:31+08:00"}
{"kind":"custom","start":"2026-10-28T10:00","end":"2026-10-29T10:00","follow_now":false}
```

- `preset` 取 `today/last_24h/last_7d/last_14d/last_30d/month/all`。24 小时为连续 86400 秒；7/14/30 天包含锚点所在自然日。`month` 从锚点当月1日开始。
- 跟随当前时刻时，每次新分析只捕获一次服务端 `now`，结束排他边界为当前秒加1；固定快捷范围须携带已固定的 `end_before`。`all` 不允许跟随，从本地覆盖取完整起止日。
- 自定义输入是 `YYYY-MM-DDTHH:MM`，解释为北京时间；固定结束包含整个结束分钟。相同起止分钟表示1分钟。跟随结束的 custom 不传 `end`。
- 响应 `time_range` 包含 `version=1/timezone=Asia/Shanghai/start_at/end_before/precision/intent/resolved_at/rollup_policy=full_days_only`。两个端点均为含 `+08:00` 的秒级 ISO 字符串；`precision` 为 `day/minute/second`。`start_date/end_date` 仍保留为覆盖日期兼容投影。
- `GET /api/status.now` 是服务端北京时间秒级 ISO。浏览器时区不能改变选择；旧 `intent.kind=legacy_dates` 是内部兼容元数据，不能直接当作新请求意图发回。
- `time_coverage={complete,omitted_rollup_count,omitted_days,reason}` 独立解释时间粒度损失。`reason` 有省略时为 `daily_rollup_has_no_event_time`，否则为 null。`pending_count` 继续表示业务待核对，不把部分日汇总转为核对事项。
- 日汇总仅在该整天完全被覆盖时计入；首尾部分日只取有真实事件秒的明细。省略数按同一项目、该部分日期的未抑制日汇总计数，独立于 available/all 和占用豁免；不附全天金额。`summary_complete` 结合时间覆盖与待核对情况；合法的确定成员仍可在 available 模式保存，只有省略汇总而无确定成员时不能保存。
- 完整月读月统计，完整日读日统计，首尾部分日从事实按秒过滤；分段最多两段边界，不重叠。四视图、摘要、完整导出和冻结迭代使用同一选择。keyset 保留事件秒标量范围收紧。
- 查询 hash/游标绑定规范化起止秒与粒度政策；业务 hash 绑定实际区间。保留既有冻结成员摘要算法，不能为新增意图元数据改变历史成员身份。
- 新材料为 manifest4，四文件名称不变；范围、覆盖与不完整提示写入 JSON/HTML。保存/导出沿用最后成功预览，不重新解析跟随意图。
- 旧 manifest3 ZIP 重下载返回原字节；旧 frozen 修订保留原成员和范围。历史缺失的 `time_coverage/summary_complete/pending_count` 保留 null/未知，禁止根据当前台账补成“完整”。

## 4. 校验与错误矩阵

| 条件 | 结果 |
| --- | --- |
| 混合新旧时间字段、非布尔 follow_now、未知 preset/额外字段 | `invalid_time_range`，不登记分析 |
| 非法日期、倒置、year0000、规范化端点上溢/下溢 | `invalid_time_range`；组件预先阻止非法/不可表示端点和固定端点倒置；跟随范围以服务端本次 now 权威校验 |
| all 且本地无覆盖 | `invalid_time_range`，提示先同步 |
| 冻结范围与兼容日期不一致 | `invalid_time_range`，不能生成材料 |
| 不同实际时间复用游标、旧分析或占用变化 | 原 `invalid_cursor` / 409 失效规则 |
| all 或没有合法确定成员 | 沿用保存阻断，不用时间组件绕过 |

旧日期入口对最大日期的历史摘要行为保留；它不能伪造超出 ISO 上限的 `time_range`，原极端范围导出错误也不被新组件掩盖。

## 5. 正常、基础与错误场景

- 正常：10:00 至10:00 包含该分钟的 :00 至 :59，排除10:01:00；跨两天部分范围省略两个日汇总，同时保留范围内明细。
- 基础：没有部分日汇总时 `time_coverage.complete=true`；旧 frozen 缺失完整性信息显示未知，不能当新完整查询。
- 错误：用日汇总的零点投影当真实消费秒、按小时比例拆费、保存时重新取 now、因省略汇总禁止一切合法保存。

## 6. 必需测试

- `test_time_ranges`：一次取钟、各快捷意图、跨日/月/闰日、同分钟、非法端点、空覆盖、完整日/月分段、游标隔离和深页 VM 工作量。
- `test_http`：两个分析入口的新旧互斥、status.now、确认/预览/保存和目标身份；等待后保存的冻结边界不漂移。
- `test_time_ranges`：四视图与 CSV/HTML/JSON/冻结成员金额和 Token 一致；`test_independent_v3_zip_and_frozen_rows_survive_new_writer_and_fact_changes` 独立构造旧 manifest3 库/包验证原 SHA 与 frozen 修订。`test_evidence` 保留流式材料、转义和隐私等通用断言，不能只改新 writer 的期望版本冒充兼容验证。
- 真实浏览器：非北京时间、取消与确认、跟随/固定、A 提示、改查整天、当前和冻结修订；规模证据区分回归探测与完整目标平台验收。

## 7. 错误与正确做法

```python
# 错误：保存时移动范围，用全天费用替代未知的小时费用。
preview = store.analyze_time_range(intent)
saved = store.create_batch(store.analyze_time_range(intent), claim, key)

# 正确：冻结成功预览；范围内确定成员与粒度缺失分别解释。
preview = store.analyze_time_range(intent)
saved = store.create_batch(preview, claim, key)
```

界面组件与陈旧响应保护见 [前端组件](../frontend/component-guidelines.md) 和 [状态规则](../frontend/state-management.md)。
