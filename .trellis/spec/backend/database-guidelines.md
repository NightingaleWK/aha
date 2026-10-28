# SQLite 与持久化

## 所有权与连接

本项目直接使用标准库 `sqlite3`。CCS 来源 schema 为 23，应用 `aha.sqlite3` schema 为 2；[sources.py](../../../src/aha/sources.py)、[storage.py](../../../src/aha/storage.py) 与 [migrations.py](../../../src/aha/migrations.py) 各有明确职责。

来源读取复用 `load_sqlite`：`mode=ro`、`query_only`、`trusted_schema=OFF`，通过 SQLite backup 创建内存一致快照，包含已提交 WAL。不要使用 live 来源的 `immutable=1`，也不要仅复制主数据库文件。SQL 备份由 [sql_dump.py](../../../src/aha/sql_dump.py) 解析允许子集，不执行其中 SQL。

Store 使用 `isolation_level=None`、`check_same_thread=False`、`sqlite3.Row` 和外键约束；连接与 RLock 由 Store 管理。应用操作经门面进入，领域模块不自行创建第二份长期连接。

## 查询与写事务

数据值用 `?` 参数绑定；动态表名/字段仅来自代码内允许集合，例如 sources 的 `TABLE_FIELDS` 和 batches 的占用表选择。不要将请求中的名称拼入 SQL。

所有占用、换版、释放、消解和迁移在 `Store._transaction()` 内执行。其实现片段为：

```python
self._db.execute("BEGIN IMMEDIATE")
yield
self._db.execute("COMMIT")
```

完整实现还包含 RLock、关闭状态检查、`BaseException` 回滚和 SQLite 错误转换；扩展时复用该上下文，不复制上面三行代替完整事务。RLock 只管同进程线程，跨进程竞争依赖 SQLite 写锁与约束。

保存进入事务后重检 generation、有效版本、claim revision、成员和幂等。不能把 HTTP 预检结果当作写入授权；失败换版必须保留原有效版与原占用。各表与业务关系见 [主契约](./usage-evidence-contract.md)。

## 迁移、文件和备份

- `migrations.initialize` 在写事务内重读 `PRAGMA user_version`；新库显式创建，未知版本拒绝。
- v1 升级前 `Store._backup_v1` 使用另一条只读连接执行 SQLite backup，在 `backups/` 校验版本和 `quick_check`，之后才迁移。
- 逐条 `execute` 执行 DDL；不要在现有事务中用会隐式提交的 `executescript`。备份、回填、DDL 或提交失败不得留下半升级库。
- `legacy_review` 保留所有不安全候选，不取 `MAX(version)` 猜有效版。旧 writer 的持久触发器不能绕过。
- `objects/` 和 `packages/` 由 `_write_immutable` 写临时文件、flush/fsync、校验后替换；库只登记成功材料。已有文件不一致时报告损坏，历史 ZIP 不重新生成。
- 使用显式关闭/`contextlib.closing` 管理 SQLite 连接，特别是 Windows 测试夹具，避免临时目录无法删除。

## 实例与检查

[tests/test_claim_concurrency.py](../../../tests/test_claim_concurrency.py) 用两个连接/两个进程竞争，并在提交失败时断言旧版、原占用和原包仍在；[tests/test_migrations.py](../../../tests/test_migrations.py) 覆盖 WAL 备份、旧连接写入拒绝和迁移回滚；[tests/test_storage_helpers.py](../../../tests/test_storage_helpers.py) 覆盖文件/连接辅助路径。

本页规定保存方法，成员规则与生命周期详见 [主契约](./usage-evidence-contract.md)。不要为通过校验而清空占用、覆盖原包或自动降级资料。
