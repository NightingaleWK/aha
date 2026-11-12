# 本次Windows环境与验收入口

- CPython 3.12.16 x64、SQLite 3.53.1，均实际原生探测；满足项目SQLite修复门禁。
- 任务根：`C:\Users\djsyw\AppData\Local\Temp\aha-device-continuity-20261112`，有task-ownership.json归属标记。qa312为本任务隔离环境；不改主环境。
- 固定开发依赖与项目editable已安装；Playwright1.65.1、pywin32 312、pypdf7.0.1为QA工具，不作为产品依赖。
- 初试CPython3.15.2环境因固定zstandard0.25.0没有对应wheel且本机无MSVC编译链而失败；已切换上述满足门禁且有wheel的3.12.16。qa目录为可清理的失败任务环境，不降低依赖或SQLite要求。
- run-native.py以原生外层解释器启动qa312，捕获child输出；从WSL直接PowerShell调用venv时可能丢失child执行/输出，测试以runner的真实returncode为准。
- Windows原生目录能确认持久备份存在，WSL DrvFS目录视图未显示新目录，所有成品/真实资料校验以Windows原生接口为准。
- 实施前D:\Program Files\aha.exe SHA256=0c25c25da9df56f7b82e7fe4cbce9f20613e1e82172c2ac9b620c2b77b0e8f58；桌面接口返回C:\Users\djsyw\Desktop；当次无运行aha进程、无桌面同名exe。
- Excel注册路径存在：C:\Program Files\Microsoft Office\Root\Office16\EXCEL.EXE（不等同本轮专项通过）。原生Edge和Chrome存在。
- 已按computer-use技能读完整指导/确认规则，初始化、重试、reset后再试均被宿主sandboxCwd URI校验阻断：`sandboxCwd is not a local file URI: file:///home/wangkai/code/aha`。没有发出UI输入，不能据此声称物理点击通过。页面/Office可继续采用原生Edge Playwright、Excel COM与A4PDF验证，物理托盘缺口分别报告。
