# 换机数据接续与完整备份：全范围独立检查

日期：2026-11-12。角色trellis-check。检查R1–R8的产品实现与自动验证；未访问或修改真实台账/CCS/恢复副本，未提交Git。真实资料接续、浏览器/Office、Directory/OneFile和桌面交付由主会话验收，本报告不冒称这些已经通过。

## 已修复发现

1. **完整恢复漏检索引约束**：局部检查已复现额外唯一来源索引能随正确重算的manifest还原，随后合法来源导入失败。`backup.py`已比较table/index/trigger DDL；`test_backup.py`新增额外约束、缺索引和索引篡改回归。局部20项通过，详见子任务`research/check-report.md`。
2. **目录候选可能永久过期却仍显示开放**：已有directory候选后，同一cwd的parent_id更新会改变当前metadata hash，原case永远stale。`sync._rebase_directory_cases`保留候选版本和内容，旧case supersede并推进generation，基于新当前hash建立可操作的新case；旧请求仍拒绝。新增`test_auxiliary_metadata_change_keeps_directory_candidates_actionable`验证刷新、旧请求拒绝与候选可确认。
3. **退出门禁与transfer取消间存在间隙**：`Application.close`及`LocalHTTPServer.mark_stopping`原先先取消transfer，再设置closed；当前都在同一RLock内先关闭分配门禁再取消，close同时获取worker快照。生成备份前也先拒绝closed。原生隔离复现证实旧mark_stopping在取消后仍可分配上传；新增`test_shutdown_closes_allocation_gate_before_cancelling_transfers`及`test_mark_stopping_closes_allocation_gate_before_cancelling_transfers`，覆盖门禁、无暂存分配及既有取消信号。
4. **核对后焦点落在已隐藏select**：AhaForms隐藏原生select，旧选择器会找到无法聚焦的元素。页面现在优先可用combobox/可见select/按钮，仅在核对dialog仍打开且程序未停止时恢复焦点；实际浏览器焦点由主会话补验。
5. **旧别名费用测试遗漏新确认步骤**：原`test_confirmed_alias_cost_revision_can_be_frozen_without_changing_old_package`假定身份确认后异来源异值自动采用，与本次明确保护合同冲突。现保留其全部费用、冻结材料、作废/占用断言，并先验证revision当前/候选金额、原包未变，再明确采用候选。未放宽产品保护或删除回归。
6. **最终QA捕获脚本错误启动子进程与发现路径**：检查代理自己增加的`research/run-final-suite.py`首版缺`__main__`保护，multiprocessing的spawn导入重新执行测试；文件入口又未把仓库根加入sys.path，令`test_rebuild_trial_data`导入scripts失败。已补入口保护和仓库根，并改成持续写完整日志。失败一轮301项、2并发ready超时和1导入错误完整保存在`python-test-runner-failure-{result.json,log.txt}`，未计作产品通过。修后同入口的5项跨进程竞争和16项重建测试全部通过，证明并非以环境问题豁免失败。

## 范围检查

- **R1/R3/R4**：来源位置与设备/restore_id绑定分开；旧SQLite历史缺当前绑定在run创建前阻断源接续，历史可查。全局消费key、历史版本/claims/包不重写；异源异值留候选，明确current决定不会被下次同步隐式接受。相同异源日汇总以rollup_origin确认范围，不盲加。missing保留历史matched cwd/项目，目录冲突有明确候选和代际。
- **R2**：严格支持外部23/24/25，内部projection保持23；SQLite必要字段、SQL唯一字面版本声明与未知26拒绝保留，版本不进入消费身份/内容hash或旧冻结包回填。
- **R5**：空筛选解释与全历史入口保留原时间意图；全历史切all只读。核对请求先使保存身份过期，再按当前筛选重预览；旧成功/异常不覆盖新状态，动态AhaForms正确销毁并重建。
- **R6**：一致WAL快照、所有修订原包、完整DB与objects；有界分块上传/下载、清单/DDL/外键/文件SHA验证、新目录原子无覆盖发布。HTTP保持Host/Cookie/Origin/CSRF，offset/长度/类型检查、取消/丢响应上传清理、程序关闭的worker等待与暂存清理。离线CLI不创建源Store/服务/同步。
- **R7/R8**：主会话已提供真实副本回执；本代理不以其替代自己的执行，也不把源码测试当成真实原库修复或成品交付。新恢复规范及README/API说明与本次实现边界一致；版本仍由发布PR统一递增。

## 实际自动验证

环境：原生Windows CPython3.12.16 x64 / SQLite3.53.1，任务qa312，runner默认隔离完整profile，不放宽SQLite门禁。

- 第一轮全套：310项，416.066秒；唯一失败是第5项所述旧断言，已完成契约适配。
- 修复后定向：换机/目录/安装身份15项、HTTP备份最终11项、报销冻结14项，全部通过。
- QA捕获脚本修后定向：跨进程竞争5项、重建16项，全部通过且无跳过。mark_stopping最终修复前曾启动一轮完整验证，运行约2分钟后按精确识别的本代理runner进程树停止；该未完成轮次不计通过。
- Ruff全量`src tests scripts`：通过。
- strict mypy全`src/aha`24文件：通过，使用任务Windows绝对独立cache与`--no-incremental`。
- compileall全`src/aha`：通过。
- app/form-controls/time-range-picker三个JS语法：通过。
- Node页面状态：34项通过，0失败、0跳过（修复后再次执行）。
- `git diff --check`：通过。
- **最终冻结源码完整Python复跑：317项全部通过，0 failures、0 errors、0 skips**。unittest执行415.661秒，包含收集总418.156秒，完成于2026-11-12 10:55:28 +08:00。同目录`python-test-result.json`与完整`python-test-log.txt`为终态证据；该轮包含mark_stopping最终修复与新回归、完整20项备份及新增Windows verifier传输检查。
- `check-source-freeze.json`记录本轮60个产品/测试/Windows verifier文件SHA；终态再次比对全部一致，changed/missing/added均为空。最终Ruff、strict mypy、compileall均在mark_stopping修后执行；Node34项结果对应同一未再改动的JS文件。

## 未修复发现及交接

无仍阻断本次产品源码质量的未修复发现。产品源码已冻结，已通知主会话按最终server.py重新构建全部成品。新恢复规范覆盖本次索引、目录候选代际和关闭分配门禁合同，无新增文档同步缺口；没有扩大为多业务库的报销占用合并。

真实资料副本、当前原库接续、原生浏览器/Excel/A4/托盘专项、Directory/OneFile与实际桌面副本、清理及发版评估均由主会话继续；不能以本检查结果替代。
