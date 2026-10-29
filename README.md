# aha · 用量与费用 v0.3.0

aha 是 Windows 本机 Codex 用量台账与报销材料工具。双击 `aha.exe` 后在浏览器使用，运行环境和 SQLite 均内置。CC Switch 的数据按记录长期保存在 aha 自己的数据库，查询和导出使用本地台账。

## 使用

1. 每次打开程序自动同步一次 `%USERPROFILE%\.cc-switch\cc-switch.db`；也可点“立即同步”、填写其他 SQLite 路径或导入 SQL 备份。支持 CCS schema23，仅统计 `codex_session`。同步不要求抢在 CCS 前启动。
2. 页面先显示已有本地资料。来源正忙、无法读取或同步失败时仍可查询旧资料，并显示上次成功时间；需要核对的来源变化单独提示。程序只在打开和手动操作时读取来源，没有周期采集、关闭后同步或开机自启。
3. 在“项目管理”新建项目，绑定发现的工作目录或手填 Windows/Linux 路径。一个项目可绑定多个目录，更具体的目录优先；未匹配保持“未归属”，也可人工分配。
4. 在“用量与费用”选择项目和北京时间日期范围，点击“更新预览”。明细、历史日汇总、每日和模型使用游标翻页，查询不依赖原 CCS 文件仍存在。
5. 默认“可用用量”排除已占用及待核对部分，显示原因。“全部用量（查看）”用于核对，不能直接保存新申请。明细与来源历史日汇总存在重叠时不相加，身份、版本或覆盖不清楚时先核对。
6. 填写用途、选填申请金额/币种/金额依据，点击“保存并下载”。空金额与零分别保留；填金额须有依据。参考 USD 成本沿用来源保存值，不按今天价格重算，不自动换算或分摊订阅。
7. ZIP 含 `使用明细.csv`、`每日汇总.csv`、`费用说明.html`、`导出信息.json`；导出完整筛选范围，不受当前页限制。CSV 用 Excel 打开，HTML 可打印或另存 PDF。
8. 在“报销记录”查状态、修改当前草稿或重下材料。同一资料目录只运行一个服务；误关网页后再次双击 `aha.exe` 即可找回页面。Windows 托盘支持双击打开，右键有“打开 aha”和“退出程序”；页面也保留“退出程序”。只关网页会保留后台，不会新增周期同步。

首次换用支持单实例的新版前，请先正常退出旧版；旧 EXE 不具备新版的互斥机制。不同资料目录仍可独立运行，退出只影响对应实例。

## 历史保留与核对

同步完整比较当前来源的允许字段，只把新记录和变化写入本地；旧费用回填可以识别。重复导入不产生重复消费。源库清理不会删除本地历史；源异常缩水或疑似重建先提示核对，未确认前保持原台账和成功时间。

旧备份的导入时间不代表数据更新。与已知记录冲突的备份保留候选，明确选择时填写原因；新旧key可能指向同一消费时按确认后的身份关联。只有历史日汇总就按该粒度保留，不编造明细或按比例补差。

同步对 CCS 使用有界只读事务，包含已提交 WAL，也支持 DELETE 日志模式；遇锁冲突有限等待后失败，可稍后手动重试。不会修改 CCS 的索引、日志模式、数据、设置或 Codex 会话文件。

## 报销记录与冻结材料

保存草稿即占用用量；下载失败不释放。其他记录使用剩余可用部分；两个窗口抢同一消费时后保存者须更新预览。

- 草稿可以修改用途，沿用原冻结用量，或重新按当前台账筛选；保存后只有一个有效版本。
- 已提交可带原因撤回为草稿，保留占用；也可标记已报销。
- 已报销填错时带原因作废，再新建；作废释放占用且为终态。
- 旧版本和作废版本仍能下载原包，字节与SHA不变。后续来源改价只显示与当前值的差异，不改历史申请和材料。

占用规则作用于同一份本地资料库，不协调两份独立复制的账本或外部重复发送。

## 从试用版本重建

v0.3.0 使用全新 schema3，不自动升级schema1/2，也不承接旧试用项目、人工归属、报销、占用和材料。首次运行遇到旧库会明确拒绝打开。保留旧EXE和完整恢复副本，不能让旧版直接打开新库。

本项目当前重建授权仅针对尚未正式使用的试用资料。工具 [rebuild_trial_data.py](scripts/rebuild_trial_data.py) 默认只盘点；依次执行 inspect、extract、apply、import-history。inspect 记录逐文件指纹及保护路径，extract 校验并独立保全旧留存中的CCS允许投影；apply 在退出旧程序、指纹和文件集未变化、历史已保全且备份校验成功时，才删除清单中的旧aha试用文件；import-history 将保全用量导入新台账。具体参数见各子命令 `--help`。

未知文件、CCS原件/sidecar/历史库/SQL、未保全用量、符号链接及嵌套输出都会阻断清理。不要递归删除父目录或按扩展名扫库。失败保留输入和恢复副本；回退先退出所有版本，再隔离新资料并恢复配套旧目录，不能混用数据库与材料。

## 本机资料与隐私

Windows默认 `%LOCALAPPDATA%\aha`，Linux默认 `${XDG_DATA_HOME:-~/.local/share}/aha`。`aha.sqlite3` 保存行式事实、修订/核对、归属、精确统计与新报销；`packages` 保存指定版本原ZIP。历史来源和重建恢复副本独立保管，程序不自动清理长期事实。

不读取聊天正文，不上传数据，不自动写入 OneDrive 费用目录。分享包不附全库SQL、账号配置、API Key、IP、完整来源绝对路径或目录规则；项目、用途与用户填写说明会进入材料。

