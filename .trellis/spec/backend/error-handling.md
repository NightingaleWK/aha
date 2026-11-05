# 错误处理

## 公开形状

AppError(code,message,status=400) 由 domain 定义，HTTP 返回安全JSON。message使用简体中文，不能拼接str(exc)、SQL、原路径、正文、凭证或traceback。具体状态矩阵见 [主契约](./usage-evidence-contract.md)。

## 所有者

- sources/sql_dump 在读取/解析边界转换错误；原 AppError 保留。busy、超时和取消不是空数据。
- Store事务对所有异常回滚，locked/busy转store_busy，其他写入错误转storage_write_failed；不能捕获后继续提交。
- sync记录failed/cancelled/needs_review等有限结束，旧可见数据和最近成功时间保持；HTTP worker与UI必须认识needs_review，不能误标成功或无限轮询。
- SQLite源读取预算与本地回放/暂存预算分离：前者超时为source_busy，后者为sync_processing_timeout；临时投影的本地I/O失败不得被sources误归因为源读取错误。临时文件及时清理，本地库被占用而无法持久清理staging时以有界失败和精确恢复处理，不能吞错后永久留下running；具体矩阵见[两阶段合同](./database-guidelines.md#sqlite-同步两阶段合同)。
- 资料/原包损坏时明确拒绝读取，不重建掩盖，不清空占用求通过。
- HTTP异常终止响应但不打印原始细节；错误同时进入当前弹窗及持续可见反馈，数据/归属/claim失效清主预览与current修订。

## 示例与验证

```python
# 错误：把读取失败变成零用量。
except OSError:
    return {"details": []}

# 正确：保留失败并让调用方继续显示已发布本地资料。
except OSError as exc:
    raise AppError("source_unavailable", "无法读取来源，请稍后重试。") from exc
```

验证错误后的事实、占用、成功时间和文件，不能只断言状态码。生产读取/发布/下载与进程并发各自验证；数据文件缺失与业务候选待核对是不同情形。
