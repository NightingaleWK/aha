# CI 短路径测试修复复核

结论：**Ready，可以提交这两处测试期望值修复并重跑 PR 最终 HEAD 的 CI。** 未发现需要修改产品或进一步削弱断言的问题。本次仅写此报告，未修改产品、测试或 Git 状态。

## 真实产品路径

- `server.py::_restore_upload` 在校验新目标和启动任务前调用 `destination.resolve()`，因此 HTTP 接受短路径输入，任务使用规范化后的路径。
- `backup.py::restore_backup` 对输出再次 `resolve()`，经隔离 staging 校验和不覆盖的目录发布后返回 `str(output)`。返回值没有要求逐字保留用户输入的 8.3 拼写。
- `server.py::_open_restored` 取已完成结果中的 `destination`，检查该目录的 `aha.sqlite3`，再由 `_restored_command` 生成 `--data-dir` 参数。

因此 RUNNER~1 与 runneradmin 的差异应在测试的预期路径上规范化。两处改用 `target.resolve(strict=True)` 正好验证上述 API/打开命令的实际合同；strict=True 还要求还原目标真实存在，未将断言放宽成仅文件名相同、任意目标或字符串包含。

## 业务覆盖保持

实际恢复请求仍传 `str(target)`，没有预先消除临时根的短路径，所以 CI 原先暴露的短路径输入仍被执行。测试继续检查完成终态、归档 SHA、restore-info、独立 Store 重开后的原冻结材料 SHA、恢复/当前台账 counts、恢复后来源重绑以及打开目标参数；没有删除或跳过任何业务断言，也没有触碰路径防嵌套、原目录不覆盖、鉴权或 SQLite 门禁。

## 验证边界

本轮读取了实际两处 diff、故障记录、测试完整业务流程、恢复/打开入口实现及恢复合同。静态语义复核通过；Ruff/AST 的执行状态沿用主会话记录，本子代理没有重复执行。原生 Python 3.15.2 定向测试和更新后完整 CI 仍由主会话执行，未将原先 350/351 或本机其他运行时结果写成新源码全部通过。
