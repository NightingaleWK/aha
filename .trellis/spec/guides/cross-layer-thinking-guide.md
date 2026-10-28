# 跨层修改思考指南

## 先画实际链路

```text
CCS SQLite/SQL → 允许投影与元数据 → Store 留存 → 归属/分析/可用成员
页面操作 → HTTP 参数与主体 → Store 写事务重检 → 有效版本/占用/原包
分析与冻结资料 → CSV/HTML/manifest/ZIP → 页面展示与指定版本下载
```

链路入口可对照 [sources.py](../../../src/aha/sources.py)、[archive.py](../../../src/aha/archive.py)、[server.py](../../../src/aha/server.py)、[storage.py](../../../src/aha/storage.py) 和 [app.js](../../../src/aha/web/app.js)。

## 修改前检查

- [ ] 记录每个 producer/consumer 的字段、默认值、空值、错误码和数据所有者；依 [后端契约](../backend/usage-evidence-contract.md) 与 [页面契约](../frontend/local-web-contract.md) 核对。
- [ ] 金额仍是精确十进制字符串、时间仍是北京时间整日、粒度和 capture 没有被隐式合并？
- [ ] 新字段会否改变原始身份、分类 revision、业务哈希、占用评估或分享投影？变更范围需逐一确认。
- [ ] 新建/修订主体与自身占用豁免是否绑定；过期页面和打开的弹窗如何失效？
- [ ] 迁移失败能否保留原库和原包；新写入是否仍与事件/幂等/有效版本一起提交？
- [ ] 本机启动凭证、Cookie、路径或元数据是否会穿入公开错误或分享包？

## 区分校验职责

HTTP 边界解析类型、格式、长度和请求来源，领域函数统一计算及投影；这些结果不能替代保存时的权威检查。页面预览后另一个进程可能修改占用，Store 必须在写事务内重新核对当前成员、claim revision、generation 和 active version。

- [ ] 共享解析是否由所属模块复用，避免不同消费者另写规则？
- [ ] 写入重检是否仍在同一个 `BEGIN IMMEDIATE` 内，而非只做一次入口判断？
- [ ] 同 key 重试、旧作废请求重放、失败换版和资料重启后是否维持原语义？

具体规则见 [SQLite 规范](../backend/database-guidelines.md) 与 [状态规范](../frontend/state-management.md)。

## 验证穿过边界

- [ ] 用真实 HTTP 请求确认输入/输出和错误，用独立连接/进程确认竞争，用实际浏览器确认 DOM 失效和下载。
- [ ] 对比预览、明细/每日、HTML/JSON 的同一成员与精确金额，不从页面分页回算全体。
- [ ] 对旧资料、历史版本和原 ZIP 核对保留，不用重新生成材料掩盖差异。
- [ ] Windows/Excel/打印结果按实际版本和执行时间记录，历史验收与本轮验证分开。

测试入口与触发条件见 [后端质量](../backend/quality-guidelines.md) 和 [前端质量](../frontend/quality-guidelines.md)。
