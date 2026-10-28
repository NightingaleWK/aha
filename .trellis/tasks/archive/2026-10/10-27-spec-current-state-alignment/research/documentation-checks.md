# 文档验收与检查依据

本文件固定文档交付检查口径，不将检查通过解释为产品发布或正式报销验收。

## 规范检查

1. 扫描 `.trellis/spec/`，不保留 `To be filled`、`To fill`、`TODO: fill`、`TBD`、示例路径占位或空章节。
2. 三个索引与 `research/spec-file-map.md` 中 17 份目标 spec 一致。
3. 逐一解析现行 spec、README、未归档工作和本任务的 Markdown 本地链接，文件必须存在；跳过网络地址和纯页内锚点，历史归档不改写。
4. 核对分题源码/测试路径及命名符号真实存在，代码例子来自实际实现；禁止把 ORM、React、TypeScript、日志框架或 Trellis 引擎模块当作 aha 现状。
5. 对两份主要契约逐项核对 schema23/schema2、Decimal/北京时间、单 capture、独占/原子换版、作废/撤回、迁移/旧 writer、幂等/重放、原 ZIP、隐私、HTTP 与页面失效；中文整理不能改变签名、字段、错误码或义务。
6. 明确输入格式由边界解析，当前占用/代次/有效版本在写事务内重检，不能统一写成只校验一次。
7. 日志说明保留私有 AHA_URL 的真实例外；操作事件来自 SQLite，不虚构日志文件、logger 或日志等级实践。

## 工作记录检查

- 初始化 backend/frontend/例子三项关联实际文件与检查，计划项和完成项分开。
- 保留 `00-bootstrap-guidelines` 的 id/name、目录、创建信息及 `in_progress` 状态，记录初始化来源。
- 标题/说明可改中文；未获授权不归档，不将规范齐备扩写为产品正式验收。
- 已归档产品任务与历史 journal 不改，本轮仅引用历史记录。
- 当前任务保持规划直到批准最新摘要；实施结束也不自行提交、合并或推送。

## 检查命令与执行条件

```bash
python3 .trellis/scripts/task.py validate .trellis/tasks/10-27-spec-current-state-alignment
git diff --check
git diff --name-status 434c785
git status --short
```

本地链接、源码符号、占位和范围校验可用一次性只读 Python/rg，不添加产品测试或长期脚本。范围检查包括未跟踪文件，不能仅看 git diff。

规划时已执行源码基线，见 `research/current-state.md`。后续仅改文档且源码未变化时，不重复整套产品测试；若有新失败、源码变化或未解决技术问题，再评估相应检查和范围，不顺手修改产品。

本轮没有发布，Windows EXE/浏览器/Excel/PDF 既有结果只能标为历史验收；新文档规则不能凭历史记录获得新的产品验收。
