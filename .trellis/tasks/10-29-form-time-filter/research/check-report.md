# 独占质量复核记录

日期：2026-10-29。依据已批准的 PRD、design.md V0.2、implement.md 和 check.jsonl。审核范围为本任务 `src/aha/**`、`tests/**` 的实际改动及新增文件；本报告未提交代码，未修改来源或历史材料。

## Findings (fixed)

- File: `src/aha/web/app.js`，`renderPreview()`。
  - Issue: 成功响应有归属检查，但旧明细请求的迟到 409 仍可经 `api()` 默认路径清除新预览；迟到断连也会显示过时错误。
  - Fix: 把分析 ID、标签、游标、筛选代次和退出状态组成同一检查，传入 `api()` 并在异常路径使用；当前请求的权威 409 仍会清除分析、打开的 current 修订和保存身份。
- File: `src/aha/web/form-controls.js`。
  - Issue: 分段选择器把点击闭包绑定到原 option 对象；以相同文字和值重新创建 option 时不重建按钮，已脱离 select 的旧 option.index 变为 0，第二项点击错误选择第一项。方向键也可能选中 hidden 选项。
  - Fix: 按钮捕获数字索引，键盘候选排除 hidden；原 native select 继续拥有值与权限。
- File: `src/aha/web/time-range-picker.js`。
  - Issue: 支持上限的最后一分钟会使排他结束落入 10000 年，但面板原先仍允许确认；内部分钟校验也接受 0000 年。
  - Fix: 检查预览归一化后的两个端点均可表示为支持年份，超限时在面板内显示错误并禁用确认；拒绝 0000 年。服务端校验保持原状。
- File: `src/aha/web/app.js`，`renderBatches()`。
  - Issue: 报销列表收到规范化 time_range，却仍只显示日期，无法分辨同日不同时间的记录。
  - Fix: 复用 `rangeDescription()` 显示实际时间并注明北京时间；旧记录 day 精度仍只显示原起止日期，没有补判完整性。
- File: `src/aha/web/app.js`，`renderRevisionPreview()`。
  - Issue: 仅有被省略日汇总的 current 修订仍显示“0 条用量 / 0 USD”，与首页明确未知的显示不一致。
  - Fix: 复用首页的 omittedOnly / hasUsage 条件，显示“当前时段没有可确定的用量”，保留 A 完整性说明及禁用保存。
- File: `tests/web_state.test.cjs`。
  - Fix: 新增使用真实 app.js 和时间格式函数的 Node 标准库回归，延迟 fetch 响应验证旧错误/旧成功/断连不恢复或清除新状态、当前 409 仍失效、列表精确时间与旧日期兼容、修订未知用量不显示零成本且禁保存。对应缺陷用例均在修复前实际失败，修复后 6/6 通过。

## Findings (not fixed)

本次功能未发现仍待修复的范围内问题。

- `src/aha/web/app.js` 的既有 `response.json()` / `counts()` 边界会损失超过 2^53 的 JSON 数值精度。原文 `9223372036854775807` 在当前 Node 解析后显示为 `9,223,372,036,854,776,000`；后端、CSV、HTML 和冻结金额/Token 的 Python 整数与十进制逻辑仍精确。本任务未引入此问题。主会话已明确要求保留在本次功能范围外；若后续处理，应统一确定 API 大整数及页面展示合同，不在质量修复中悄悄更改公开字段类型。
- 实际 Windows 应用、HTTP 整链路、规模基准、目录包及规范同步由主会话负责；本报告的组件与状态回归不替代这些证据。正式发布、目标 Excel、A4 打印与 OneFile 不在本轮实施授权内。

## Verification

- Lint: pass。隔离运行时执行 `python -m ruff check src tests scripts`。
- TypeCheck: pass。`python -m mypy --cache-dir .aha-data/form-time-filter-check-mypy src/aha`，22 个源模块。
- Compile: pass。`python -m compileall -q src/aha`。
- JavaScript syntax: pass。三个产品脚本分别经 Windows Node `--input-type=commonjs --check` 从同一源文件标准输入检查，避免 UNC 读取限制。
- Tests: pass。`node --test tests/web_state.test.cjs`，6/6。Windows 临时目录保留同结构的脚本和产品文件副本运行；仓库测试本身不含个人运行时路径或外部依赖。
- Native Edge focused regression: pass。相同选项动态重建后的分段选择、跳过 hidden 的方向键、最后一分钟超限禁确认，均验证实际 DOM，无页面异常。
- Native Edge existing component suite: pass。重新运行实施者的隔离组件场景，覆盖项目搜索、键盘、程序回填/动态选项、禁用、取消、24 小时秒级锚点、分钟、闰日、dialog 内控件与错误、375px 边界、非北京时间浏览器。
- Native Edge 375×1000: pass。面板 `overflow:auto`，clientHeight 974 / scrollHeight 1038；Shift+Tab 自动滚动 64px 到确定，按钮 y=926.66–970.66，`:focus-visible` 为 solid 3px。鼠标内部滚动可到取消且不应用，键盘 Enter 可到确定且只应用一次。无需 CSS 修复。
- Backend baseline: 实施者本轮完整日志 `/tmp/aha-form-time-filter-backend-tests.log` 为 203 个用例通过，2 个平台跳过；本审查未改 Python 源码，因此未重复全套。已复核精确区间、互斥统计分段、A 遗漏与 pending/占用区分、目标豁免、游标、保存时不重读 clock、成员摘要、manifest4 及独立合成 v3 原包/旧冻结未知完整性的覆盖。
- `git diff --check`: pass。

规范复核：主会话已同步 README、时间合同、manifest4、共享组件与状态边界，并加入 `node --test tests/web_state.test.cjs`。最终复核也确认了跨层图使用 manifest4、v3 回归归属 test_time_ranges、跟随范围以本次服务端 now 权威验证、仅遗漏汇总的修订预览不能冒称零。本报告不修改这些归主会话所有的文档。
