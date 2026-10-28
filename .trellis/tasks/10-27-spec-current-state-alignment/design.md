# 文档校准设计

## 交付边界

本任务对现有工具的规范与未归档工作做一次闭环校准，行为基线为当前 v0.2.0 源码。证据见 `research/current-state.md`，文件集合见 `research/spec-file-map.md`。spec、导航与初始化记录相互引用，由一个任务整合验证。

## 当前架构

```text
只读 CCS SQLite / SQL 备份
  → sources.py / sql_dump.py / domain.py
  → archive.py 留存允许投影 + storage.py Store
  → projects.py 归属 + analysis.py 核算 + claims.py 占用评估
  → batches.py 事务与版本 / migrations.py 兼容
  → evidence.py 冻结四文件 ZIP
  → server.py 本机 HTTP
  → web/index.html + app.js + style.css + mark.svg
```

`Application` 管临时状态，`Store` 管持久化与事务。外部库只读、应用资料独立、分享投影和运行凭证分离。规范讲解实际边界及验证方法，不另设计架构。

## 规范层次与兼容

两份主要契约继续承担业务和跨层约束入口，核对签名、输入输出、错误码和场景后中文整理，保留技术标识、默认值及业务义务。

backend 五份分题讲模块、SQLite、错误、输出/历史和质量；frontend 五份讲资源、DOM、状态、数据边界和质量。分题引用主要契约，不重抄全部状态机或 HTTP 表。

`type-safety.md` 保留路径，内容为实际 JavaScript 边界；删除 `hook-guidelines.md`，真实 api/run/事件内容并入状态和组件规范。实施前再次全仓检索引用，更新现行入口，历史任务只读保留。

三个 guides 改为 aha 实例，去除 Trellis 引擎模板同步、并不存在的 CLI 适配器及 TS/reducer 强制模式。跨层指南区分 HTTP 对格式/类型/长度的解析，与 Store 写事务内对 claim revision、generation、active version 和成员的重检；两者不能互相替代。复用指南以 domain/claims/analysis/Store/DOM 工厂为入口。

## 契约核对表

| 事项 | 保持的语义 | 核对入口 |
| --- | --- | --- |
| 来源与版本 | schema23/schema2 分开，只读 WAL 快照，SQL 不执行 | sources/domain/migrations 与测试 |
| 核算 | Decimal 字符串、原保存成本、三类 token 语义、北京时间、单 capture | domain/analysis 与测试 |
| 保存与版本 | 同库独占、唯一有效版、重检、原子换版、撤回保留、作废释放终态 | claims/batches/并发测试 |
| 兼容与重试 | 备份、legacy holds、旧 writer 拒绝、重放不复活旧占用 | migrations/storage/HTTP 与批次测试 |
| 原材料 | 四文件、原 ZIP 字节、校验和允许投影 | evidence/archive/download 与测试 |
| 服务与页面 | 本机认证、端口 Cookie、可选字段、过期弹窗、先保存后下载 | server/app.js/HTTP/CLI 测试 |
| 输出 | AHA_URL/runtime 为私有启动信息，默认访问日志关闭，事件在库内 | __main__/RequestHandler/schema/events |
| 开发发布 | 隔离 venv/data-dir、当前检查命令；原生成品门禁与本轮检查分开 | pyproject/README/build_windows/历史 verification |

如发现实现与契约有实质性分歧，记录证据和影响后说明，不能删掉业务约束来凑一致或在本任务改代码。只有源码、测试或项目记录支持的内容才写成当前契约。

## 未归档工作处理

保留 `00-bootstrap-guidelines` 的目录、id/name、创建信息、`in_progress` 状态和初始化来源，PRD 改为实际范围与验收清单，增加 `verification.md`。标题、说明、备注和 relatedFiles 可更新。

规范完成、索引和引用检查通过后才能勾选对应项；记录此前部分业务契约与本次补齐关系，链接本轮结果。归档待用户之后决定。本任务另写自己的验证记录，旧产品任务和历史日志保持原样。

## 可写范围与协作

| 范围 | 内容 |
| --- | --- |
| `.trellis/spec/backend/**`、`.trellis/spec/frontend/**`、`.trellis/spec/guides/**` | 规范与导航 |
| `.trellis/tasks/00-bootstrap-guidelines/{prd.md,task.json,verification.md}` | 初始化说明与验收 |
| `.trellis/tasks/10-27-spec-current-state-alignment/**` | 当前任务规划、上下文和验证 |
| `README.md` | 开发规范入口及必要事实校准 |

主会话负责证据、规划、规范整合、初始化记录和最终结论；按 spec-bootstrap 单一所有者方式补规范。需要项目检查代理时，只读复核批准的文档及源码依据。JSONL 仅登记稳定研究文档，源文件与待修改 spec 按需读取。其他会话的新改动保留并复核冲突，不覆盖他人工作。

产品、测试、依赖、构建脚本、Trellis 工作流/技能/hooks/配置和历史记录不在可写范围；不做个人资料迁移、发布、提交、推送或归档。

## 验证与回退

按 `research/documentation-checks.md` 检查占位、源码引用、本地链接、索引、业务不变量、任务状态和写入范围。源码不变时不重复已通过的全套基线。

回退只反向应用本任务文档差异，不 reset/clean 或丢弃其他会话更改。模板已有 Git 基线，历史与个人材料保留；产品和数据库回退不属于本轮。
