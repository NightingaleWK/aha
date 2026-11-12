# aha · 用量与费用

aha 是 Windows 本机 Codex 用量台账与报销材料工具，用来记住每笔消费、归到对应项目，回答每个项目用了多少，并形成向公司申请报销的证据。双击 `aha.exe` 后在浏览器使用，运行环境和 SQLite 均内置；消费和项目关系长期保存在 aha 自己的数据库。

## 下载与版本

正式版本统一在 [GitHub Releases](https://github.com/NightingaleWK/aha/releases) 提供 Windows x64 单文件 EXE、中文版 What’s New 和 SHA256 校验信息。当前运行版本显示在程序页面右上角；下载后可改名为 `aha.exe` 使用。程序仍在本机离线运行，本轮没有增加联网检查更新或自动安装。

开发采用发布 PR：功能合入 main 后自动汇总下一版的版本号和说明，维护者合并发布 PR 后由 GitHub Windows 环境构建验证，再公开 Release。构建或验收未完成时只保留候选/草稿，首次启用是否已完成以真实 Releases 和 Actions 运行结果为准。维护步骤见 [发版说明](docs/RELEASING.md)。

## 使用

1. 每次打开程序自动同步一次 `%USERPROFILE%\.cc-switch\cc-switch.db`；也可点“立即同步”、填写其他 SQLite 路径或导入 SQL 备份。SQLite与SQL用量备份支持CCS结构版本23、24、25，仅统计 `codex_session`。同步不要求抢在CCS前启动。旧台账换机或还原后会先提示确认本机来源，历史保持可查询。
2. 页面先显示已有本地资料。来源正忙、无法读取或同步失败时仍可查询旧资料，并显示上次成功时间；需要核对的来源变化单独提示。程序只在打开和手动操作时读取来源，没有周期采集、关闭后同步或开机自启。
3. 在“项目管理”查看各项目费用和待归属进度。新建项目后可设置多个工作目录，作为新会话的自动识别线索。已确认的逐笔归属持续保存，换机或移除旧目录不会改变过去的项目费用。按目录、会话或时间筛选待归属记录，选择全部筛选结果可跨页批量分配，先看影响再确认；整会话可覆盖现存和后续新增明细，逐条人工例外优先。纠正历史时单独预览“重新归属”，保存目录规则本身不回写历史。
4. 在“用量与费用”搜索选择项目，打开时间面板，可选当天、近24小时、近7/14/30天、本月或全部，也可用日历和时间输入精确到分钟。确认后直接更新预览，取消保留原结果。全部按北京时间，手动结束时间包含该分钟；勾选跟随当前时刻后，每次更新预览才推进结束时刻。明细、历史日汇总、每日和模型使用游标翻页，查询不依赖原 CCS 文件仍存在。
5. 默认“可用用量”排除已占用及待核对部分，显示原因。“全部用量（查看）”用于核对，不能直接保存新申请。明细与来源历史日汇总存在重叠时不相加，身份、版本或覆盖不清楚时先核对。
6. 填写用途、选填申请金额/币种/金额依据，点击“保存并下载”。空金额与零分别保留；填金额须有依据。参考 USD 成本沿用来源保存值，不按今天价格重算，不自动换算或分摊订阅。
7. ZIP 含 `使用明细.csv`、`每日汇总.csv`、`费用说明.html`、`导出信息.json`；导出完整筛选范围，不受当前页限制。CSV 用 Excel 打开，HTML 可打印或另存 PDF。
8. 在“报销记录”查状态、修改当前草稿或重下材料。同一资料目录只运行一个服务；误关网页后再次双击 `aha.exe` 即可找回页面。Windows 托盘支持双击打开，右键有“打开 aha”和“退出程序”；页面也保留“退出程序”。只关网页会保留后台，不会新增周期同步。

只有整天汇总的历史用量无法按小时拆分。选择覆盖某天一部分的范围时，程序省略该天汇总并提示“统计不完整”；范围内已确定的明细仍可保存，也可点“改查整天”纳入整天汇总。保存及材料沿用最后一次成功预览的实际范围，不会因等待时间变长而悄悄增加用量。旧记录继续保留原冻结内容和原下载包，历史未保存的完整性信息显示未知。

同期间待归属的消费单独提示，不计入某个项目，也不阻止已确认的项目成员正常报销。新材料记录当次归属覆盖说明；项目合计、逐笔成员与日汇总使用同一依据，历史材料保持原样。只有整天汇总的旧记录仍按整条分配，不编造已不存在的逐笔项目证据。

首次换用支持单实例的新版前，请先正常退出旧版；旧 EXE 不具备新版的互斥机制。不同资料目录仍可独立运行，退出只影响对应实例。

## 历史保留与核对

同步完整比较当前来源的允许字段，只把新记录和变化写入本地；旧费用回填可以识别。重复导入不产生重复消费。源库清理不会删除本地历史；源异常缩水或疑似重建先提示核对，未确认前保持原台账和成功时间。

旧备份的导入时间不代表数据更新。与已知记录冲突的备份保留候选，明确选择时填写原因；新旧key可能指向同一消费时按确认后的身份关联。只有历史日汇总就按该粒度保留，不编造明细或按比例补差。

同步对 CCS 使用有界只读事务，包含已提交 WAL，也支持 DELETE 日志模式；遇锁冲突有限等待后失败，可稍后手动重试。不会修改 CCS 的索引、日志模式、数据、设置或 Codex 会话文件。

来源结构版本与 aha 内部用量投影版本分别记录：每次成功读取的同步结果保留实际 CCS 结构版本；内部历史投影仍为 23，应用库为 schema4。未知 CCS 版本会明确提示实际版本和当前支持范围，不会忽略必要字段检查。新分析和材料通过 `usage_projection_schema_version` 标明内部投影版本；材料的旧兼容字段 `source_schema_version=23` 由 `source_schema_version_scope=normalized_usage_projection` 说明其含义，不代表所有历史记录都来自 CCS 23。旧投影未记录的真实来源版本保留未知，已有下载包保持原字节。

## 换电脑与完整备份还原

“导入CCS用量备份”只补入CCS的SQL用量，不包含aha项目、人工归属或报销材料。“备份与还原”生成完整`.aha-backup`，包含一致台账、项目/目录依据、核对、报销占用和全部版本原包；请下载后保存在自己选择的备份位置。完整备份含个人资料，不能当费用分享包发送。换机、还原或重要资料调整前先保存一份完整备份，平时定期另存到不同存储；仅留在同一块磁盘不能防磁盘损坏。

换机保留现有aha历史，把新电脑CCS确认为新来源再同步。相同消费不重复计入；不同历史值和来源汇总重叠保留核对。源库为空、较小或不支持时不会清空旧历史；当前时段为空时可点“查看全部历史”，申请报销再切回“可用用量”。新电脑没有旧会话日志不会清除原目录依据，新目录可作为原项目的附加规则。

旧版本已经使会话目录失效时，在“项目管理 → 检查历史关联恢复”预览 aha 留存的历史依据。唯一有效目录可恢复并按当前项目规则重建关联；仅能找回目录或存在冲突的部分继续进入待归属清单，供批量确认，无需找回旧电脑日志。

首次打开正式 schema3 台账会先自动保留完整回退备份，再无损升级为 schema4，项目、用量、占用和旧材料保留。旧 schema3 完整备份仍可还原到新目录并升级；旧版程序不能打开已升级的新库。需要回退时使用保留的原 schema3 备份及配套旧程序，不将两个版本交替指向新库。

还原先校验数据库、索引、文件和原包SHA，再生成**新的资料目录**，不在线覆盖当前台账。完成后点“打开还原台账”；恢复结果也提供再次打开命令。默认双击EXE仍打开原默认目录，两个目录各自独立；在恢复台账中确认本机来源后再接续。只有日汇总的旧历史仍按整日使用，不还原为并不存在的逐条明细。

离线操作也可使用同一个EXE（目标备份文件和还原目录都必须尚不存在）：

```text
aha.exe --data-dir EXISTING_DATA --backup NEW.aha-backup
aha.exe --restore-backup SAVED.aha-backup --restore-dir NEW_DATA_DIRECTORY
aha.exe --data-dir NEW_DATA_DIRECTORY
```

不要在程序运行时只复制`aha.sqlite3`而遗漏WAL或历史原包。不要用试用库重建/清理工具处理正式schema3/4账本。完整恢复不是两个独立aha业务库的自动合并，报销占用只在同一账本内协调。

## 报销记录与冻结材料

保存草稿即占用用量；下载失败不释放。其他记录使用剩余可用部分；两个窗口抢同一消费时后保存者须更新预览。

- 草稿可以修改用途，沿用原冻结用量，或重新按当前台账筛选；保存后只有一个有效版本。
- 已提交可带原因撤回为草稿，保留占用；也可标记已报销。
- 已报销填错时带原因作废，再新建；作废释放占用且为终态。
- 旧版本和作废版本仍能下载原包，字节与SHA不变。后续来源改价只显示与当前值的差异，不改历史申请和材料。

占用规则作用于同一份本地资料库，不协调两份独立复制的账本或外部重复发送。

## 从试用版本重建

v0.3.0 起的正式台账使用 schema3，当前支持其无损升级到 schema4；schema1/2 仍属于旧试用资料，不自动承接其项目、人工归属、报销、占用和材料。遇到上述旧试用库会明确拒绝打开。保留旧EXE和完整恢复副本，不能让旧版直接打开新库。

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
node --check src/aha/web/form-controls.js
node --check src/aha/web/time-range-picker.js
node --test tests/web_state.test.cjs
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

便携成品在 `release\portable\aha.exe`。脚本输出 EXE 路径与 SHA-256；构建成功本身不代表通过业务验收。每版独立验证 Directory/OneFile 的原生程序、HTTP、资源、材料和退出。首次发布完成本机全面验收；以后涉及材料生产链时补 Excel/打印，涉及托盘/启动退出时补相关交互，运行时和构建环境变化时重新全面验收，具体见 [发布合同](.trellis/spec/backend/release-contract.md)。构建脚本采集实际 CPython、zstandard、zstd 和 PyInstaller 的许可证原文及指纹并内置在成品中，启动后通过页面底部“开源说明”查看。

## 数据解释依据

CCS 的 Token 语义、会话来源、历史日汇总和结构23→24→25兼容行为参考[farion1231/cc-switch固定提交efbec38f](https://github.com/farion1231/cc-switch/tree/efbec38f0e1ecaee2a488d619190b7ec4075238b)，上游采用 [MIT License](https://github.com/farion1231/cc-switch/blob/efbec38f0e1ecaee2a488d619190b7ec4075238b/LICENSE)。aha 为独立实现；没有复制上游配置、凭据或原始个人数据。金额沿用来源历史保存值，不按当前价格表重算。
