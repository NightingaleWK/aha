# 全范围质量检查报告

- 日期：2026-11-13（Asia/Shanghai）。
- 角色：独立 Trellis check 子代理；已读取完整原生注入文件、PRD、设计、执行计划、后端索引及 check 上下文规范。
- 范围：domain 外部版本集合、sources/Store/HTTP/evidence 回归、原生验收脚本、README/后端兼容规范及新增中文变化片段。
- 结果：未发现需要修复或留待决策的代码问题，未修改产品、测试或规范文件。

## 合同核对

- 产品源码仅将显式外部支持集合从 `(23, 24, 25)` 扩为 `(23, 24, 25, 26)`；SQLite、SQL 和同步发布共用该集合，不放行未来版本。
- SQLite 必要表/列及只读事务、SQL 字面量解释/唯一真实版本声明、隐私白名单和失败清理路径保持既有实现。
- 版本升级回归检查相同投影、消费身份、两种来源指纹、facts/content versions、归属、占用与原包 SHA；内部投影23、应用schema4及manifest4作用域保持原合同。
- HTTP 新增26默认来源的startup及手动同步回归；默认路径与setUp夹具一致，job/ledger实际版本与27失败后的历史保留都有断言。
- 原生验收脚本实际执行23→24→25→26、SQL26、未知27失败/26恢复及26重启startup；独立恢复台账的26期望与源夹具一致，scope没有冒充物理托盘/Office或浏览器检查。
- README和后端索引/兼容合同/主契约/SQLite规范与26支持范围一致；新增fix片段未手工递增产品版本，已发布旧片段未改写。

## 实际验证

原生检查均通过任务 `run-native.py` 使用合成profile、隔离资料及独立缓存执行；解释器为已核实与公开v0.5.0一致的Windows x64 CPython3.15.2 / SQLite3.53.4。

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| 完整Python suite | 351 tests，459.901秒，OK，无跳过/失败 | `check-full-tests.log`、`check-full-tests-result.json` |
| Ruff：src/tests/scripts | 通过 | `check-ruff.log`、`check-ruff-result.json` |
| strict mypy：src/aha | 26 source files，无问题 | `check-mypy.log`、`check-mypy-result.json` |
| compileall：src/aha | 通过 | `check-compileall.log`、`check-compileall-result.json` |
| release validate：v0.5.0→WORKTREE | 通过，WSL Python与本机Git | `check-release-wsl.log`、`check-release-wsl-result.json` |
| Git diff whitespace | `git diff --check`通过 | 本次检查执行记录 |

实施代理的针对性回归另有独立通过记录：sources26、storage29、HTTP18、evidence6项。上述完整suite包含这些回归，也覆盖发布、备份/恢复、同步取消/超时、旧材料及原生成品验证器的边界测试。

## 校验宿主处理

原生Windows解释器直接对WSL UNC仓库执行release元数据校验时，Windows Git的`ls-files`失败，未进入片段校验；保留`check-release.log`及失败结果。随后用WSL Python+本机Git执行完全相同的release校验参数并通过，未修改产品或放宽校验规则。完整suite中的Git夹具使用Windows本地临时仓库，实际通过。

## 主会话剩余交付门禁

- Node检查、Directory/OneFile/桌面副本、真实26来源的隔离同步与清理由主会话完成；本报告不把源码suite当作成品验收。
- `domain.py`属于材料专项指纹范围，本次需要新的Excel/打印专项证据；托盘/配方源码未变，运行时相等已有独立核查。是否满足发布门禁应以最终候选指纹和真实回执为准。
- 本轮没有执行公开Release，也没有声明物理托盘或Office通过。
