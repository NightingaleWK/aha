# 时间范围与旧材料兼容核查

核查日期：2026-10-29。仅检查现有源码与测试，没有执行迁移或读写个人业务资料；以下事实支撑设计，技术决定以 [design.md](../design.md) 为准。

## 已核实的存储与读取事实

- `src/aha/batches.py:80`：revisions 的 analysis_json 已保存分析对象，新增范围/完整性元数据不需要改表结构；不可变触发器在 `src/aha/batches.py:120` 禁止原记录事实更新。
- `src/aha/batches.py:321`：frozen 修订按 revision_members.frozen_json 读取原成员，不需要重新按当前事实筛选。
- `src/aha/server.py:291`、`src/aha/server.py:312`：仅改用途时从当前有效修订的 analysis 深复制，再加冻结主体；新的兼容补全不能改写旧记录。
- `src/aha/batches.py:429`：当前冻结依据比较只列出日期、项目和摘要；新范围比较须统一规范化后比对，避免旧记录缺字段与新记录有字段被误判。
- `src/aha/batches.py:552`：冻结分析的字段白名单会丢弃未列出的字段，包括原分析中的 summary_complete/pending_count。旧冻结记录不能假定已经保存完整性布尔值；不得从当前资料或文案字符串倒推旧记录的完整性。

## 两种 selection_hash 不能混为一谈

- `src/aha/queries.py:416` 的 analysis.selection_hash 是查询条件/版本身份，绑定精确区间后可防止同日不同时间的游标互用。
- `src/aha/batches.py:398`、`src/aha/batches.py:549` 的冻结 selection_hash 是按成员内容生成的流式摘要，旧冻结修订用它核实原成员。增加时间范围不能改变这套成员摘要算法。
- `src/aha/batches.py:736` 的 business_hash 另行绑定成员摘要、用途和筛选信息；规范化时间身份应加入这里，不应靠修改成员摘要算法达到目的。

## 现有材料的兼容边界

- `src/aha/evidence.py:24`、`src/aha/evidence.py:418`：当前新包写 manifest_version=3，selection 只有日期、时区与项目。
- `src/aha/evidence.py:367`、`src/aha/evidence.py:395`：材料 writer 按 metadata 流式输出；新范围/完整性可作为结构化元数据，同时保持四文件形式与分块成员输出。
- 对 src/aha 全量搜索，manifest_version 的使用仅在 evidence writer 中，没有生产代码通过“必须等于 3”解码旧材料后重建的路径。
- `src/aha/batches.py:1085`：下载按 revisions 中既存 zip_path、zip_hash 与 file_name 校验后返回原文件；不解析 manifest、不调用 builder。
- `tests/test_evidence.py:54` 是现有新包版本 3 的断言；新包版本变动需更新新建包预期，同时新增真实旧版本 3 原包回归，不能把所有测试一改成新版本后声称旧包兼容。
- `tests/test_batches.py:79`、`tests/test_batches.py:106` 和 `tests/test_http.py:296` 已有原包不变、原分类/原费用冻结修订的测试入口，可复用扩展。

## 可以确定的设计结论

应用库保持 schema3；新生成材料使用 manifest4 清楚表达时间范围和完整性。旧版本 3 ZIP 原字节重下；对旧冻结记录仅在内存补出原整天区间，缺少的历史完整性标志使用未知值，不能重新判断成完整或按新来源扩张成员。
