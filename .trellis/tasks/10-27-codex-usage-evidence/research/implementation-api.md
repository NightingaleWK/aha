# 实施接口与并行所有权

用户已于 2026-10-27 明确回复“开始实现”。本文固定首轮模块边界；更改接口需先通知主会话和依赖协作者。数据结构可用有类型标注的字典，JSON 入站必须校验，金额始终为十进制字符串。

## 所有权

- data implementer：`domain.py`、`sources.py`、`sql_dump.py`、`session_meta.py`、`analysis.py`；对应 source/metadata/analysis 测试。
- persistence implementer：`storage.py`、`archive.py`、`projects.py`、`batches.py`、`evidence.py`；对应持久化/项目/批次/导出测试。
- app implementer：`__init__.py`、`__main__.py`、`server.py`、`web/`、项目配置、README、构建脚本；对应 HTTP 测试。
- 主会话：协调、隔离环境、真实输入核对、浏览器与 Windows 运行验收、规范和任务记录；集成修复先与所有者协调。

## domain 的共享出口

`AppError(code: str, message: str, status: int = 400)`；`canonical_bytes(value)`、`content_hash(value)`；`record_key(row, grain='detail')`、`row_fingerprint(row, grain='detail')`；`fresh_input(row)`、`decimal_text(value)`。

`record_key` 对明细使用 app_type/data_source/request_id；对汇总使用原复合键。`row_fingerprint` 仅包含来源原始字段，不包含项目名、归属结果等派生字段。禁止以同一秒/相同 Token 自动删行。

## 来源和元数据

- `sources.load_sqlite(path: Path) -> dict`
- `sql_dump.load_sql_dump(data: bytes, name: str) -> dict`
- `session_meta.scan_metadata(session_ids: set[str], roots: list[Path]) -> dict`

来源结果：`schema_version`、`details`、`rollups`、`pricing`、`source`；source 含 kind/name/fingerprint_kind/fingerprint/observed_at（ISO）。明细/汇总使用 CCS 原列名，只留允许字段。

元数据结果：`sessions` 映射会话 ID 到 `{cwd: str | None, status: matched|missing|conflict, parent_id: str | None}`，另有 matched_sessions/total_sessions/errors。支持普通和压缩头，不能输出正文。

## 项目配置与归属

`Store.config() -> {revision, projects, overrides}`；projects 每项 `{id,name,description,directories: list[str]}`；overrides 为记录 key 到 `{project_id,content_hash}`。

`projects.canonical_path(path: str) -> str`；`projects.classify(row, metadata, config, grain='detail') -> dict`，返回 project_id（可空）、project_name、assignment_origin、cwd（可空）。人工有效覆盖优先，其次最长目录规则，其次未归属。

## 核算

`analysis.analyze(data, metadata, config, start_date: str, end_date: str, project_id: str = 'all') -> dict`

结果包含 start_date/end_date/project_id/project_name/classification_revision、details/rollups/daily/models/members/warnings，及 summary：record_count/detail_count/rollup_record_count/fresh_input_tokens/output_tokens/cache_read_tokens/cache_creation_tokens/total_tokens/total_cost_usd/detail_cost_usd/rollup_cost_usd/unpriced_count。

project_id 支持 `all`、`unassigned`、真实项目 UUID。rows 保留来源字段并增加项目/归属信息、date、fresh_input_tokens、total_tokens、record_key、content_fingerprint。members 含 kind/key/content_hash/date/model/来源维度及用于可能重叠的语义特征。金额保持字符串。服务层补 capture_id 与 analysis_id。

## 本地 Store（persistence implementer 提供稳定门面）

- `Store(data_dir: Path)`，可 close；SQLite 并发访问需锁/事务。
- `retain(data, metadata) -> dict`：返回 capture 描述符，至少 id/source/created_at/counts；相同内容不重复计数。
- `list_captures() -> list[dict]`、`get_capture(id) -> {id,data,metadata,source,...}`。
- `config()`、`save_project(project_id: str | None, name, description, directories: list[str]) -> dict`。
- `assign(rows: list[dict], project_id: str | None, grain: str = 'detail') -> dict`；使用 record_key 和原始内容指纹。
- `overlaps(analysis, exclude_batch_id: str | None = None) -> list[dict]`。
- `create_batch(analysis, claim, idempotency_key: str, batch_id: str | None = None) -> dict`；新版本均为草稿，结果有 id/batch_id/version/status。
- `list_batches()`、`batch_detail(id)`、`set_status(id, version: int, status: str)`。
- `download(id, version: int) -> tuple[bytes,str]`，返回原 ZIP 与安全文件名；损坏不能重算冒充。

claim 包含 purpose/amount（可空字符串）/currency/amount_note；项目来自冻结分析，不能任意替换为其他名称。建包由 persistence implementer 内部 evidence 模块完成。

## HTTP 与前端

app implementer 按 design.md 路由实现。后端缓存分析并校验 capture、配置版本与身份；来源/元数据/归属修改使当前分析失效。可选批次新版本 body 为 batch_id + 新分析/说明，需兼容从旧冻结分析仅修改说明。

CLI 支持 `--data-dir`、`--port`（默认 0）、`--no-browser`；启动输出 `AHA_URL=<本机地址>`，测试可定位。Windows 默认 LOCALAPPDATA/aha，WSL 默认用户本地数据目录；测试始终指定隔离位置。入口关闭端口不删持久数据。

输入 JSON 限流/大小/类型校验；SQL 上传可采用 JSON 内 base64，界面 FileReader 本机读取。仅 loopback，启动令牌换取 HttpOnly/SameSite cookie，校验 Origin/Host；不写凭据或源绝对路径到日志。界面全部中文、真实状态，不使用在线资源或示例数据冒充来源。
