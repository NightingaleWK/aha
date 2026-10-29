# 执行计划：单实例重开与 Windows 托盘退出

## 进入实施前

- [x] 用户同意创建任务；状态保持 planning。
- [x] 核对源码、既有规范、HTTP/CLI 检查与官方 API。
- [x] PRD 归并为最终需求和 AC，补齐技术设计与实现/检查上下文。
- [x] 用户在最新最终规划摘要之后明确回复“开始实现”（2026-10-28）。
- [x] 已加载 Phase 1.4，确认基线并创建 `codex/single-instance-tray` 分支；按已批准计划激活任务。

本任务是一个完整生命周期交付，不拆成独立发布的子任务。实施与检查遵循当前 Trellis 子代理方式，主会话协调、维护规范和收尾。派发以 `Active task: .trellis/tasks/10-28-single-instance-tray` 开头，先加载相应阶段上下文；planning 阶段不派发实现。

## 实施顺序

### 1. 运行权与重开

- [x] 新增 instance.py：目录规范化、持久锁、有限等待、原子描述符与本次归属清理。
- [x] 增加认证 GET /api/instance 和严格回环核验；复用不得创建 Store 或请求同步。
- [x] 接入 CLI，保留 AHA_URL、默认位置和参数；明确复用时沿用端口。
- [x] 独立进程覆盖连续/并发 5 次、不同目录、常见路径别名、崩溃、坏描述符、非 aha 端口、PID 复用与持锁超时。浏览器替身验证启动器请求打开正确的已验证地址。
- [x] 阶段回退点：托盘接入前 CLI/HTTP 仍可用；失败只回退本任务代码，不修改用户资料。

### 2. 生命周期与托盘

- [x] 新增 runtime.py，统一退出、ready/stopping/closed、启动失败清理；锁最后释放。
- [x] 新增 tray_windows.py：主线程消息循环、菜单、双击/键盘、TaskbarCreated 和完整句柄清理。
- [x] 增加 --no-tray，CLI 自动检查明确使用它；加入内置 ICO 并更新包资源和两个 Windows 构建入口，保留许可证与目录包门禁。
- [x] 必要时调整页面退出文案，避免请求接受即声称已完全退出；不加 unload 退出。
- [x] 验证同步中退出、重复/同时退出、服务线程失败、托盘失败、浏览器失败和退出过程中重开，核对资料/历史 ZIP 保留。
- [x] 阶段回退点：原生托盘失败须修复，不以默认关闭托盘代替约定产品行为。

### 3. 检查与原生验收

- [x] 使用任务隔离环境/小型合成资料完成实例、HTTP、CLI、托盘相关检查，再运行项目完整质量门禁一次。
- [x] Windows 目录包完成可自动执行的 AC 覆盖：重复打开、误关再开、不同资料、同步去重、页面/托盘消息退出、重启和崩溃恢复；AC4 的实际鼠标交互单列保留。
- [x] 目录包的可自动执行检查通过后构建并独立检查 OneFile；按一个服务、一份托盘验收，不按 bootloader PID 数，AC4 实际鼠标交互仍保留为未完成。
- [x] 真浏览器验证刷新、多标签、重开、项目和原包保留；手动同步经 HTTP 回归覆盖。原生消息验证托盘和 TaskbarCreated，未重启用户 Explorer。
- [ ] AC4 实际鼠标展开托盘菜单/点击：Computer Use 初始化被工具路径错误阻断，未以消息测试冒充物理交互。
- [x] 按 browser/computer 技能执行可用操作并尝试桌面初始化；Computer Use 失败的交互项如实保留，未拿 mock 或旧验收替代。
- [x] verification.md 记录版本、AC、端口/锁释放和文件摘要；私有 URL/Cookie/CSRF、原始截图和业务数据留 Git 外。

实施阶段建议命令（任务环境为 `.aha-data/single-instance-tray/venv`）：

```bash
.aha-data/single-instance-tray/venv/bin/python -m unittest discover -s tests -p 'test_instance*.py' -v
.aha-data/single-instance-tray/venv/bin/python -m unittest discover -s tests -p 'test_http*.py' -v
.aha-data/single-instance-tray/venv/bin/python -m unittest discover -s tests -v
.aha-data/single-instance-tray/venv/bin/python -m ruff check src tests scripts
.aha-data/single-instance-tray/venv/bin/python -m mypy src/aha
.aha-data/single-instance-tray/venv/bin/python -m compileall -q src/aha
node --check src/aha/web/app.js
```

Windows 用任务自有 `Scripts/python.exe`；SQLite 继续满足现有运行时门禁。新测试命名以实际实施为准，完整发现必须包含它们。不恢复已取消的大规模试验。

### 4. 规范与交付

- [x] 更新 README、后端运行/目录/输出和前端生命周期契约，记录单实例、托盘与复用规则，保留只在首次页面启动一次/手动同步的约束。
- [x] 检查代理复核完整代码差异、AC、并发与认证；主会话完成两种 Windows 成品检查并记录实测与未完成项。
- [ ] 通过后按 Phase 3 提交、归档和记录会话；代码或打包成功不等于原生验收通过。

## 回退边界

主要改动是入口、HTTP 生命周期、三个新增运行模块、资源/打包、测试与规范。Store/schema/核算/报销不作为改造对象。运行锁文件不能当作残留删除；回退前先退出程序并确认锁释放，不清理用户库、来源或材料目录。
