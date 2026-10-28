# JavaScript 数据边界

## 当前类型方式

页面是原生 JavaScript，没有 TypeScript 构建或运行时 schema 库。对象来自 api 和页面表单，服务端由 [server.py](../../../src/aha/server.py) 的 `_string/_strings/_project_id/_version/_generation` 及领域函数强制校验。前端检查用于及时反馈，不能代替写事务内的版本/占用重检。

业务字段、金额和状态以 [页面契约](./local-web-contract.md) 和 [后端契约](../backend/usage-evidence-contract.md) 为准，不在每个渲染点自创另一套允许值。

## 金额、空值和计数

- 参考成本与申请金额按十进制字符串流转；money 只去除显示末尾零，counts 才使用数值格式化。不要用 parseFloat/Number 后求和或将金额 toFixed 成另一份账。
- `claim()` 从输入取字符串，`validateClaim` 做非负/两位小数/依据提示；服务器的 `validate_claim` 再强制币种 CNY/USD、长度、金额格式和说明。
- `claim()` 发出的是 trim 后的金额字符串，未填时发空字符串；后端 `validate_claim` 将 None/空字符串规范为 None，保存及 JSON 响应中表示为 null。字符串金额 `"0"` 有效且须依据，数字类型 0 不符合金额输入契约。使用 `??` 保留值/空语义，不用真假判断将其混淆。真实修订填值示例：

```javascript
$("revision-amount").value = revision.claim.amount ?? "";
```

金额条件的标准以 [evidence.py](../../../src/aha/evidence.py) 为准，当前 purpose/amount_note 最多各 4000 字符，金额字符串最多 40 字符。

## 可选字段与真实 payload

新批次预检缺少 batch_id 时应省略该字段；实际准备代码为：

```javascript
const previewRequest = {...request};
if (batchId) previewRequest.batch_id = batchId;
```

该预检字段后端兼容 null/空字符串以照顾旧页面；这不表示所有字符串字段都可发 null。通过 `_string` 的字段要求字符串；人工分配的 project_id 可为 null 表示未归属，申请金额也有单独空值规则。不要将这些不同边界统一强转成字符串。

版本/generation 是整数，服务端拒绝 bool 充数。分页 kind 是 detail/rollup，每页 1–200，页面当前按 50 条请求；不要将页面行数当全体成员数。

UI 使用服务端 `can_*` 和生命周期信息生成动作，安全写入仍由后端判断。页面按 record_key 选中行并发送 keys，后端从所选 capture 找回原行，人工覆盖再绑定其 content fingerprint；页面不需要在分配请求里另传指纹。不能通过行号或项目显示名重新定义记录。

## 常见错误与验证

禁止在渲染器中更改原始 payload、将来源文字拼进 HTML、依据缺省值伪造“零消耗”，或给 revision 请求借用 main analysis。可选字段调整先全仓检索 producer/consumer，再做完整 HTTP 请求形状测试。

[test_http.py](../../../tests/test_http.py) 的 `test_browser_preview_and_revision_subject_cannot_be_borrowed_by_new_claim` 检查主体；[test_evidence.py](../../../tests/test_evidence.py) 的 `test_amount_validation_distinguishes_blank_zero_and_invalid_inputs` 检查金额；[test_analysis.py](../../../tests/test_analysis.py) 检查完整成员和精确金额。
