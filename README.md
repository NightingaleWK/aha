# aha · 用量与费用 v0.2.0

aha 是 Windows 本机工具：读取 CC Switch 的 Codex 用量，按项目和北京时间期间保存报销材料。双击 `aha.exe` 后在浏览器使用，程序内置运行环境和 SQLite 数据库。

## 使用

1. 打开程序后，默认加载当前 Windows 用户的 `%USERPROFILE%\.cc-switch\cc-switch.db`。也可点击“导入备份”选择 SQL 文件，或在“数据来源”填写其他数据库路径。支持 CCS 结构版本 `23`。
2. 在“项目管理”新建项目，勾选发现的工作目录，也可手填 Windows / Linux 路径。一个项目可对应多个目录，更具体的目录优先；未匹配的用量保持“未归属”。
3. 在“用量与费用”选择数据快照、项目和日期，点击“更新预览”。日期按北京时间整日计算，包含起止两天；每次使用一份数据快照。
4. 默认显示“可用用量”，排除已被其他报销记录占用或待核对的部分，并显示原因和对应记录。“全部用量（查看）”用于核对总消耗，不能直接保存新报销。
5. 需要分配项目时，在“明细”或“历史日汇总”勾选记录，再点击“分配项目”。会话可整批分配；历史汇总按完整记录处理。
6. 填写用途和选填的申请报销金额、币种、金额依据，点击“保存并下载”。金额为空与零分别保留；填写金额须提供依据。
7. 下载包包含 `使用明细.csv`、`每日汇总.csv`、`费用说明.html`、`导出信息.json`。CSV 可用 Excel 打开，HTML 可打印或另存 PDF。导出包含本次预览的全部可用记录，不受分页限制。
8. 在“报销记录”查看状态、下载材料或修改当前草稿。退出时点击“退出程序”；仅关闭浏览器标签不会结束本机程序。

参考成本沿用 CC Switch 保存的模型用量估算，申请报销金额由你另填。工具不自动分摊订阅或换算汇率；旧日期只有汇总时按汇总保留。

## 一次使用与修改

保存草稿成功，用量立即由这条报销记录占用；下载失败也不会释放。其他记录只能使用剩余可用用量。两个窗口同时保存同一用量时，后保存的一方需要更新预览。

- **草稿**：可点击“修改报销记录”。保留当前用量，或在修改窗口重新选择数据快照、项目和日期。保存后新版本成为当前记录，旧版材料仍可下载。
- **已提交**：可标记已报销，或填写原因“撤回为草稿”再修改。撤回保持用量占用。
- **已报销**：可查询和下载；填错时通过“作废记录”纠正，再新建需要的记录。
- **作废记录**：原因必填。作废后释放用量，原金额、状态历史和材料保留；作废是终态。

每条报销记录只有一个当前有效版本。历史版本不能再次修改状态，但“下载材料”始终下载当时保存的原包。同版本重复下载的字节和校验和保持相同。

占用规则作用于同一份本地资料库。程序不能控制下载文件在外部被再次发送，也不协调两份独立复制的资料库。完整历史日汇总或疑似重建记录无法确认独立时会标为待核对，不按比例拆分。

## 从 v0.1.0 升级

先在旧程序里点击“退出程序”，再运行新版。保留旧成品即可；项目和记录使用原来的应用资料目录。

新版首次打开旧资料时，会先在资料目录的 `backups` 下保存升级前的完整数据库快照，再将应用数据库升级为结构版本 `2`。原数据留存对象和证据包保留，无冲突的草稿会接续占用。备份或校验失败会取消升级。

旧记录存在重复占用、多个候选版本或无法安全确定当前版本时，会显示“待核对”。先查看冲突，填写原因作废不保留的记录，再明确确认保留版本；未处理的候选用量暂不可被新申请使用。

已升级的数据库不能由旧版直接打开。需要回退时，先退出所有版本，保留当前整个资料目录，再将 `backups` 中升级前的数据库恢复为 `aha.sqlite3`，配套 `objects`、`packages` 一并保留；不要在程序运行时替换文件。

## 本机资料与隐私

Windows 默认资料目录为 `%LOCALAPPDATA%\aha`，Linux 为 `${XDG_DATA_HOME:-~/.local/share}/aha`。其中 `aha.sqlite3` 保存项目、占用、报销记录及操作历史，`objects` 保存必要用量与目录依据，`packages` 保存原始证据 ZIP，`backups` 保存升级前数据库备份。程序不修改 CCS / Codex 数据或设置，不读取聊天正文，不上传用量，也不自动写入 OneDrive 费用目录。

