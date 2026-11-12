# HTTP 与页面实施结果

## 文件与行为

- `src/aha/server.py`：完整备份/独立目录还原有限任务、4MiB原始二进制分块上传、受限上传会话、取消与遗留上传清理、流式下载、一键打开恢复台账及可复制再次打开命令；全部沿用Cookie/Host/Origin/CSRF边界。任务临时目录在系统Temp中独占创建，退出清理仅自身文件，不放在被备份资料内。
- 新接口：POST `/api/backups`；GET `/api/backups/{id}`；GET/HEAD `/api/backups/{id}/download`；POST `/api/backups/{id}/cancel`、`/open`；POST `/api/restore-uploads` `{size}`；POST `/api/restore-uploads/{id}/chunks`（octet-stream、X-AHA-Upload-Offset）；POST `/restore` `{destination?}`、`/cancel`。GET/POST `/api/source/binding` 通过Store门面读/确认本机来源。
- status新增 `data_directory`、`default_source.binding`、`backup_limits`、当前 `backup` 和安全的 `restore_uploads`摘要。损坏绑定不会阻断历史查询。恢复始终新目录，原台账不替换；默认双击仍打开原目录，结果明确展示这一点及再次打开命令。
- `web/app.js/index.html/style.css`：区分CCS用量导入和完整备份；来源确认；资料目录；空筛选的历史保留提示/全部历史入口；核对提交立即清旧保存身份，刷新后按原筛选重查，迟到刷新不覆盖新筛选。directory、rollup_origin有专用依据/选择文案。
- `tests/test_http_backup.py`：原生HTTP验证完整备份/上传/恢复/原包哈希、当前台账不变、鉴权/类型/长度/偏移、损坏/不完整/已有目标/嵌套目标、取消及丢响应后取消、来源绑定与历史可查、刷新遗留上传可清理。
- `tests/web_state.test.cjs`：新增空范围、来源确认、核对刷新成功/失败/迟到、备份完成/迟到创建取消、原始分块上传取消后迟到成功、目录与汇总来源专用选择回归。

## 实际验证

Windows QA：Python3.12.16 / SQLite3.53.1，任务qa312环境及隔离profile；没有访问真实用户数据。

- 新增 `test_http_backup.py`：9项通过。
- 原有 `test_http.py`：16项通过。
- `node --test tests/web_state.test.cjs`：34项通过。
- `node --check src/aha/web/app.js`：通过。
- Ruff（server.py与新增HTTP测试）：通过。
- strict mypy（server.py）：通过。初次把SQLite型mypy缓存放UNC工作目录遇database is locked；改为任务Windows Temp/mypy-http-ui后通过，未改产品规避测试环境。
- `git diff --check`：通过。

真实浏览器、Directory/OneFile、托盘/Office、原用户台账接续与桌面交付由父任务验证；本报告不声称这些已通过。

## 浏览器入口

`backup-options`“备份与还原”；`create-full-backup`“生成完整备份”；`restore-file`、`restore-destination`、`restore-backup`“校验并还原到新目录”；`cancel-backup`；`view-all-history`；`bind-default-source`“确认来源，保留历史”；`source-binding-form`/`source-binding-reason`，提交“保留历史并接续”。恢复结果提供“打开还原台账”“复制打开命令”；下载结果为“下载完整备份”。`unfinished-uploads`/`clear-unfinished-uploads`仅在实际存在遗留上传时出现。

## 边界与临时文件

未更改backup/source/sync领域核心、真实数据库、CCS、Git提交或发布版本。此代理失败的UNC mypy缓存已核实并删除；原生mypy缓存位于父任务自有Windows Temp，由父任务统一清理。
