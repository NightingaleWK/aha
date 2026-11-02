# 独立代码检查

日期：2026-11-02。检查角色：trellis-check。范围为当前完整产品 diff、README/版本信息及相关测试；未修改产品代码。

## 发现与处理

- 未发现需要修复的产品问题。
- 已沿 SQLite/SQL → staging → 发布结果 → HTTP/本地分析 → 冻结材料核对外部版本 23/24 与内部投影版本 23 的区分。
- SQLite 在 sink 前拒绝未知版本，必要表/字段检查、有界只读事务与取消处理继续保留。SQL 只接受唯一的受支持版本声明，不执行输入 SQL；失败暂存会清理，旧事实、版本和最近成功时间保持。
- 外部版本元数据不进入记录身份、内容指纹或允许投影指纹；同源 23→24 不重复计量，既有人工归属、占用及原包 SHA 回归已覆盖。
- 同步结果仅标记本轮实际外部版本；旧历史投影缺失版本仍为未知。新分析/材料明确投影版本和旧兼容字段作用域，不用最近同步版本冒充全部历史来源。
- 版本元数据一致为 0.3.1；应用 schema3、规范化投影 23、manifest4 和四文件材料格式保持既有兼容边界。没有源码中遗漏的旧 domain.SCHEMA_VERSION 导入。

## 验证

- 独立运行 `ruff check src tests scripts`：通过。
- 独立运行 strict `mypy src/aha`：22 个源文件通过；独立缓存位于任务临时根的 `check-mypy`。
- `git diff --check`：通过。
- 已核查实施代理本轮完整 Linux 日志：211 项测试，OK，跳过 2 项平台限定用例。日志为 `/tmp/aha-ccs-schema-compatibility-01a199ff/implement-linux-tests.log`；本检查未改产品代码，未无理由重复完整测试。

## 源码依据

- 检查时产品源码指纹：`f02947a38d7b3ccb893ab5387a79d6be3eee497c15b23e7a30b0fa03a345e6f5`。
- 覆盖 `git ls-files src scripts pyproject.toml` 的 38 个文件。算法：按仓库相对路径排序，每个文件串接 UTF-8 路径、NUL、文件内容原始 SHA256 字节，最后对整体求 SHA256。
- 检查时产品/测试改动共 13 个文件：README.md、pyproject.toml、src/aha/{__init__,domain,evidence,queries,sources,sql_dump,sync}.py、tests/test_{evidence,http,sources,storage}.py。

## 后续交付边界

主会话负责将旧 schema23-only 规范同步为当前外部 23/24、内部投影 23 合同，并完成 Windows 原生完整测试、真实来源与旧资料隔离副本核对、Directory/OneFile/桌面副本与浏览器材料验收、清理和收尾。本检查不把 Linux 回归或代码审阅写成 Windows 成品已通过；产品源码若在此后变更，须重新检查对应改动并重建成品。

主会话已按规范复核建议收紧实际来源版本字段的描述：仅 `_publish` 的本轮结果保证 23/24 或旧投影 null；失败及升级前旧 run 可缺少字段，不从其他 run 推断。产品代码未变。

## 规范同步复核

2026-11-02 追加检查 `ccs-source-compatibility.md`、后端 index、database-guidelines 和 usage-evidence-contract，对照最终源码及获批 design。

- 外部 23/24、内部投影 23、应用 schema3、未知未来版本拒绝、SQL 唯一版本声明、指纹与身份稳定、manifest4 兼容作用域和旧包原字节合同均与实现一致。
- 当前 spec/README 未发现残留的“仅支持 CCS23”现行声明；历史投影格式 23 和应用 schema3 的说明属于不同协议，不能当成遗漏替换。
- 32 条本地 Markdown 链接全部有效；产品源码指纹仍为 `f02947a38d7b3ccb893ab5387a79d6be3eee497c15b23e7a30b0fa03a345e6f5`，本次仅审文档，不重复产品测试。
- 向主会话提交 1 处文字纠正：新兼容规范第 3 节应把实际外部版本持久化限定到 `_publish` 结果（含 needs_review）。`_failed` 不写该字段，升级前旧 run 也可能缺失字段；仅本轮新导入且缺来源版本的旧内部投影明确输出 null。不能把“观察到”概括成失败/旧 run 都有 23/24 或 null。
- 本角色按责任边界未编辑 spec；此文字纠正由主会话落地，且不要求修改产品行为或重建已通过的源码产物。