分享包不附全库 SQL、账号配置、API Key、IP、完整对话、原来源的绝对路径或完整目录规则。项目名称、用途及用户填写的说明会进入材料，分享前按实际用途核对。

每次启动仅监听 `127.0.0.1` 的本机端口，随机启动凭证换取本次会话 Cookie；接口校验 Host、Origin 与操作凭证，资源全部内置。资料目录中的 `runtime.json` 是本次启动的临时凭证文件，含本机启动地址与 PID，供无控制台启动和本机验收使用；正常退出删除。不要分享该文件或把它放进证据包。程序不自动清理历史资料。

## 开发规范

修改前按范围阅读当前实现的规范：

- [后端规范](.trellis/spec/backend/index.md)：来源、核算、SQLite、用量独占、版本、错误和运行输出。
- [前端规范](.trellis/spec/frontend/index.md)：HTTP、DOM、页面状态、数据边界和浏览器检查。
- [思考指南](.trellis/spec/guides/index.md)：复用入口、跨层影响和证据核对。

规范以当前源码与测试为依据；任务中的检查结果和历史原生成品验收分别记录。

## 源码运行与检查

开发需要 Python 3.12+。使用任务自有隔离环境，不修改系统或 Codex bundled Python 的依赖：

```bash
python -m venv .venv
.venv/bin/python -m pip install -e . -r requirements-dev.txt
.venv/bin/python -m aha --data-dir .aha-data --port 0 --no-browser
```

Windows 的解释器入口改为 `.venv\Scripts\python.exe`。`--port 0` 自动选择端口；省略 `--no-browser` 会自动打开浏览器。有控制台时启动输出 `AHA_URL=...`，无控制台时可在指定资料目录的 `runtime.json` 找到本次地址。该地址仅本次进程有效。开发和测试必须指定隔离的 `--data-dir`，以免混入实际项目规则或批次。

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m ruff check src tests scripts
.venv/bin/python -m mypy src/aha
.venv/bin/python -m compileall -q src/aha
node --check src/aha/web/app.js
```

## Windows 原生构建

在 Windows x64 的任务自有目录创建隔离环境；使用实际 Windows Python 3.12+，不能把 Linux 产物改名为 EXE。推荐直接运行纯 Python 构建入口，无需执行 PowerShell 脚本或调整本机执行策略。打包依赖固定在 `scripts/requirements-build.txt`，开发检查依赖固定在 `requirements-dev.txt`。以下路径是构建示例，应换成实际隔离目录：

```powershell
$BuildRoot = Join-Path $env:LOCALAPPDATA 'aha-build\my-build'
python -m venv (Join-Path $BuildRoot 'venv')
$BuildPython = Join-Path $BuildRoot 'venv\Scripts\python.exe'
& $BuildPython .\scripts\build_windows.py --build-root $BuildRoot --stage Directory
```

先原生运行 `release\directory\aha\aha.exe`，使用隔离资料目录核对数据库 / SQL、压缩会话头、项目归属、留存重开、批次重下载和退出；验证后再构建单文件：

```powershell
& $BuildPython .\scripts\build_windows.py --build-root $BuildRoot --stage OneFile --directory-verified
```

`--python-exe` 可显式指定隔离环境解释器，缺省使用当前解释器；`--source-root` 可指定源码根目录，缺省为构建脚本所在项目。入口会检查所选解释器为 64 位 Windows 隔离环境，再安装固定构建依赖并采集许可证。已有的 `scripts/build_windows.ps1` 保留为兼容入口；无需为使用它改变执行策略。

便携成品在 `release\portable\aha.exe`。脚本输出 EXE 路径与 SHA-256；构建成功本身不代表通过业务验收。CSV 还需在目标 Windows 表格软件打开，HTML 在浏览器查看并打印预览。构建脚本采集实际 CPython、zstandard、zstd 和 PyInstaller 的许可证原文及指纹并内置在成品中，启动后通过页面底部“开源说明”查看。

## 数据解释依据

CCS 的 Token 语义、会话来源和历史日汇总行为参考 [farion1231/cc-switch 的固定提交 e55d8a21](https://github.com/farion1231/cc-switch/tree/e55d8a21b3897b595b746e9f2139716b2931641d)，上游采用 [MIT License](https://github.com/farion1231/cc-switch/blob/e55d8a21b3897b595b746e9f2139716b2931641d/LICENSE)。aha 为独立实现；没有复制上游配置、凭据或原始个人数据。金额沿用来源历史保存值，不按当前价格表重算。
