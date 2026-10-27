# aha · 用量与费用证据

aha 是 Windows 本机小工具：只读打开 CC Switch 的 Codex 用量，关联会话工作目录，按项目与北京时间期间保存费用证据和报销批次。成品双击 `aha.exe` 后在本机浏览器打开；不要求另装 Python、Node 或数据库。

## 使用

1. 打开程序后，默认只读加载当前 Windows 用户的 `%USERPROFILE%\.cc-switch\cc-switch.db`。也可点击“导入 SQL”，或在“管理数据来源”中填写其他数据库文件。首版支持 CCS 结构版本 `23`。
2. 在“项目管理”中新建项目，从实际发现的会话目录勾选目录，或手填 Windows / Linux 路径。一个项目可绑定多个目录；更具体的目录规则优先。缺失或冲突会话保持未归属。
3. 在“用量导出”选择一份当前读取或历史留存、项目、起止日期，然后更新预览。日期按北京时间整日计算，包含两端；每次只使用一份留存。
4. 需要修正时，在“明细”或“历史日汇总”表中勾选记录并指定项目。明细可连同所选会话在该份留存中的全部记录一起修正；完整旧日汇总不按比例拆分。
5. 填写用途，可另填申请金额、CNY / USD 及依据。申请金额为空和零分别保存，程序不分摊订阅、不计算汇率。
6. 点击“创建批次并下载”。ZIP 包含 `使用明细.csv`、`每日汇总.csv`、`费用说明.html`、`导出信息.json`。CSV 使用 UTF-8 BOM；HTML 可用浏览器打印或手动保存 PDF。下载不受预览分页限制。
7. 在“报销记录”中下载原版本、手动更新状态，或创建新草稿版本。重下载同版本复用原 ZIP；原包损坏时明确报错。重叠提示区分草稿和已提交 / 已报销，可核对已有批次后继续。
8. 点击侧栏“退出程序”释放端口。关闭浏览器标签不会自动结束程序；已保存资料在退出后保留。

CCS 保存金额是期间参考成本，不能单独证明订阅逐次扣款或实际报销金额。旧日期只有日汇总时，不补造逐次明细；未定价的零金额不解释为免费。没有记录的日期不据此认定为零消耗。官方账单或支付凭证仍由用户另外归档。

## 本机资料与隐私

Windows 默认资料目录为 `%LOCALAPPDATA%\aha`，Linux 为 `${XDG_DATA_HOME:-~/.local/share}/aha`。其中保存应用自己的 `aha.sqlite3`、必要用量与目录依据留存、原始证据 ZIP。程序不修改 CCS / Codex 数据或设置，不读取聊天正文，不上传用量，也不自动写入 OneDrive 费用目录。

分享包不附全库 SQL、账号配置、API Key、IP、完整对话、原来源的绝对路径或完整目录规则。项目名称、用途及用户填写的说明会进入材料，分享前按实际用途核对。

每次启动仅监听 `127.0.0.1` 的本机端口，随机启动凭证换取本次会话 Cookie；接口校验 Host、Origin 与操作凭证，资源全部内置。资料目录中的 `runtime.json` 是本次启动的临时凭证文件，含本机启动地址与 PID，供无控制台启动和本机验收使用；正常退出删除。不要分享该文件或把它放进证据包。首版不自动清理历史资料。

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
