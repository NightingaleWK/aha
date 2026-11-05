# 诊断与规划依据

## 2026-11-05 本机会话证据

- 用户截图：aha 0.4.0 来源卡同时显示“已同步”和“来源读取超过时限”，上次成功北京时间11月3日10:47；当天视图统计为0。CC Switch 关于页显示v4.0.25。
- 源只读查询：SQLite user_version=24、journal_mode=DELETE，必要允许用量字段通过；真实用量读取得到约2.9万条明细。
- 真实 aha sync_runs：11月5日一次 startup、三次 manual 均约5.5秒失败，error_code=source_busy；11月3日成功读取/暂存约4.15秒。
- 原生 Windows Python3.15、SQLite3.53.4 源码隔离诊断，白名单投影：29,106 detail / 117 rollup / 9 pricing；纯源扫描911.18ms；本地生产暂存路径5秒预算在28,160条明细处失败（5,070.43ms）；实验20秒预算5,377.39ms成功，其中flush约1,788.50ms，其余读/处理约3,588.89ms。
- 这只是源码隔离实验，不是桌面 EXE 验收。实验约60.8MB临时投影和暂存库已清理。未改真实来源/台账和产品代码。

## 代码边界

- `sources.scan_sqlite`：三表同一只读事务，256行读取块，逐行序列化/摘要后立即调用 sink。sink 目前直接为 `_Stager.add`，导致本地CPU与FULL同步提交都占用源读事务及5秒墙钟。
- `_Stager.add/flush`：规范化、身份、内容hash、JSON、512行批暂存；writer争用已有250ms上限，不能退化。
- `sync._execute`：在read完成后flush、补元数据、原子publish；异常清理本轮暂存，成功时间只有completed推进。新两阶段需在本地预算内包含最终flush，避免漏掉尾批。
- `queries.ledger_status`：last_sync是最近成功，last_attempt是最近尝试；持久描述用state。HTTP job用status。UI需要识别两种形状。
- `web/app.js.renderSource`：当前优先syncBusy/needsReview/last_successful，失败只影响红色文本；initialize在安装currentSync前先render，可能短暂显示旧成功。
- `tests/test_storage.py` 已有真实独立源writer和应用writer争用测试；修复后应保留这些保护并增加“源锁在慢本地工作开始前释放”的更强断言。
- 构建与原生验收继续复用scripts/build_windows.py、scripts/verify_windows_artifact.py；发布合同规定运行时变化需重做对应全面专项。

## 方案取舍

采用有限只读快照→临时白名单投影→释放源→本地流式处理。单纯将SNAPSHOT_TIMEOUT提高会让源DELETE写事务被阻塞更久，且仍混淆两类错误；完整备份可能带入无关配置；全量列表会放大内存，均不作为本次方案。

无待用户决定的产品分叉；最终方案门禁仍须在用户看到摘要后获得明确实施批准。实现细节允许在上述合同内优化，涉及scope/schema/锁保护/真实资料写入的变化须重新审阅。
