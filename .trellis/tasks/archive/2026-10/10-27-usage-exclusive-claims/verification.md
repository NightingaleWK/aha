# v0.2.0 实施验证记录

状态：功能实现、检查、Windows成品验收及桌面交付完成；用户已确认提交、归档和合并main，当前版本进入试用。所有开发/迁移测试在隔离目录中进行，正式资料只读复制。

## 基线与隔离环境

- 分支 `feat/usage-exclusive-claims`，基线 `a9872f1`（产品工作提交 `8d16266`）。实施前89项测试、Ruff和15文件strict mypy通过。
- 本任务 Windows 独立 venv 在 `aha-build\20261027-usage-exclusive-claims\venv`，Python3.12；已安装固定 PyInstaller6.22.3、zstandard0.25.0及任务内构建依赖，pywin32仅用于Excel验收，不改bundled/global依赖或执行策略。
- 个人QA资料仅在仓库外 `C:\Users\djsyw\Documents\Codex\aha-v02-qa-01a17b2c`；保存旧源码基线、旧版截图及独立预期，不进入Git。

## 真实资料副本

使用原生 Windows SQLite `mode=ro + backup` 创建一致副本，只复制数据库引用的允许对象与证据包，不复制 runtime 凭证：

| 隔离副本 | 来源及规划时实测 |
| --- | --- |
| real-v1-copy | 用户已有应用资料；schema1，2项目、3captures、1批次、1草稿版本，原ZIP哈希已核对 |
| legacy-v1-copy | 上轮隔离QA；schema1，2批次、3版本，含2草稿和1已报销，存在重复候选 |

两份已保存旧字段指纹，覆盖项目、归属、留存、观察、原批次/版本JSON/金额/状态、事件、幂等旧列。原生 Windows 升级已验证仅增加控制信息，原冻结字段和原包不变：

- `real-upgrade-data`：schema2、有效草稿、5,509 个独占成员；原项目、原字段及1份原ZIP一致，升级前schema1备份可读且旧字段指纹相同。
- `legacy-upgrade-data`：2批次3版本全部保留，8,982条候选占用进入待核对。真实浏览器确认跨批次冲突仍会阻止保留；填写原因作废重复批次后，可明确保留原v1已报销版，v2成为历史，原包哈希相同，不能重新申请其2,994条用量。
- 升级核验见仓库外 `migration-check.json`；人工消解实测见 `legacy-browser.json`、`legacy-pending-review.png`、`legacy-resolved.png`。

## 独立核算预期

使用从Git导出的旧版源码解析原始SQL和会话头，独立于本次实现计算：

| 范围 | 明细数 | 原保存参考成本USD |
| --- | --- | --- |
| 2026-10-26全部 | 793 | 32.8928704 |
| 同日流萤目录项目 | 791 | 32.8127404 |
| 先占流萤后的其余同日用量 | 2 | 0.080130 |
| 流萤2026-10-26至27 | 810 | 34.7441424 |

原SQL基准 SHA-256：`1c19a1b1c0da4355bcb4b98c6a47d909619b92507cebf9ad2c8f5eb8e3c7042b`。会话目录线索178个；不把线索覆盖当成业务归属证明。

## 源码检查与并发保障

- 最终全范围检查代理无遗留问题：Linux `unittest` 124项通过（11.053s，含8项报告测试），Ruff、strict mypy 17文件、compileall、原生Node语法及`git diff --check`通过；任务两份JSONL各9条校验通过。
- 原生Windows Python3.12完整123项套件通过（26.362s）；最后的报告去重修复另跑原生8项报告测试通过（2.545s）。构建暂存与最终产品/脚本/测试39个文件逐字节一致，生成的egg-info与缓存不参与产品源码比较。
- 测试实际启动两个进程竞争同一用量、同幂等请求竞争和并发迁移；断言仅一份有效占用、同请求仍同一版本、只生成一份迁移备份。另有旧活跃连接原SQL写入拒绝、备份/回填/提交故障回滚、损坏材料拒绝和旧请求不误删新owner覆盖。
- 检查阶段修正同一浏览器访问两个服务时的Cookie覆盖问题，Cookie按实际端口命名，并有共享CookieJar回归。修订弹窗预览失效后清空分析并禁用保存，必须重新预览。

## 原生 Windows 浏览器与导出

原生Windows Chrome源码冒烟成功：body/input16px、表格15px、表头/标签14px、次要13px；1440、1366、1280、768、430、375宽度根页无横溢，SQL筛选793条/32.8928704一致。新增项目弹窗可读，勾选Linux目录及手填Windows目录成功。

预检后已落实：指标前置、无排除时隐藏重复占用卡、成功提示短时浮动、保存表单位于长明细前。操作成功会清理先前错误；当前失败保留并在对应弹窗显示。CNY/USD完整显示，不被金额控件挤掉。

目录EXE完整主流程和退出重启已通过，使用实际Windows Chrome156、真实后端和独立资料目录，见 `directory-final-browser.json`、`directory-final-restart.json`：

