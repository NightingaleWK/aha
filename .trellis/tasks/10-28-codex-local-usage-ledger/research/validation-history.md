# v0.3.0 实施与验证记录

状态：实施中。以下只记录已执行证据；未标通过的代码、性能、原生交付和试用重建均未完成，不能用环境就绪替代业务验收。

## 授权与工作边界

- 2026-10-28 用户在最终规划后明确“实施”；任务已由 planning 转为 in_progress。
- 分支 `codex/local-usage-ledger`，基线 `01b2c1e`。规划上下文 implement/check 各 12 条，task.py validate 通过。
- 当前产品由核心、billing、HTTP/页面三个 trellis-implement 代理按文件所有权并行；主会话协调与准备隔离运行时、资料保全、整合验收。
- 用户确认尚未正式使用：新库重建，不迁移试用规则、报销、占用或旧材料；CCS 原件与可恢复历史用量受保护。

## 已完成：隔离运行时

| 环境 | 实测版本与位置 |
| --- | --- |
| Linux | Python3.14.4；任务 `.venv-ledger`，用任务目录动态库加载 SQLite3.53.4；Ruff0.17.3、mypy2.4.0、zstandard0.25.0 |
| Windows | Python3.12.14 / SQLite3.53.1；任务 venv 位于 `%LOCALAPPDATA%\\Temp\\aha-build\\20261028-local-ledger-01a18012\\venv`，同样已安装固定开发依赖 |

