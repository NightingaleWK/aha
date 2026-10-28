# 跨层修改思考指南

## 实际链路

```text
只读CCS SQLite/受限SQL → staging → 身份/版本/覆盖核对 → 本地SQLite事实与精确日聚合
页面筛选 → HTTP边界 → 本地分析/游标 → 保存事务重检 → 冻结版本/占用/事件/原包
冻结行 → 流式CSV/HTML/manifest3/ZIP → 指定版本下载
```

入口是 sources/sql_dump、sync/ledger、queries/storage、claims/batches/evidence、server 和 web/app.js。查询不重新读取CCS、不解压历史capture。

## 检查边界

- 字段、默认值、空值、错误码及所有者在 [后端](../backend/usage-evidence-contract.md) 和 [页面](../frontend/local-web-contract.md) 对齐。
- 身份与内容hash分离；金额精确字符串，北京时间整日；detail与rollup覆盖只计一次，未知需核对。
- 变更是否影响 data/classification/claim revision、分页、别名、冻结成员或分享投影？打开的current修订如何失效？
- 读取失败/取消/源缩水待核对后，旧事实、聚合和成功时间是否保留？新epoch是否经过明确核对？
- 写事务内重检当前版本、generation、主体、占用与幂等；预览不是占用证明。
- 新库拒绝schema1/2；一次性清理只能删除已核实试用allowlist，先保全历史CCS输入与完整恢复副本。
- 凭证、源路径、完整目录、会话正文不能穿入分享包或公开错误。

## 穿过边界验证

实际HTTP看输入输出，双连接/进程看竞争，真实浏览器看job终态、DOM失效和下载。对比预览、游标页、聚合、manifest和ZIP的同一冻结成员与精确合计；旧包核对原SHA。百万/千万和Windows/Excel/打印写实际版本、介质与时间，不用历史证据替代当前验证。

复用入口见 [复用指南](./code-reuse-thinking-guide.md)，质量门禁见 [后端](../backend/quality-guidelines.md) 与 [前端](../frontend/quality-guidelines.md)。
