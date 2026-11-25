# 北京时间范围与冻结材料

## 1. 范围与触发条件

修改首页或当前修订的时间筛选、查询统计、游标、冻结或导出时阅读。所有链路复用 time_ranges.py 的北京时间半开区间，按照已解析边界筛选逐笔明细。

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
- 响应 time_range 包含 version=1、timezone、start_at、end_before、precision、intent 和 resolved_at。两个端点为含 +08:00 的秒级 ISO 字符串，precision 为 day、minute 或 second。start_date 和 end_date 继续提供覆盖日期。
- `GET /api/status.now` 是服务端北京时间秒级 ISO。浏览器时区不能改变选择；旧 `intent.kind=legacy_dates` 是内部兼容元数据，不能直接当作新请求意图发回。
- 当前预览用 pending_count 和 summary_complete 表示未核对的用量。部分自然日按真实事件秒筛选。
- 完整月读月统计，完整日读日统计，首尾部分日从逐笔事实按秒过滤。分段最多两段边界，粒度视图、摘要、导出和冻结迭代使用同一选择。事件游标继续收紧标量时间范围。
- 查询 hash 和游标绑定规范化起止秒，业务 hash 绑定实际区间。冻结成员摘要继续用其版本所保存的成员。
- 新材料为 manifest 5。四个文件及其成员来自最后一次成功分析，保存与导出沿用该分析的实际范围。
- 已登记的旧 ZIP 按原文件下载。历史冻结信息按原记录查询，缺失的完整性仍显示未知。包含旧汇总的批次支持查阅、下载和状态操作。

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

- 10:00 至 10:00 包含该分钟的 :00 至 :59。跨日范围按实际事件时间聚合所选明细。
- 旧材料展示其实际保存范围，历史完整性缺失时显示未知。
- 从同一个成功预览冻结成员和范围，防止保存时因重新解析当前时刻而改变成员。

## 6. 必需测试

- `test_time_ranges`：一次取钟、各快捷意图、跨日/月/闰日、同分钟、非法端点、空覆盖、完整日/月分段、游标隔离和深页 VM 工作量。
- `test_http`：两个分析入口的新旧互斥、status.now、确认/预览/保存和目标身份；等待后保存的冻结边界不漂移。
- test_time_ranges 和 test_evidence 覆盖按日、按模型、逐笔、CSV、HTML、JSON 和冻结成员的金额与 Token 一致，以及历史 ZIP 原 SHA。
- 真实浏览器覆盖非北京时间、取消和确认、跟随与固定、当前及冻结修订。

## 7. 错误与正确做法

```python
# 重新分析可能改变跟随范围。
preview = store.analyze_time_range(intent)
saved = store.create_batch(store.analyze_time_range(intent), claim, key)

# 用已成功的预览冻结范围内的明细。
preview = store.analyze_time_range(intent)
saved = store.create_batch(preview, claim, key)
```

界面组件与陈旧响应保护见 [前端组件](../frontend/component-guidelines.md) 和 [状态规则](../frontend/state-management.md)。
