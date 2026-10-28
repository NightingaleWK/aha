# 本机页面与 HTTP 契约

## 1. 范围与触发条件

修改 `src/aha/web/` 或 HTTP payload 前阅读。界面是 [server.py](../../../src/aha/server.py) 提供的原生 HTML/CSS/JavaScript；没有前端框架、打包器、远程资源或外部服务。产品文案使用简体中文。

## 2. 函数与接口

[app.js](../../../src/aha/web/app.js) 管理 state、`api(path, body?)`、`run(label, action)`、`invalidate()`、`prepareBatch(payload, batchId?)`、`saveBatch()` 和 `download(id, version)`。

| 接口 | 请求或响应 |
| --- | --- |
| `GET /api/status` | 当前启动 CSRF、日期、时区、默认来源可用性等 |
| `GET /api/captures`、`GET /api/captures/{id}` | captures 列表、当前 capture 及目录依据描述 |
| `POST /api/source/sql` | `{name, content_base64}`；有界导入并留存新 capture |
| `POST /api/source/sqlite` | `{path}`；空字符串使用当前操作系统用户的默认路径 |
| `POST /api/session-metadata` | `{capture_id, roots?: string[]}`；刷新目录依据 |
| `GET /api/projects` | 当前 config |
| `POST /api/projects`、`POST /api/projects/{id}` | 创建/修改项目，`name/description/directories`，名称最多 160 字符 |
| `POST /api/assignments` | `capture_id/kind/project_id` 加 keys 或 session_ids；明细可按会话，rollup 必须完整记录 |
| `POST /api/analysis` | capture/project/起止日期、classification_revision、`availability_mode=available\|all`；新建或只读分析 |
| `POST /api/batches/{id}/analysis` | 修订筛选、base_version、expected_generation；有效草稿主体 |
| `GET /api/analysis/{id}/details` | `kind=detail\|rollup`、page、size（1–200），返回分页行与总数 |
| `POST /api/batches/preview` | 新建分析或有效版冻结依据，返回 conflicts/overlaps/blocking，不绕过阻断 |
| `POST /api/batches` | analysis/claim、idempotency_key；保存冻结草稿版 |
| `GET /api/batches`、`GET /api/batches/{id}` | 批次列表及版本/状态/操作历史详情 |
| `POST /api/batches/{id}/revisions` | base_version/expected_generation/claim/idempotency_key、可选 analysis_id；原子换有效草稿 |
| `POST /api/batches/{id}/revisions/{n}/status` | `{status,expected_generation}`；有效版状态变更 |
| `POST /api/batches/{id}/withdraw`、`/void` | `{reason,expected_generation,idempotency_key}`；撤回保留占用，作废释放 |
| `POST /api/batches/{id}/resolve` | 生命周期字段加 selected_version；明确旧候选保留版 |
| `GET /api/batches/{id}/revisions/{n}/download` | 原 ZIP，UTF-8 Content-Disposition |
| `POST /api/shutdown` | 认证后退出本机程序 |

表中为调用摘要，字段可选和输入规则见服务端相应处理函数及 [数据边界](./type-safety.md)。

## 3. 交互与数据契约

### 请求、失效和幂等

- api 发送 same-origin Cookie、JSON、X-AHA-CSRF，使用已认证的本次启动 origin；Cookie 按实际端口命名，由浏览器管理。不要硬编码 Cookie 名或将 bootstrap 凭证写进业务链接、日志和导出。
- 来源、元数据、目录规则、人工归属、筛选和占用变化使预览失效：清旧指标/选择、禁新建。analysis_expired/classification_changed/availability_changed/usage_claimed 还须清打开的 **current** 修订 analysis、替换更新提示并禁保存；frozen 修订重试保留其依据。导入失败不能继续把旧来源显示成新成功。
- 后端负责核算，前端展示金额原字符串，只有计数用数值格式化；不从可见页算总额。`analysis.availability` 具有 `matched_summary/available_summary/excluded_summary/excluded_groups` 和排除原因/所有者；all 行带 usage_state/usage_reason/usage_owners。新建默认 available，all 或零可用不能保存。
- run 串行操作、显示 busy，并在异常后恢复控件；未改变的 pending 保存请求保留幂等 key，网络重试不能产生第二条申请。
- 可选字符串缺省时省略。新建预检无 batch_id，后端对此字段兼容 null/空字符串，其他通过 `_string` 的字段仍须是字符串。修订预检带真实稳定 batch ID；project_id/amount 的空值按各自领域规则处理。
- 阻断冲突展示对应记录导航与刷新，不提供继续绕过。pending 请求绑定实际 analysis 或有效冻结修订与 claim；不同 payload 使用新 key。成功请求可在预览过期/重启后按持久签名重放。下载成功不会自动提交或报销。

### 生命周期、保存与展示

