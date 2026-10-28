# JavaScript 数据边界

页面为原生 JavaScript，没有 TypeScript 构建。HTTP 负责类型、格式和长度，Store 写事务负责事实与占用的权威重检。参考 [页面契约](./local-web-contract.md) 和 [后端契约](../backend/usage-evidence-contract.md)。

## 金额与空值

参考成本和申请金额都是十进制字符串。money 只处理显示末尾零，counts 才转数值；禁止 parseFloat/Number 求财务合计。claim 从表单取 trim 后字符串；空字符串由后端规范为 null，字符串 `"0"` 是有效金额且须依据，数字0不是输入金额类型。使用 `??` 保留空值与零的区别。

purpose/amount_note 最多4000字符，金额输入最长40字符，币种 CNY/USD。可选 batch_id 缺省应省略，预检兼容 null/空不代表所有字符串可接受 null。project_id=null 表示未归属。

## 记录、版本与游标

版本/generation 是整数，拒绝 bool。kind 为 detail/rollup/daily/models，size1–200；cursor 是服务端签发的不透明字符串，绑定筛选与 revision，不从行号构造。total 可以 null，不据此显示0条或禁下一页。

选中行使用稳定 record_key；分配发送 keys 或 session_ids，不发送 capture_id，不用显示名、页号或原始来源路径定义身份。服务端处理别名与内容修订。analysis 响应不附全量 details/members；聚合与明细按游标读取。

## 验证

UI 依据 can_* 展示动作，但不能绕过服务器状态；禁止在渲染中修改 payload 或将来源文本拼进 HTML。字段变化先查 producer/consumer，再用真实 HTTP 验证。测试入口为 test_http.py、test_analysis.py、test_evidence.py；真实浏览器覆盖同步终态、total=null 分页及打开的修订弹窗失效。
