# CCS25与换机接续核心实施记录

日期：2026-11-12。执行者：source_recovery（trellis-implement）。仅使用合成资料；未打开真实CCS/aha库，未写真实本机安装标识，未提交Git。

## 改动边界与结果

- `src/aha/domain.py`：外部支持23/24/25，内部投影仍23。
- 新增`src/aha/source_bindings.py`；`storage.py`仅增两个绑定门面。安装UUID存账本外本机私有设置；settings的`source_bindings_v1`为有格式版本、条目/字节上限的绑定记录。当前设备、规范化来源路径和`restore-info.json`的restore_id共同绑定来源实例，不重写消费key/冻结成员。
- 有旧SQLite profile或恢复标记且缺少当前绑定时，`sync_sqlite`在创建run前返回`source_binding_required`；旧事实不挂pending。完全首次接入SQLite、此前仅SQL历史时可安全建立独立新来源；与SQL历史差值仍保留候选。
- 绑定前独立恢复过期/已知失败run，再拒绝未过期竞争run；原有有限同步、双取消、两阶段预算和失败清理不变。
- `sync.py`：异源同key不同内容保留revision；确认缩水来源不隐式批准开放revision；用户显式保留当前值后重复同步仍保留决定，兼容旧审计事件。跨来源同值日汇总也须`rollup_origin`核对，避免把数值相同当成员范围相同。
- `_save_metadata`：本机未找到日志不抹掉已保存matched cwd；真实不同/冲突依据保留版本并产生`directory`候选，原目录及项目仍可使用。等价Windows路径不制造冲突。
- `ledger.py`：directory核对支持保留原值/采用唯一候选；采用候选后使其他旧依据事项superseded，迟到确认被generation/state阻断。rollup_origin仅确认来源重叠后保留既有汇总，不自动相加，也不误确认source epoch。
- 测试扩展23→24→25内容/身份/占用/原包保持及26拒绝；原先“来源确认后自动接受100→10汇总”的断言改为必须单独核对事实。

## 提供给HTTP/UI的接口

```python
Store.source_binding_status(path, *, installation_id=None)
Store.bind_source(path, reason, *, installation_id=None)
Store.sync_sqlite(path, ..., installation_id=None)
```

`installation_id`是测试/受控调用注入参数，正常产品由模块的`installation_id()`读取本机UUID；HTTP不接收任意设备ID。

状态字段：`required`、`bound`、`has_history`、安全`source_name`、`source_id`、`reason`、`confirmed_at`。不返回安装UUID或来源绝对路径。错误包括`source_binding_required`、`source_binding_damaged`、`device_identity_unavailable`、`source_binding_limit`、已有`sync_in_progress`。

directory开放事项含session_id/current_cwd/candidate_cwd/candidate_status；唯一新目录时choices=current/candidate，仅冲突时只能current。rollup_origin含date/model/request_count，仅current。UI代理已获接口和文案信息。

## 实际验证

Windows隔离QA：Python3.12.16 / SQLite3.53.1，任务`qa312`；使用父任务`run-native.py`，USERPROFILE/LOCALAPPDATA/TEMP等均隔离。相关测试另显式patch安装ID，普通测试执行也不依赖用户标识文件。

| 检查 | 实际结果 |
| --- | --- |
| test_device_continuity | 14项通过，含同路径新机、空源、已有占用/原包、较小/相同汇总、恢复标记、坏/深层JSON、目录候选/冲突/迟到确认 |
| test_storage | 29项通过 |
| test_sources | 26项通过 |
| test_sync_timeout | 14项通过；首次发现绑定妨碍过期租约恢复，修复后整组通过 |
| test_http | 16项通过，包含SQL23/24/25及SQLite25、未知26旧资料仍可查 |
| test_evidence | 6项通过，外部25仍输出内部投影23/manifest4 |
| test_projects | 6项通过，未改该测试文件 |
| Ruff（所辖生产/测试文件） | 通过 |
| strict mypy（source_bindings/sync/ledger） | 通过，独立mypy-source缓存 |
| git diff --check | 通过 |

全量集成检查、真实浏览器、真源/真库接续与Windows成品由父任务负责；此记录不将它们计作子代理已执行。

## 剩余边界

- 不增加schema，不给旧来源推断真实设备身份；完整备份保留DB中的历史绑定证据，通过新restore_id使机器授权失效。
- 本期只做单向换机；独立多设备同日日汇总不能直接相加，候选保留供核对。
- 主会话核实Codex MSIX可能对新AppData目录虚拟化；由主会话通过Explorer/Shell启动最终成品，验证其日常运行身份与物理资料位置。测试主机的UUID不能代替正常用户启动所用UUID，本模块不硬编码MSIX路径。