- 按 is_effective/lifecycle/generation/can_* 生成动作；历史/作废版始终可下载。仅有效草稿可改；已提交明确带原因撤回，已报销纠错明确作废再新建。作废须原因且为终态。旧候选须明确带原因确认，不能把最新版自动标为有效。
- revision-basis=current 调专用目标批次分析，可沿用自身占用；独立 capture/project/date 控件变更后禁保存至新预览。新建不能借用此豁免，主页面可用预览不能静默变成修订依据。
- 创建先保存再下载，下载失败须说明已保存并可在记录重下；重下始终使用指定原版本接口。
- 用户/来源文字用 DOM 创建与 textContent，不拼 innerHTML；CSV/报告由后端按其规则转义。
- 用途/金额说明各最多 4000 字符；金额可空或零，填写时须依据且币种 CNY/USD。参考 USD 成本与申请金额分开展示。
- 新建成功清用途/金额/说明，币种可保留；范围变化提示重新核对，不按比例分配或把旧金额带到下一条申请。
- 默认来源随平台变化；Windows 会话可含 Linux cwd，既支持发现目录选择，也支持手工绑定文本。
- 关浏览器标签不停止服务，退出按钮调认证 shutdown，不删除项目、留存和原包。

### 字号与产品表达

正文/输入基础 16px，表格/按钮 15px，标签/表头 14px，次要至少 13px；主要控件约 44px，小按钮减内边距而非可读字号。系统字体、正常中文字距、数字对齐、换行/容器滚动，响应式不缩到 9–11px。

保留青绿、深色导航和卡片风格，标题为“用量与费用/项目管理/报销记录”，动作表达“保存并下载/修改报销记录/下载材料”。口径说明放按需帮助，不加入宣传语、助手旁白、重复免责声明或内部 epoch/协议细节。主要顺序为筛选→指标→必要排除说明→申请表单→可选长预览，保存不埋在大量明细之后。成功短浮动，操作错误持续可见并进入当前弹窗。

## 4. 校验与错误矩阵

| 条件 | 界面行为 |
| --- | --- |
| 无 capture 或新鲜分析 | 空态并禁新建 |
| 零可用或全部占用 | 禁新建、显示原因/所有者和下一步，不能称为零消耗 |
| 元数据缺失/冲突 | 显示覆盖说明，未归属记录仍可使用 |
| 金额无效或缺依据 | 可操作校验，不创建记录 |
| analysis_expired/classification_changed/availability_changed/usage_claimed | 清主页面及受影响 current 修订预览，禁保存，要求更新 |
| stale_batch/inactive_revision/batch_voided | 保留失败操作提示，刷新记录并重开当前版再重试 |
| 网络/下载失败 | 可见错误，保留已存记录与相应重试身份 |
| 阻断重叠或旧候选模糊 | 显示原因和现有记录，不绕过 |
| 撤回/作废缺原因 | 弹窗不关，说明必填 |
| 未知来源结构 | 显示来源错误，不静默换源 |

## 5. 正常、基础与错误场景

- 正常：占用一批成员后其他记录只取余量，修订当前草稿，带原因作废后仍能下载原字节。
- 基础：未配置项目时按日期导出、申请金额空、元数据缺失或只有历史日汇总。
- 错误：失效弹窗仍可保存、新建预览冒充自豁免修订、缩字适配列宽、截断币种、成功后残留旧错误，或把目录依据当业务归属证明。

## 6. 测试要求

运行 Node 语法与完整 HTTP 测试，命令见 [前端质量要求](./quality-guidelines.md)。跨层变更须实际浏览器操作，Store 直调不能验证前端请求形状。

浏览器发布链路包括 SQL 导入、项目/日期/历史、元数据、占用→余量→旧预览阻断→目标修订→撤回→作废→重用→旧请求重放→重启/原包→退出；另覆盖旧冲突消解和真实的**已打开修订弹窗**失效。核对 computed style、1440/1366/1280 和 430/375 截图、长名称/金额、币种完整、空/错误和弹窗反馈。真实显示不能由 CSS 字符串测试替代，像素密度不是浏览器缩放；个人证据在 Git 外。

参考 [test_http.py](../../../tests/test_http.py)、[test_http_cli.py](../../../tests/test_http_cli.py) 和 [后端契约](../backend/usage-evidence-contract.md) 的断言点。历史原生验收与当前检查分别记录。

## 7. 错误与正确做法

```javascript
// 错误：只清主页面，current 修订弹窗仍能保存旧依据。
invalidate();

// 正确：受影响的当前修订分析也清空并禁保存。
invalidate("用量已变化，请更新预览");
if (state.revision && $("revision-basis").value === "current") {
  state.revision.analysis = null;
  $("revision-preview").replaceChildren(node("p", "", "用量已变化，请点击“更新用量”。"));
  syncActions();
}
```

实际实现见 [app.js](../../../src/aha/web/app.js) 的 api 分支；请求入口与服务端权威重检分别说明在 [状态规范](./state-management.md) 和 [SQLite 规范](../backend/database-guidelines.md)。