Linux 系统 SQLite 仍为3.46.1；没有改系统库或全局 Python。所用 libsqlite3 只从 [Debian 官方包](https://deb.debian.org/debian/pool/main/s/sqlite3/libsqlite3-0_3.53.4-2_amd64.deb) 解包到 `/tmp/aha-ledger-runtime-01a18012/sysroot`，包 SHA-256 为 `bbf13c9326764d05e37e6590debdaa6f33af6bd822e3ca1204789d9d1dc23b11`。

Linux 检查命令前缀：

```bash
env LD_LIBRARY_PATH=/tmp/aha-ledger-runtime-01a18012/sysroot/usr/lib/x86_64-linux-gnu PYTHONPATH=src .venv-ledger/bin/python
```

Windows venv 使用应用提供的已修复运行时创建，只写任务 venv，不修改 bundled/global 依赖。实际打包仍须验证运行时、许可证、程序行为和成品 SHA。

## 已完成：可逆保全与历史输入校验

- 原 aha 试用目录仅作只读访问；使用 Windows SQLite `mode=ro/query_only + backup` 生成一致副本，`quick_check=ok`，原应用 schema2。
- 一次性副本位于 `%LOCALAPPDATA%\\aha-rebuild-20261028-01a18012\\source-preservation\\trial-copy`。保全 12 个文件、56,261,345 字节，逐文件 SHA 校验；没有复制 runtime 凭证。
- `preservation-manifest.json`、`history-index.json` 留在该私有保全目录，不进入 Git。
- 6 份 usage 压缩对象的内容 SHA、format_version1/adapter_version1/schema23 均校验通过。按原始 key 去重有14,036条明细、112条来源日汇总，未发现同键不同内容；费用按两种粒度分别核对，没有将两类合计相加。
- 这些是已保存输入的校验，不证明所有历史来源成员完整；新台账仍需来源/覆盖核对。
- **尚未清理原试用目录、尚未向原 CCS/Codex 写入、尚未将旧业务数据导入新库。**

## 已完成：实现与初步回归

- 核心：schema3、不可变版本、完整来源投影比较、覆盖/候选核对、源缩水needs_review、身份别名及后续金额修订；Linux/原生Windows核心及报销联动103项通过。旧archive/业务迁移夹具已删除。
- 报销：32项Linux/Windows通过，覆盖当前/冻结主体、事务占用、重放、原ZIP字节、差异和作废后按最新值重用。170字符data-dir的Windows路径回归通过；物理ZIP名改为固定32位UUID。
- 根整合全套初步114项Linux和Windows通过（Windows跳过1个权限所限的symlink fixture），随后新增核对/别名回归，正式检查代理将跑最终全量；早期发现的SQL字符串误调用已修复，旧失败日志保留不当通过记录。
- 全源码18模块mypy、compileall与各所有权Ruff已通过；最终全量检查仍待正式check收口。

## 已完成：原生浏览器与隔离重建演练

- 源码模式：原生Chrome156，13/13阶段通过，证据 `%LOCALAPPDATA%\Temp\aha-build\20261028-local-ledger-01a18012\qa-ui\run-2026-10-28T03-11-42-631Z\result.json`。
- 真实启动120条同步与刷新去重；四标签/50条游标；失败后本地查询；目录/人工归属；保存和原包重下；打开current修订时占用变化409禁保存；frozen改用途保持原11.59USD与旧SHA；提交/撤回/报销/作废重用；0.99备份与0.25当前候选明确核对；源120→1的needs_review终态/旧成功时间/120留存/刷新恢复；界面退出、进程0与私有描述删除均通过。
- 同轮原生HTTP/CLI12项通过，记录 `qa-ui/checks-2026-10-28T03-12-54-648Z/result.json`。源码模式不是最终EXE验收。
- 1440/1366/1280/430/375无body横向溢出；正文/输入16px、表格/按钮15px、币种112px。0pageerror，只有刻意触发的availability_changed409。
- Chrome A4 PDF一页594.96×841.92pt，Poppler渲染；主会话实际查看1440页截图及A4第一页，无裁切。CSV尚待原生Excel。
- 真实试用保全副本的隔离重建：`qa-rebuild/trial-data`从schema2变schema3，导入14,036detail+112rollup，项目/报销/占用均0；原12文件SHA未变，原目录尚未清理。15项工具测试双平台通过（Windows跳过1symlink）。

## 性能进展（尚未验收）

- 合成1万与物理ext4十万快播种、完整projection抽样和真实Store业务链路已通过；原生Windows1000条含查询/进程冷/不变同步/新增修订/导出通过。
- 首次1m预跑使用了 `/tmp` tmpfs，**不是物理盘最终结果**。其热态深页约175ms，全年统计P95约689ms，但五年全项目进程冷查询约2.97s超过1.5s目标。
- 已定位深页tuple条件没有收紧实际Seek起点、分析重复日聚合；正式检查代理负责修复与回归。不会把索引存在或小规模结果当作目标达成。
- 1m样本已准备迁入 `/home` 物理盘；10m在 `/home`独立目录用fast-seed生成，完成后恢复生产索引/参数，以新进程query-only测量。最终还须在Windows NTFS复制同样本独立实测。

## 验收映射与剩余工作

| 项目 | 当前证据/剩余 |
| --- | --- |
| AC1 来源/口径/只读 | 核心边界测试已过；待最终检查与真实源导入 |
| AC2 启动/手动/退出 | 源码HTTP及真实浏览器通过；待EXE |
| AC3 本地长期查询 | 核心移除来源/重启及UI失败留存通过；待EXE重启 |
| AC4 身份/修订/材料冻结 | 核心+报销alias回归、浏览器冻结/原SHA通过 |
| AC5 覆盖与重建防重 | 单元边界及浏览器核对通过；待最终审查 |
| AC6 本地查询/归属/报销 | 核心及UI贯通通过 |
| AC7 并发与失败恢复 | 双连接/进程及源双模式测试通过；待最终审查 |
| AC8 保全/重建/实际清理 | 保全与真实副本隔离演练通过；原试用尚未清理 |
| AC9 百万/千万性能 | 物理盘样本与优化进行中，未验收 |
| AC10 Windows/浏览器/Excel/打印 | 源码模式浏览器/打印通过；EXE、Excel、交付待完成 |

## 追加：真实来源与目录包预验收

- 原生Windows对当前CCS只读同步至独立qa-live/data：schema23、DELETE，14,806条detail、112条rollup、7条价格；全程26.65s，completed、data_revision1、pending0。本次没有单独记录源读锁时间，不将26.65s当源事务时长；源墙钟预算另有确定性测试。证据qa-live/result.json。
- 首个原生Directory构建成功，运行时Python3.12.14/SQLite3.53.1，实际EXE的浏览器13阶段通过，证据qa-ui/run-2026-10-28T03-23-59-092Z。后续核对/性能修正后还须重建最终Directory，不能将该预验收冒充最终成品。
- 上述目录包生成的alpha-v2 ZIP已用独立Excel16.0 COM实例以只读方式真实打开：明细61×23、每日1×17，BOM/中文/成本逐行一致，无公式，关闭未保存。包SHA256为26ffc62876bb0163f6c8585540cc50f54724285ed90e656d563cd6b79f121607；证据qa-excel/run-2026-10-28T03-23-59-092Z/result.json。
- 物理Linux1m第一次正式预热10/100采样：12种分页最慢P95 6.68ms，项目月4.56/年27.78、全项目月33.06/年431.99ms；进程冷1616.50ms仍未达标。100次固定10000条窗口同步无新增事实/版本，P50 1.926s/P95 5.235s；新增10000+修订10000时1882次前台查询P95 68.49ms、max233.33ms；导出1000000因仅710000可用而明确跳过，**没有百万导出通过结论**。
- 正式检查已修复真实keyset seek、同步范围更新和幂等竞态；另发现同源等量换key、日汇总代表量回退及source sink等待本地RLock的边界，根已授权按原PRD修复。为满足冷查询增加月派生统计，保留精确金额和事实版本；最终测量须用其完成后的代码。

## 最终普通查询与精确派生：百万级

- 1m纯基准先按当前DDL补建月统计/来源观察派生表，事实与原版本未改。固定seed、预热10/采样100，12种50行游标最慢P95 **4.365ms**；项目月3.51/年8.54、全项目月9.82/年69.59ms，五年首次分析+50行的进程冷 **383.65ms**。完整结果 `/tmp/aha-ledger-runtime-01a18012/benchmark-1m-final.json`。
- 100,156个冻结成员实际导出/下载/校验95.23s，ZIP13,618,327字节，额外峰值RSS17,039,360字节，≤128MiB。导出后带原因作废，只为恢复合成样例占用，不影响原材料证据。
- 大样本生成与测试并行；上述冷值为新进程，不清系统磁盘缓存。原生Windows与千万级最终结果仍待完成，不能仅凭Linux百万级宣布AC9全部通过。
- 当前最终产品src/aha22文件内容指纹 `e8f732d4346d288411ff6992b8bdf7a774c61f846ca807befac6e6b6e3f81e96`；按排序相对路径+NUL+文件原bytes拼接SHA256，排除pycache/egg-info。最终Directory构建前后该指纹相同，EXE SHA256 `3e756698667ab735276d0f7369067d8b7bf262228639ed14b262a15c01e0983b`。

## 最终检查与原生锁测量

正式trellis-check记录见research/final-check.md。146项r2全量Linux15.388s/Windows53.669s通过，Windows因权限跳过1symlink；最后仅把staging SQLite临时等待上限由250ms收紧为100ms，相关26项存储回归Linux1.199s/Windows8.216s及真实锁探针重新通过。全Ruff、mypy18src、compileall、Node、diff检查通过。

当前产品22文件最终指纹更新为9f295ab3ec334fe393021884809cf3345ec735feb1c10734c53fd387016bb9f0。原生测量Python锁0.244576s、取消0.031106s、SQLite busy分支0.166561s；源writer均在本机writer仍持有时提交，原busy_timeout恢复5000。保留旧Windows COMMIT墙钟断言失败日志和诊断，不把writer刷盘耗时冒充读锁等待，不承诺硬实时。

最终guard版Directory SHA256=5050d1141438cf945ca5ff91f43451bf113ac08fc268adc1a2c17a5bb3953be2，正在原生13阶段复验。此前e8版本Directory和OneFile都已13阶段通过，CSV Excel16.0及一页A4实际渲染/目视通过；最后安全参数变动后以新成品验收为准。

## 百万级Windows NTFS最终普通查询

同一原始1m样本在首次增量验证后有1,010,000事实/1,030,000版本，已显式记录marker；在此更大样例补建月派生后预热10/采样100：12种分页最慢P95 7.369ms；项目月4.43/年13.42、全项目月10.87/年109.61ms；五年进程冷659.98ms。100次固定20,000条窗口无新事实/版本，P50 5.787s/P95 10.241s；projection SHA b690e89c15ac59c8f73e423f306d087287524ae6707d5ff7a162254a23c7fc9f，这是额外20k压力结果；Windows原始1m的10k窗口100次结果也已保留，最终10m按原始10k同SHA作跨规模比较，不能混用20k。

## 最终HTTP入口复核

147项完整测试双平台通过，新增VM/独立参考证明状态页使用月投影、日期两次seek；排除前100组查询在全5年和首月工作量相同，随后续历史增长不多扫描。新索引stats_excluded_day_model_state、stats_excluded_project_day_model_state纳入fresh和夹具补建。最终产品22文件指纹ff3b003349e4d280ba1a22b912e70f281c07dbd841da8ed466a30ee2f1eb1aa1。

此后100次正式查询：Linux/WSL最慢页P95 6.241ms，全项目年14.72ms，数据层新进程首次查询116.47ms；Windows最慢页P95 9.726ms，全项目年22.68ms，数据层新进程首次查询142.41ms。完整原始结果已保存research/performance/。冷计时明确不含解释器导入和EXE解包，实际成品另测。

最终Directory c00b1956ccb19fb6d4abda6644b7762476231e91821378b39dfcd329db35c9bf在qa-ui/run-2026-10-28T04-19-25-789Z通过13阶段。实际该EXE接NTFS1.01m：首次全5年available分析117.96ms，四种HTTP分页最慢P95 36.79ms；含启动/认证/初始status的bootstrap1472.91ms，licenses内置与原生退出均通过。qa-mega/1m-directory-r3的早期脚本mode沿用了onefile标签，实际exe参数是Directory，以本条记录/命令和EXE哈希为准；未来脚本已修正packaging字段。

## 最终单文件与真实百万库

最终ff源码对应OneFile SHA256=c8c5774f843d9766458602a02f1d7a8bd7922328bc09f65b197f8f36cf365c73。qa-ui/run-2026-10-28T04-26-05-567Z真实浏览器13阶段passed。实际OneFile接NTFS1,010,000事实：首个五年available分析137.34ms，全/单项目×全部/可用HTTP列表100次最慢P95 36.79ms；EXE启动、解包、认证及status共1584.15ms（独立于数据层冷查询142.41ms）。内置licenses、旧成功时间保留、退出0和runtime删除全部通过，结果qa-mega/1m-onefile-r3/result.json，已记录实际EXE哈希。

10m全部事实已播种完毕，正在恢复原生产索引/ANALYZE/抽样与真实Store对账；未完成前不测量缺索引库、不宣称千万级通过。复制Windows只做二进制文件传输，来源关闭/checkpoint后流式SHA256并校验目标，不让Windows SQLite直接打开WSL UNC活库。

## 千万样本校验及环境恢复

最初长时间播种进程完成10,000,000事实、19个生产二级索引、ANALYZE/外键检查后，在最后参考Store验证时混用了已更新的sync模块与旧Store类，抛`AttributeError: _staging_transaction`。失败日志/JSON保留，没有把该失败作为通过。其marker已明确完成事实播种；最终ff代码的新进程执行`--query-only --refresh-derived --skip-queries`，补建月/观察表和2个排除索引，3.59s完成派生补建；106行完整projection与实际Store同步/查询/保存/下载/作废对账全通过，fatal_error为空。证据benchmark-10m-refresh.json。

源库checkpoint/关闭后主文件36,449,095,680字节。Windows复制按流计算源SHA，完整重读本机目标校验；复制期间保持源主文件不变，不在Windows SQLite中打开UNC源。复制完成前不开始写入类性能测试。

完成的1m合成库已保留指标、schema及原包后清理，为10m复制/导出腾出空间；没有操作原aha试用目录或任何CCS原件。Windows1m物理分配：主文件4,258,193,408字节、索引1,562,800,128字节、版本/冻结成员/事件表合计1,667,440,640字节；事实1,010,000、版本1,030,000、占用300,000、日投影302,899、月投影13,365。100,156成员ZIP13,618,328字节已保留，dbstat原始数据见research/performance/windows-1m-footprint.json。
