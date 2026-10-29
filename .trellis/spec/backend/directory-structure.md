# 目录与模块职责

## 范围

项目为 src 布局，包入口 aha。新增模块前按真实职责复用，业务不变量见 [主契约](./usage-evidence-contract.md)。

| 路径（Python文件均在 src/aha） | 职责 |
| --- | --- |
| __init__.py / __main__.py | 版本、CLI、资料目录、实例复用分流、浏览器和安全启动错误 |
| instance.py / runtime.py / tray_windows.py | 资料运行锁、私有描述符/身份核验、统一退出和 Windows 托盘；Store 不负责生产启动互斥 |
| domain.py / decimal_sql.py | 允许字段、身份、归一、AppError、精确十进制/大整数聚合 |
| sources.py / sql_dump.py | 同一只读源事务的分块投影、SQL字面量流式解析 |
| session_meta.py | 普通/zstd会话头目录线索，不读取正文 |
| storage.py / migrations.py | Store门面、全部连接/事务/文件、干净schema3初始化与运行时门禁 |
| sync.py | run/staging、来源/修订核对、差异写与成功进度 |
| ledger.py / projects.py | 当前事实、覆盖/核对、派生可用性/日统计、目录规则与人工归属 |
| queries.py / analysis.py | SQL筛选、摘要、游标、冻结迭代；analysis仅再导出新查询入口 |
| claims.py / batches.py | 索引冲突、行式冻结、单有效版/占用/状态/幂等/事件 |
| evidence.py | 流式CSV/HTML/manifest3/ZIP，精确金额与分享投影 |
| server.py / web/ | 本机HTTP边界、有限同步worker、原生HTML/JS/CSS |
| tests/ | 合成来源、隔离存储/请求/进程与重建安全回归 |
| scripts/ | 构建/许可证/启动，受控试用重建与独立规模基准 |

旧 archive.py 和旧业务迁移夹具已退役；查询不再解压单份 capture。历史对象的一次性提取放在重建工具，不为此保留旧报销协议或第二套运行期账本。

## 扩展纪律

外部调用经 Store，领域函数接受 Store 或既有连接；不在 HTTP/evidence 自建另一份金额核算或长期 writer。源只读连接不能用于应用写入。queries 的完整选择迭代与日统计是报销入口，不以页面可见行生成材料。

业务数据、输入、截图和包位于指定 data-dir/任务证据目录，不进入源码或 Trellis 管理目录。修改职责后检查所有生产者/消费者、导入依赖与 [质量要求](./quality-guidelines.md)。
