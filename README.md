# aha · 用量与费用

aha 是 Windows 本机 Codex 用量台账与报销材料工具，用来记住每笔消费、归到对应项目，回答每个项目用了多少，并形成向公司申请报销的证据。双击 `aha.exe` 后在浏览器使用，运行环境和 SQLite 均内置；消费和项目关系长期保存在 aha 自己的数据库。

## 下载与版本

正式版本统一在 [GitHub Releases](https://github.com/NightingaleWK/aha/releases) 提供 Windows x64 单文件 EXE、中文版 What’s New 和 SHA256 校验信息。当前运行版本显示在程序页面右上角；下载后可改名为 `aha.exe` 使用。程序仍在本机离线运行，本轮没有增加联网检查更新或自动安装。

开发采用发布 PR：功能合入 main 后自动汇总下一版的版本号和说明，维护者合并发布 PR 后由 GitHub Windows 环境构建验证，再公开 Release。构建或验收未完成时只保留候选/草稿，首次启用是否已完成以真实 Releases 和 Actions 运行结果为准。维护步骤见 [发版说明](docs/RELEASING.md)。

## 使用

1. 首次使用时打开“数据来源”，确认 Windows 的 Codex 目录和要接入的 WSL 发行版。路径留空时从所选环境发现当前 Codex 目录。WSL 内需要可用的 Python 3。绑定后每次启动自动同步一次，平时也可点“立即同步”。
2. Windows 和 WSL 各自显示读取状态、已核对的范围和上次成功时间。一端不可用时仍可接续另一端，已有台账也可继续查询。换机及还原后在新台账中重新确认来源。
3. 在“项目管理”新建项目并选择一个或多个工作目录，点击“查看关联影响”，核对各目录记录数、参考费用和原项目→目标项目变化，再“确认保存并关联”。一次确认将这些目录内有明确依据的已有记录整体归入项目，旧人工分到其他项目的记录也统一迁入；以后新会话、旧会话新增及稍后才识别目录的用量随同步自动关联，无需逐条选择或勾选整个会话。已有项目点击“确认目录关联”采用同一流程，升级不会自动重算旧项目；同一目录转移时同时调整原项目的目录和费用。
4. 在“用量与费用”搜索选择项目，打开时间面板，可选当天、近24小时、近7/14/30天、本月或全部，也可用日历和时间输入精确到分钟。确认后直接更新预览，取消保留原结果。全部按北京时间，手动结束时间包含该分钟；勾选跟随当前时刻后，每次更新预览才推进结束时刻。明细、历史日汇总、每日和模型使用游标翻页，查询使用已保存在 aha 的台账。
5. 默认“可用用量”排除已占用及待核对部分，显示原因。“全部用量（查看）”用于核对，不能直接保存新申请。明细与来源历史日汇总存在重叠时不相加，身份、版本或覆盖不清楚时先核对。
6. 填写用途、选填申请金额/币种/金额依据，点击“保存并下载”。空金额与零分别保留；填金额须有依据。新用量按随程序发布的模型参考价估算，旧用量沿用已保存金额。缺价会单独提示，参考成本与申请金额分别显示。
7. ZIP 含 `使用明细.csv`、`每日汇总.csv`、`费用说明.html`、`导出信息.json`；导出完整筛选范围，不受当前页限制。CSV 用 Excel 打开，HTML 可打印或另存 PDF。
8. 在“报销记录”查状态、修改当前草稿或重下材料。同一资料目录只运行一个服务；误关网页后再次双击 `aha.exe` 即可找回页面。Windows 托盘支持双击打开，右键有“打开 aha”和“退出程序”；页面也保留“退出程序”。只关网页会保留后台，不会新增周期同步。

只有整天汇总的历史用量无法按小时拆分。选择覆盖某天一部分的范围时，程序省略该天汇总并提示“统计不完整”；范围内已确定的明细仍可保存，也可点“改查整天”纳入整天汇总。保存及材料沿用最后一次成功预览的实际范围，不会因等待时间变长而悄悄增加用量。旧记录继续保留原冻结内容和原下载包，历史未保存的完整性信息显示未知。

目录绑定以整组目录为单位，用户只选择纳入哪些目录。无目录依据、冲突依据和没有会话的历史日汇总不会被猜入项目，可在高级资料处理中核对；不同项目的父子目录重叠须先调整目录范围。换机时将新目录追加到原项目，旧日志缺失不撤销已确认历史；只停用目录会停止未来识别并保留已有历史。已确认目录内不能再创建逐条相反项目例外，纠错应调整目录所属项目。

同期间待归属的消费单独提示，不计入某个项目，也不阻止已确认的项目成员正常报销。新材料记录当次归属覆盖说明；项目合计、逐笔成员与日汇总使用同一依据，历史材料保持原样。只有整天汇总的旧记录仍按整条分配，不编造已不存在的逐笔项目证据。

首次换用支持单实例的新版前，请先正常退出旧版；旧 EXE 不具备新版的互斥机制。不同资料目录仍可独立运行，退出只影响对应实例。

## 历史保留与核对

同步只读 Codex 会话和压缩归档。已读文件从已确认进度继续，日志复制到另一端或归档后会按事件证据去重。正在写入的尾行待完整后继续处理，来源不可达或记录形态存在疑问时显示覆盖提示。清理源日志不会删除 aha 已保存的事实。

旧台账的逐笔费用、整日汇总、项目和报销材料继续可用。补采和已入账历史重叠时可查看核对依据，待确认的新用量留在核对记录中。若有历史只保存于外部 CCS 文件而原生会话已丢失，需要留存时先用旧版按确认范围导入旧 aha 台账，再生成完整备份。

新分析和材料继续用 `usage_projection_schema_version=23` 表示内部用量字段契约。材料保留 `source_schema_version=23` 和 `source_schema_version_scope=normalized_usage_projection` 兼容字段。原生模型价格依据随材料保存，旧包下载保持原字节。

## 换电脑与完整备份还原

“备份与还原”生成完整`.aha-backup`，包含一致台账、项目与目录依据、核对、报销占用和全部版本原包。下载后保存在自己选择的备份位置。完整备份含个人资料，不能当费用分享包发送。换机、还原或重要资料调整前先保存一份完整备份，平时定期另存到不同存储；仅留在同一块磁盘不能防磁盘损坏。

还原后重新确认本机 Codex 来源，已确认事件可以去重接续。旧日志缺失时，已保存的目录依据和历史仍可查。编辑原项目追加新目录，预览影响并确认后继续自动关联。

旧版本已经使会话目录失效时，在“项目管理 → 检查历史关联恢复”预览 aha 留存的历史依据。唯一有效目录可恢复并按当前项目规则重建关联；仅能找回目录或存在冲突的部分继续进入待归属清单，供批量确认，无需找回旧电脑日志。

schema 3 和 schema 4 的正式台账在升级前自动生成完整回退备份，再迁移到 schema 5。旧版完整备份可还原到独立目录并升级。需要回退时，用与旧库配套的 EXE 打开升级前备份的还原目录。

还原先校验数据库、索引、文件和原包SHA，再生成**新的资料目录**，不在线覆盖当前台账。完成后点“打开还原台账”；恢复结果也提供再次打开命令。默认双击EXE仍打开原默认目录，两个目录各自独立；在恢复台账中确认本机来源后再接续。只有日汇总的旧历史仍按整日使用，不还原为并不存在的逐条明细。

离线操作也可使用同一个EXE（目标备份文件和还原目录都必须尚不存在）：

```text
aha.exe --data-dir EXISTING_DATA --backup NEW.aha-backup
aha.exe --restore-backup SAVED.aha-backup --restore-dir NEW_DATA_DIRECTORY
aha.exe --data-dir NEW_DATA_DIRECTORY
```

不要在程序运行时只复制`aha.sqlite3`而遗漏WAL或历史原包。不要用试用库重建/清理工具处理正式账本。完整恢复不是两个独立aha业务库的自动合并，报销占用只在同一账本内协调。

## 报销记录与冻结材料

保存草稿即占用用量；下载失败不释放。其他记录使用剩余可用部分；两个窗口抢同一消费时后保存者须更新预览。

- 草稿可以修改用途，沿用原冻结用量，或重新按当前台账筛选；保存后只有一个有效版本。
- 已提交可带原因撤回为草稿，保留占用；也可标记已报销。
- 已报销填错时带原因作废，再新建；作废释放占用且为终态。
- 旧版本和作废版本仍能下载原包，字节与SHA不变。后续来源改价只显示与当前值的差异，不改历史申请和材料。

占用规则作用于同一份本地资料库，不协调两份独立复制的账本或外部重复发送。

## 从试用版本重建

v0.3.0 起的正式台账使用 schema3，当前支持正式 schema 3/4 台账升级到 schema 5；schema1/2 仍属于旧试用资料，不自动承接其项目、人工归属、报销、占用和材料。遇到上述旧试用库会明确拒绝打开。保留旧EXE和完整恢复副本，不能让旧版直接打开新库。

本项目当前重建授权仅针对尚未正式使用的试用资料。工具 [rebuild_trial_data.py](scripts/rebuild_trial_data.py) 默认只盘点；依次执行 inspect、extract、apply、import-history。inspect 记录逐文件指纹及保护路径，extract 校验并独立保全aha 旧留存中的用量投影；apply 在退出旧程序、指纹和文件集未变化、历史已保全且备份校验成功时，才删除清单中的旧aha试用文件；import-history 将保全用量导入新台账。具体参数见各子命令 `--help`。

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
node --check src/aha/web/form-controls.js
node --check src/aha/web/time-range-picker.js
node --test tests/web_state.test.cjs
```

Windows使用 `.venv\Scripts\python.exe`。开发/测试必须指定隔离data-dir。`--port 0` 自动选择新服务端口，复用已有实例时沿用原端口；不加 `--no-browser` 自动开浏览器。`--no-tray` 用于无桌面的命令行运行，`--no-browser` 本身不会关闭 Windows 托盘。控制台输出 `AHA_URL=...`，无控制台时从私有runtime.json取本次地址。Windows Node读取WSL UNC路径失败时可从stdin检查同一脚本，见前端质量规范。

## 可复现规模验证

[benchmark_ledger.py](scripts/benchmark_ledger.py) 仅生成合成样例，固定seed、项目/模型分布、历史跨度、30%占用和1%修订；实际Store小样本链路及完整projection抽样对账独立校验。需要可容纳数据库的本机物理磁盘，使用独立合成资料。

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

先原生运行 `release\directory\aha\aha.exe`，使用隔离资料目录核对原生会话增量、压缩归档、项目归属、本地重开、同步失败、旧原包下载、备份还原和退出；验证后再构建单文件：

```powershell
& $BuildPython .\scripts\build_windows.py --build-root $BuildRoot --stage OneFile --directory-verified
```

`--python-exe` 可显式指定隔离环境解释器，缺省使用当前解释器；`--source-root` 可指定源码根目录，缺省为构建脚本所在项目。入口会检查所选解释器为 64 位 Windows 隔离环境和修复版SQLite，并写runtime-versions.json，再安装固定构建依赖并采集许可证。已有的 `scripts/build_windows.ps1` 保留为兼容入口；无需为使用它改变执行策略。

便携成品在 `release\portable\aha.exe`。脚本输出 EXE 路径与 SHA-256；构建成功本身不代表通过业务验收。每版独立验证 Directory/OneFile 的原生程序、HTTP、资源、材料和退出。首次发布完成本机全面验收；以后涉及材料生产链时补 Excel/打印，涉及托盘/启动退出时补相关交互，运行时和构建环境变化时重新全面验收，具体见 [发布合同](.trellis/spec/backend/release-contract.md)。构建脚本采集实际 CPython、zstandard、zstd 和 PyInstaller 的许可证原文及指纹并内置在成品中，启动后通过页面底部“开源说明”查看。

## 数据解释依据

Codex 会话事件语义与参考价的依据见 [Codex 会话实现](https://github.com/openai/codex/tree/main/codex-rs/core/src/session) 和 [OpenAI API 官方定价](https://developers.openai.com/api/docs/pricing)。不同版本产生的事件先核对语义，再归一输入、缓存和输出 Token。

旧台账已有的 CCS 用量、历史日汇总和原参考成本保留其入口与核算依据。 [历史投影参考和许可](https://github.com/farion1231/cc-switch/tree/d0da1349f9403da228dc12a8f0f812e14f624d10)
