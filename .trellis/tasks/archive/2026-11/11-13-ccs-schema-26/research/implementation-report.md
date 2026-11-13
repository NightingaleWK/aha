# 实施报告：CCS 26 兼容

## 修改边界

唯一产品源码变化是 `src/aha/domain.py` 的外部白名单从 `(23,24,25)` 扩为 `(23,24,25,26)`。SQLite、SQL及同步结果复用已有验证器；内部投影23、应用schema4及材料协议不变。

## 已修改文件

- `src/aha/domain.py`：显式支持外部26，错误提示自动沿用共同集合。
- `tests/test_sources.py`：SQL注释/字面量PRAGMA兼容26，0/1/2 Token语义跨版本投影一致；26 WAL只读及SQL/SQLite一致性；三张允许表跨23→24→25→26指纹/身份稳定；未知27、假/混合声明及26缺列/缺表/错误数值继续拒绝。
- `tests/test_storage.py`：升级链扩到26，保留归属、占用、事实/内容版本、重启元数据和原包SHA；SQL26错误/未知27失败不发布暂存或推进成功时间。
- `tests/test_http.py`：SQL四版本job/ledger真实版本；默认26来源的startup及手动重复同步；未知27失败后旧成功时间、本地查询和来源版本保留。
- `tests/test_evidence.py`：用外部26验证内部23和manifest4作用域。
- `scripts/verify_windows_artifact.py`：实际验证四版本、SQL26、27失败/26恢复、ledger版本及重新启动26同步；独立还原后重复同步预期改为26，scope与实际操作一致。
- `.release/changes/ccs26-compatibility.json`：中文fix片段，不手改产品版本。

## 实际检查

- Python AST解析：上述6个Python文件通过。
- 中文变更JSON解析：通过。
- `git diff --check`：通过。
- 使用主会话准备的任务自有Windows x64 CPython3.15.2 / SQLite3.53.4，经 `research/run-native.py` 为每项检查隔离合成profile和缓存：

| 检查 | 实际结果 | 证据 |
| --- | --- | --- |
| `unittest discover -s tests -p test_sources.py -v` | 26个测试通过 | `implement-sources.log` / `implement-sources-result.json` |
| `unittest discover -s tests -p test_storage.py -v` | 29个测试通过 | `implement-storage.log` / `implement-storage-result.json` |
| `unittest discover -s tests -p test_http.py -v` | 18个测试通过 | `implement-http.log` / `implement-http-result.json` |
| `unittest discover -s tests -p test_evidence.py -v` | 6个测试通过 | `implement-evidence.log` / `implement-evidence-result.json` |
| `ruff check src tests scripts` | 通过 | `implement-ruff.log` / `implement-ruff-result.json` |
| `mypy src/aha`（strict配置） | 26个源码文件无问题 | `implement-mypy.log` / `implement-mypy-result.json` |

- 针对性回归共79个测试通过。最终全量suite及release检查由独立检查代理执行，本实施代理不重复全套。
- Windows Directory/OneFile/桌面成品及真实来源只读投影：主会话负责，本报告不代替原生验收。

## 保留边界

没有修改sources/sql_dump/sync等其他生产模块，没有写真实CCS/aha资料，没有提交Git。README、spec、任务主文档和原生成品由主会话负责。
