# 完整备份核心与CLI独立检查

日期：2026-11-12。角色：trellis-check；范围为`backup.py`、`__main__.py`离线模式、Store备份门面及`test_backup*.py`。未访问真实用户库/恢复副本，未执行Git写入或默认资料启动；HTTP/UI、来源模块由其他代理负责。

## 发现与修复

### 恢复DDL未校验索引，可能接受无法继续使用的台账

- 原位置：`src/aha/backup.py:103-154`，只比较表和trigger定义，索引不在结构验证范围。
- Windows合成复现：备份DB增加`CREATE UNIQUE INDEX unexpected_source_kind ON source_profiles(kind)`并正确重算manifest后，`restore_backup`原先成功；恢复库导入第二个合法SQL来源失败为`storage_write_failed`。这不是只看SQL文本推断的缺口。
- 主会话原生只读核实当前用户库显式索引与生产DDL一致（23/23，无missing/extra/different），明确批准按格式v1严格检查全部index DDL；本代理未检查真实资料。
- 修复：生产DDL快照与恢复校验一起比较table/index/trigger，保持SQL空白规范化，明确拒绝不兼容的索引或历史保护结构；不自动改写旧源库。
- 回归：`tests/test_backup.py:474`新增4种实际变造包：额外唯一来源约束、删除同步唯一索引、同名改成非唯一索引、查询索引列次序变造。每项都要求拒绝、目标目录不发布、staging清理、原台账仍可查询。

## 其他审查结论

- 一致快照：独立只读事务经SQLite backup API提取，包含已提交WAL；释放源连接后才做材料归档，不长占writer。
- 材料边界：从快照全部revisions登记校验原ZIP，保留历史/作废版本及占用；`objects`保全，运行凭证/锁/临时文件/嵌套备份明确排除，未知持久文件不静默删除。
- 输入边界：文件数/压缩与展开体积/清单/中央目录有界；中央目录在ZipFile分配前预检；路径穿越、保留名、重复/大小写冲突、目录文件冲突、链接、缺包和哈希错误均阻断。
- 发布/回退：备份与恢复均以无覆盖方式发布；恢复在独占新staging完成校验，目标空目录被竞争者抢建也不覆盖。取消和失败清理只处理自有staging。
- 还原语义：只在新恢复库结束running并清未发布stage；已发布事实、项目、报销、占用和原材料不改；restore-info旁车要求重新确认本机来源。
- 离线CLI：显式备份/还原调用核心，不初始化源Store，不启动HTTP/托盘/同步；互斥参数和无效恢复参数在写目标前拒绝。

## 本次实际验证

Windows原生CPython3.12.16 x64 / SQLite3.53.1，父任务qa312隔离环境，通过默认隔离profile的`research/run-native.py`执行。

- 原始19项备份/CLI回归：全部通过（8.551秒）。
- 修复后`python -m unittest discover -s tests -p 'test_backup*.py' -v`：**20项全部通过**（9.500秒，无跳过）。
- Ruff，`backup.py`、`__main__.py`、`storage.py`及两份备份测试：通过。
- strict mypy，`src/aha`24个源文件：通过。首轮使用UNC相对cache触发mypy2.4.0内部错误；改为任务Windows绝对独立cache并`--no-incremental`后通过，修复后再次通过，未修改产品迁就工具问题。
- compileall上述三个源文件：通过。
- `git diff --check`：通过。

## 未修复项与交接

本检查范围无未解决产品缺陷。父任务仍需对最终整合代码执行HTTP/真实浏览器、原资料副本及Directory/OneFile/桌面成品验收；本回执不能代替这些验证。

格式v1当前严格要求生产schema3结构（包括索引）。不兼容的旧schema3会明确拒绝，不自动修库；这项兼容边界已由主会话确认，并应写入对应规范/用户恢复说明。最后源码变化后须重新构建最终成品。