1. SQL导入793条；创建流萤项目并勾选Linux目录、手填Windows目录，归属791条。
2. A保存791条后，B过期预览保存返回409；刷新只余2条/0.080130 USD，可单独保存。全部查看793条但禁用新建。
3. A专用修订预览可沿用自身791条，扩展日期得到810条/34.7441424 USD；其他窗口改占用后旧弹窗保存失败且禁用，刷新后才生成v2；v1仅可下载。
4. v2提交、带原因撤回均保留占用；已报销后作废必须填写原因，作废后释放，C可重新占用791条。
5. 重试旧创建及作废请求不复活A、不删除C的新占用；作废后及进程重启后v1原包SHA相同；退出删除runtime描述符并关闭监听端口。
6. 最终界面计算字号与约定一致，1440/1366/1280/768/430/375宽度根页无横溢。已留存优化前截图、用量页、剩余页、修订/作废弹窗、报销记录及窄窗口截图，并实际查看。

`directory-final-export-check.json`：原791条、剩余2条、修订810条的四文件包均通过精确Decimal/Token加总、manifest来源与文件SHA、隐私白名单核对；Excel16.0逐份实际打开6个CSV，中文、23/17列及数值合计正确。三份HTML按A4打印，各1页，PDF中文/金额/末尾信息完整，逐页渲染并检查（`directory-final-print-check.json`）。

最后发现费用说明重复通用参考成本提示，已兼容过滤新旧文案，仅保留一次“申请人填写”说明，JSON原始warnings不改。重新构建的目录包SHA为 `09b9f5320476be40577a5c67b3cc5505b072f7b71e1956746ece764e3a5a3f9d`；新EXE再次SQL导入/保存793条、生成新包通过，HTML去重与原金额核对通过（`directory-release-smoke.json`、`directory-release-report-check.json`）。完整主流程中的早先冻结包按原字节保留。

## 最终单文件与桌面交付

- 先目录包验收，后运行纯Python入口构建OneFile。最终Windows x64 EXE共10,171,446字节，SHA-256为 `40a41fe7a35bdd956da6a2723014e2755c70cedd2f291a5e401898fa7ff9ba99`。
- `portable-browser.json`、`portable-restart.json`：最终OneFile重复上述完整主流程，791→2剩余、810修订、过期弹窗禁保存、撤回/作废/释放、旧请求重试、历史包及重启全部通过，无浏览器错误，6种宽度无根页横溢；程序退出时runtime删除、端口关闭。
- `portable-export-check.json`：最终EXE三份新包分别791/2/810条，金额32.8127404/0.080130/34.7441424 USD精确一致。Excel16.0实际打开6个CSV、中文和列数/求和通过，JSON来源与文件哈希一致、分享包隐私核对通过。
- `portable-print-check.json`：三份最终HTML按A4各打印1页，PDF文字和金额检查通过；全部页面已渲染并实际查看，无重复通用说明、裁切或空白页。
- `portable-real-v1-data`来自只读基线再次克隆，启动最终OneFile前确认为schema1。实际EXE首次启动完成备份与schema2升级，保留2项目、1草稿、原材料哈希；5,509条成员接续占用。升级前schema1备份可读，全部旧字段指纹与基线相同，见`portable-real-upgrade-browser.json`、`portable-real-upgrade-db-check.json`。这不是正式资料升级。
- 桌面新目录 `C:\Users\djsyw\Desktop\aha-v0.2.0-20261027` 已交付 `aha.exe`、`使用说明.txt`、`SHA256SUMS.txt`，无QA项目或测试证据包。复制前后EXE哈希相同，见`desktop-release.json`。
- 从桌面实际EXE启动、未传`--no-browser`，用独立浏览器配置与独立data-dir观察其自动打开页面、自动读取本机来源并正常退出；QA没有替程序导航，见`auto-launch-check.json`与`desktop-exe-auto-launch.png`。
- v0.1.0原EXE SHA仍为`9db93fb5c58406afcd3de138063a961dc14d66e224c8157fe9fb60753f24260a`，原SQL SHA仍为上文基准。没有将开发或QA程序指向正式应用资料目录，也没有写OneDrive原件。

## 最终门槛

- [x] 全范围检查代理通过；完整Linux及原生Windows套件及最后报告增量、Ruff、strict mypy、Node语法通过。
- [x] 两独立连接/进程占用竞争、幂等与旧writer写入防护、故障回滚证据。
- [x] v1真实副本正常升级、冲突副本待核对→作废/确认，原字段/ZIP一致，备份可恢复。
- [x] 目录包/单文件在原生Windows运行、退出重启、历史原包下载、旧请求不复活。
- [x] 真实浏览器791占用→2剩余→草稿换版→提交/撤回→报销作废→释放重用；新建/修订主体不可混用。
- [x] 目录包及最终单文件可用预览、CSV、每日、HTML/JSON金额一致，Excel实际打开，说明页A4打印逐页检查。
- [x] 最终字体/文案/长内容/桌面和窄窗口检查，保存优化前后viewport截图。
- [x] 新EXE桌面交付及SHA-256，旧v0.1.0/原SQL/正式资料不自动覆写；规范与README同步。

目录包与单文件包的最终结果分别记录，不以构建成功代替运行验证。本记录为开发交付验收；未在正式资料执行迁移或代用户进行真实报销。