服务仅监听127.0.0.1，校验Host/Origin/CSRF，资源内置。本次随机启动地址换取按端口隔离的Cookie；`runtime.json` 含临时地址与实例身份，退出删除，不应分享、提交Git或放进材料。资料目录中的 `.instance.lock` 是持久的运行锁文件，退出后保留；不要通过删除它解除运行占用。

## 开发与检查

修改前阅读 [后端规范](.trellis/spec/backend/index.md)、[前端规范](.trellis/spec/frontend/index.md) 和 [思考指南](.trellis/spec/guides/index.md)。Python3.12+；SQLite须通过运行时门禁。使用任务隔离环境，避免修改系统或工具bundled依赖：

```bash
python -m venv .venv
.venv/bin/python -m pip install -e . -r requirements-dev.txt
.venv/bin/python -m aha --data-dir .aha-data/dev --port 0 --no-browser --no-tray
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m ruff check src tests scripts
.venv/bin/python -m mypy src/aha
.venv/bin/python -m compileall -q src/aha
node --check src/aha/web/app.js
```

Windows使用 `.venv\Scripts\python.exe`。开发/测试必须指定隔离data-dir。`--port 0` 自动选择新服务端口，复用已有实例时沿用原端口；不加 `--no-browser` 自动开浏览器。`--no-tray` 用于无桌面的命令行运行，`--no-browser` 本身不会关闭 Windows 托盘。控制台输出 `AHA_URL=...`，无控制台时从私有runtime.json取本次地址。Windows Node读取WSL UNC路径失败时可从stdin检查同一脚本，见前端质量规范。

## 可复现规模验证

[benchmark_ledger.py](scripts/benchmark_ledger.py) 仅生成合成样例，固定seed、项目/模型分布、历史跨度、30%占用和1%修订；实际Store小样本链路及完整projection抽样对账独立校验。需要可容纳数据库的本机物理磁盘，不使用用户CCS输入。

```bash
.venv/bin/python scripts/benchmark_ledger.py --rows 1000000 --seed 20261028 --data-dir .aha-data/bench/1m --output .aha-data/bench/1m-seed.json --fast-seed --skip-queries
.venv/bin/python scripts/benchmark_ledger.py --rows 1000000 --seed 20261028 --data-dir .aha-data/bench/1m --output .aha-data/bench/1m.json --query-only --sync-samples 100 --sync-added 10000 --sync-revised 1000 --export-rows 100000
```

千万条将rows改为10000000、export-rows改为1000000，并使用另一新目录。fast-seed只加速夹具准备，之后恢复生产索引/参数；query-only从新进程按正常配置测量。默认预热10次/采样100次，含首/中/深游标、月/年统计、固定10000条来源窗口、内存与EXPLAIN。进程冷启动保留操作系统磁盘缓存，不做全机缓存清理；结果必须注明存储和运行时，不能用tmpfs或小样本代替目标Windows实测。本轮具体结果记录在任务verification.md。

## Windows 原生构建

在 Windows x64 的任务自有目录创建隔离环境；使用实际 Windows Python 3.12+，不能把 Linux 产物改名为 EXE。SQLite须为已修复WAL并发问题的版本（3.51.3+，或受支持的3.50.7/3.44.6维护分支）。推荐直接运行纯 Python 构建入口，无需执行 PowerShell 脚本或调整本机执行策略。打包依赖固定在 `scripts/requirements-build.txt`，开发检查依赖固定在 `requirements-dev.txt`。以下路径是构建示例，应换成实际隔离目录：

```powershell
$BuildRoot = Join-Path $env:LOCALAPPDATA 'aha-build\my-build'
python -m venv (Join-Path $BuildRoot 'venv')
$BuildPython = Join-Path $BuildRoot 'venv\Scripts\python.exe'
& $BuildPython .\scripts\build_windows.py --build-root $BuildRoot --stage Directory
```

先原生运行 `release\directory\aha\aha.exe`，使用隔离资料目录核对数据库 / SQL、压缩会话头、项目归属、本地重开、同步失败/待核对、版本重下载和退出；验证后再构建单文件：

```powershell
& $BuildPython .\scripts\build_windows.py --build-root $BuildRoot --stage OneFile --directory-verified
```

`--python-exe` 可显式指定隔离环境解释器，缺省使用当前解释器；`--source-root` 可指定源码根目录，缺省为构建脚本所在项目。入口会检查所选解释器为 64 位 Windows 隔离环境和修复版SQLite，并写runtime-versions.json，再安装固定构建依赖并采集许可证。已有的 `scripts/build_windows.ps1` 保留为兼容入口；无需为使用它改变执行策略。

便携成品在 `release\portable\aha.exe`。脚本输出 EXE 路径与 SHA-256；构建成功本身不代表通过业务验收。CSV 还需在目标 Windows 表格软件打开，HTML 在浏览器查看并打印预览。构建脚本采集实际 CPython、zstandard、zstd 和 PyInstaller 的许可证原文及指纹并内置在成品中，启动后通过页面底部“开源说明”查看。

## 数据解释依据

CCS 的 Token 语义、会话来源和历史日汇总行为参考 [farion1231/cc-switch 的固定提交 e55d8a21](https://github.com/farion1231/cc-switch/tree/e55d8a21b3897b595b746e9f2139716b2931641d)，上游采用 [MIT License](https://github.com/farion1231/cc-switch/blob/e55d8a21b3897b595b746e9f2139716b2931641d/LICENSE)。aha 为独立实现；没有复制上游配置、凭据或原始个人数据。金额沿用来源历史保存值，不按当前价格表重算。
