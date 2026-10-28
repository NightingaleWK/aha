# 合成规模验证原始结果

全部为seed20261028的合成Codex用量，不含用户CCS原件、实际报销或临时认证凭据。查询预热10/采样100，目标与失败处理见任务design第10节和verification。

## 查询和源窗口

- `linux-1m.json`、`windows-1m.json`：HTTP入口优化后(ff源码)的100次正式查询与数据层进程冷；原1m已显式新增10000，实际事实1010000。密度补丁前后无DDL变化，最终950版再测更大的千万库。
- `linux-1m-sync-export.json`：原始1m、10k窗口重复100次、增10000/修订1000及100156成员导出；早期查询已被上面的最终百万结果替代。
- `windows-1m-increment-export.json`：原始1m、10k窗口重复100次、增10000/修订10000与100156成员导出。其初期冷查询失败保留，不当作最终通过。
- `windows-1m-unchanged-20k.json`：当时增量后的20k完整窗口重复100次；后续最终Windows千万测试先通过正常API校准合成成本，使用同一20k/同projection SHA与此文件比较，禁止和10k分母混用。
- `linux-10m-concurrent-load.json`：ff源码、两个平台大I/O同时运行的完整结果；查询通过，10k窗口壁钟比1.847失败保留，比较阶段只有约1.06倍。新增10000/修订1000的并发查询也完整记录。
- `linux-10m-fixed-window-r4.json`：950源码、停止其他大I/O后针对失败项复测。先正常API还原1000合成成本、保留额外10000事实/所有版本，以独立合成profile观察同10k投影一次（均在计时外）。100次测量P50=1.599s/P95=2.022s、无新版本，与原百万同SHA比0.931；明确披露fixture准备差异。

## 结构、回归与材料

- `linux-10m-fixture-verification.json`、`linux-10m-seed-initial-failure.json`：旧长时间播种已完成表/索引后，最后参考调用混用新旧模块失败；保留原失败，最终新进程补派生后106行完整projection/真实业务链路通过，不重写为旧进程成功。
- `linux-10m-footprint.json`、`windows-1m-footprint.json`：dbstat物理结构。千万统计包含一次主动暂停，measurement_seconds不是性能指标；索引/版本等表字节和计数为基线实测。
- `check-density-vm-final.json`：真实Store的密集scope/背景候选/目标与owner回归工作量，配合150项双平台检查；VM验证不能代替原生规模实测。
- `benchmark-smoke-r4.json`：新增导出进度/中间结果落盘后的独立1000条CLI smoke，仅证明脚本可用。
- `windows-10m-100k-package-audit.json`：101066成员ZIP的独立流式复核，重构每条CSV的源内容指纹，与manifest逐条比较，并校验冻结SQL计数/摘要、每日合计及所有内部文件哈希/字节数。

最终状态：Windows最终950版的千万查询、20k同投影重复同步、并发及101066成员完整导出已完成；原始结果是`windows-10m-r4-user-stopped.json`中的已完成字段，完整十万包另有逐条复核。百万整包尚未完成发布/下载核对，用户于2026-10-28明确取消剩余大规模测试，记`waived_by_user`，不能记通过，也不再补跑。

`windows-million-stop-by-user.json`记录自有PID34196退出79；`space-guard-result.json`记录辅助守护退出；`released-windows-10m-result.json`记录仅清理自建夹具、WAL/临时文件及旧未登记包，C盘实际回收47233470464字节（约43.99GiB）。保留完成的十万包、小型原始指标与DDL，未删除用户CCS/历史资料。Linux千万夹具也已在保存指标后删除，不修改全局VHD策略。

实际OneFile旧ff版本的百万离线HTTP证据位于同级`acceptance/windows-onefile-1m-pre-density.json`；最终950版浏览器/Excel/A4及默认真实资料两次启动同步/退出、历史逐条对账和桌面交付摘要也位于同级acceptance/。完整结果和边界以[verification](../../verification.md)为准。

进程冷保留OS缓存，计时为新进程内Store打开、全5年分析和首50行，排除解释器导入；EXE启动/解包/认证单独测量。Linux是WSL ext4磁盘目录，Windows是原生Python/NTFS本地数据库；最初tmpfs预跑不作正式结果。不清宿主全局缓存、不改全局VHD策略。已完成合成库在保留原始指标、DDL和必要原ZIP后按任务marker/来源检查清理，不能将其当作用户资料处理。
