# GitHub 版本与发版研究（2026-11-02）

## 当前仓库证据

| 核查对象 | 只读结果与意义 |
| --- | --- |
| 本地 `pyproject.toml:7` / `src/aha/__init__.py:3` | 均为 0.3.1，存在两处版本文字，需要权威来源及一致性校验。 |
| `src/aha/server.py:129-145` / `src/aha/web/app.js:879` | 状态接口已有程序版本，页面已显示该版本；无需为版本管理另造页面。 |
| `src/aha/evidence.py:432` | 新材料记录应用版本；既有冻结材料保持原字节，版本治理不能回写历史材料。 |
| `scripts/build_windows.py:23-55` | 原生 Windows x64、venv、Python3.12+ 和修复版 SQLite 的构建前置要求。不能假设 Actions 任一 Python 自带 SQLite 都符合门禁。 |
| `scripts/build_windows.py:59-164` | 复用现有固定依赖、许可证采集、Directory / OneFile 和 SHA256 输出；当前没有 `--version-file`。 |
| GitHub `GET /repos/NightingaleWK/aha/releases?per_page=10` | 返回 `[]`，尚无 Release；通过 GitHub 连接器只读查询。 |
| GitHub `main:pyproject.toml` | 远端版本为 0.3.0，需先确定首次发布确切基线，不能直接认定 0.3.1 已在 main。 |
| GitHub `GET /repos/NightingaleWK/aha/contents/.github?ref=main` | 返回 404，远端主分支没有该目录。 |
| Actions workflows 集合端点 | 当前 GitHub 连接器拒绝 `/actions/workflows`；未据此推断平台设置。`.github` 不存在这一结论来自 contents 接口及本地检查。 |

## 官方资料与已核对能力

- [GitHub Actions 概念](https://docs.github.com/en/actions/get-started/understand-github-actions)：Actions 是 CI/CD 平台；workflow 是保存在 `.github/workflows` 的 YAML，可由 pull request、push、人工操作或计划触发。本任务适合仓库事件触发，无需额外的定时任务。
- [GitHub 托管执行环境](https://docs.github.com/en/actions/concepts/runners/github-hosted-runners)：提供 Windows / Linux / macOS 运行环境；可在 Windows 云端执行项目现有构建脚本，无需依赖维护者电脑开机。
- [GitHub Releases](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)：Release 关联 Git 标签并可附更新说明和二进制下载；EXE 作为 release asset 上传，不能仅上传 Actions artifact 代替正式下载交付。
- [语义化版本官方规范](https://semver.org/lang/zh-CN/)：格式为 `X.Y.Z`；已发布版本内容不得改变；0.y.z 为初始开发阶段，稳定兼容性承诺从 1.0.0 开始。具体 0.x 规则需要在项目政策中明确。
- [Release Please Action 官方说明](https://github.com/googleapis/release-please-action)：根据 Conventional Commits 更新版本、CHANGELOG 并维护发布 PR，合并该 PR 后生成标签/Release；支持 Python 项目。用户已选择发布 PR 节奏，具体工具仍待最终技术规划审阅。

## 设计阶段必须解决的技术点

1. **发布触发与凭证**：Release Please README 对默认 `GITHUB_TOKEN` 创建资源的触发限制描述较旧。2026-11-02 核对 [GitHub 当前官方规则](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow)：`workflow_dispatch` / `repository_dispatch` 可触发；机器人触发的 `pull_request` opened / synchronize / reopened 可产生待人工批准的运行；其他多数令牌触发事件不会启动新运行。不能假设机器人创建标签后另一个 push-tag workflow 必然执行，也不能假设机器人 PR 的 CI 无需批准就自动开始。设计可使用同一编排、显式 dispatch 或 GitHub App；发布 PR 自身的 CI 与分支保护必须对应实际 HEAD。
2. **先验收再公开发布**：工具默认创建 Release 的时序不等同于本项目要求的产物已验证；设计应保证正式公开前已有通过检查的对应 EXE，可采用候选/草稿后发布等受支持方式。不能让空 Release 被当作成功。
3. **重跑与确切提交**：固定待发布提交 SHA；构建、检查、标签及上传均对应同一 SHA。重跑复用或恢复未完成候选，不覆盖已有正式资产；并发发版要有明确顺序。
4. **现有 Windows 门禁**：GitHub 云端自动 HTTP、资源、资料隔离、重开/退出、导出字节等检查可补强，但并不提供用户本机托盘物理点击、Office Excel 和打印实测的证据。须在设计中明确保留这些要求的方式，或经用户确认形成不同的云端正式发布验收政策。
5. **首次发布基线**：当前本地0.3.1、远端main0.3.0且无标签/Release，不能盲目从全部历史自动计算首版或自动升到1.0；实施前确定已批准源码基线及首个正式编号。
6. **版本与成品身份**：选择单一权威版本来源及工具适配方式，覆盖包版本、运行时、Windows PE 资源、Release 标签和校验文件。历史文档版本及冻结材料不是需要批量改写的运行时副本。
7. **工具能力补证**：Release Please [manifest 配置](https://github.com/googleapis/release-please/blob/main/docs/manifest-releaser.md) 支持 `draft`、`bootstrap-sha`、`release-as`、`bump-minor-pre-major`、`bump-patch-for-minor-pre-major` 和 `changelog-sections`；可明确首次版本与0.x递增策略。草稿默认可能延迟创建标签，须设计其与后续版本识别、失败重跑的关系，不能仅把 `draft: true` 当作完整失败恢复方案。

## 当前边界

用户已选择发布PR节奏、自动What’s New及验收方式1；补充研究见 [whats-new-design.md](whats-new-design.md)。产品决定已收敛，技术设计和执行计划已形成。目前仅修改规划材料，没有新增工作流、启动构建或更改远端，等待最终规划审阅。

## 技术设计补证

- [setuptools动态元数据](https://setuptools.pypa.io/en/latest/userguide/pyproject_config.html#dynamic-metadata) 支持 `dynamic = ["version"]` 和属性 `aha.__version__`，可保留当前包内字面量作为唯一产品版本。
- 已读Release Please [Python策略源码](https://github.com/googleapis/release-please/blob/main/src/strategies/python.ts)：它根据发行名查找包内 `__init__.py`，发行名 `aha-usage` 不会自动定位到 `src/aha/__init__.py`。因此设计显式配置generic extra-file，而不是假定Python策略会更新正确包。
- 已读 [PyProjectToml updater源码](https://github.com/googleapis/release-please/blob/main/src/updaters/python/pyproject-toml.ts)：识别动态version后跳过写入，能与setuptools动态版本共存。具体固定action版本仍须在实施时验证同样行为。
- [PyInstaller官方使用说明](https://www.pyinstaller.org/en/stable/usage.html#windows-specific-options) 支持 `--version-file`，可以从权威版本生成Windows版本资源，不另设人工数字。
- 2026-11-02通过GitHub连接器读取 [Actions官方Python版本manifest](https://github.com/actions/python-versions/blob/main/versions-manifest.json)：稳定3.15.2提供win32/x64资源。选用此版本仍须在实际runner探测SQLite、依赖及打包，不将“有下载”当成“本项目已构建通过”。
- 项目上一轮归档验收 `.trellis/tasks/archive/2026-11/11-02-ccs-schema-compatibility/verification.md` 记录本机3.15.2/SQLite3.53.4可用；明确没有托盘物理点击证据，且交付后的文件位置发生变化。这仅帮助选择运行时和保护现有实例，本轮仍须独立做首次全面验收及确认实际桌面，不复用历史结果冒充新证据。
