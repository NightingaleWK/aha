# 代码复用思考指南

## 先找到现有所有者

修改或新增辅助逻辑前先检索，不从模板推断需要新框架：

```bash
rg -n 'decimal_value|fresh_input|record_key|row_fingerprint' src tests
rg -n 'claim_snapshot|evaluate|create_batch' src/aha tests
rg -n 'invalidate|prepareBatch|function node' src/aha/web/app.js
```

| 需要修改的概念 | 先看哪里 |
| --- | --- |
| 数值、日期、记录 key/指纹 | [domain.py](../../../src/aha/domain.py) |
| 跨平台目录含义和归属 | [projects.py](../../../src/aha/projects.py) |
| 可用成员和身份/覆盖 | [claims.py](../../../src/aha/claims.py) |
| token、费用、每日/模型汇总 | [queries.py](../../../src/aha/queries.py) 与 [decimal_sql.py](../../../src/aha/decimal_sql.py) |
| 持久化、版本与幂等 | [Store 门面](../../../src/aha/storage.py) 与 [batches.py](../../../src/aha/batches.py) |
| 元素、请求、忙碌与失效 | [app.js](../../../src/aha/web/app.js) 的 node/api/run/invalidate |

## 决定复用还是扩展

- [ ] 新逻辑表达的是同一业务概念，还是只有相同字面值？只有需要同步变化的稳定概念才共享。
- [ ] 是否已经有多个消费者使用同一校验/投影？先复用所有者，不在 UI/evidence 另算金额或另判可用成员。
- [ ] 修改某个字段是否会同时影响来源归一化、身份、留存、预览、材料和测试？沿消费者查全。
- [ ] 辅助函数是否可以留在所属领域？不要为了一个局部调用建通用抽象层或新的 Store 旁路。
- [ ] 对重复边界检查，是否实际上是不同时间点的权威验证？不要把事务内重检误当可删重复。

## 修改后

- [ ] 用 rg 复查旧字段/常量/分支，确认同一概念的消费者已同步。
- [ ] 测试观察正确金额、成员和原包，而不是只观察两个实现给出相同结果。
- [ ] 复用没有改变冻结身份、哈希范围或历史材料字节。

模块职责见 [后端目录](../backend/directory-structure.md)，请求/失效复用见 [前端状态](../frontend/state-management.md)，格式与事务检查的不同职责见 [跨层指南](./cross-layer-thinking-guide.md)。
