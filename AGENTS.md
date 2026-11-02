<!-- TRELLIS:START -->
# Trellis Instructions

These instructions are for AI assistants working in this project.

This project is managed by Trellis. The working knowledge you need lives under `.trellis/`:

- `.trellis/workflow.md` — development phases, when to create tasks, skill routing
- `.trellis/spec/` — package- and layer-scoped coding guidelines (read before writing code in a given layer)
- `.trellis/workspace/` — per-developer journals and session traces
- `.trellis/tasks/` — active and archived tasks (PRDs, research, jsonl context)

If a Trellis command is available on your platform (e.g. `/trellis:finish-work`, `/trellis:continue`), prefer it over manual steps. Not every platform exposes every command.

If you're using Codex or another agent-capable tool, additional project-scoped helpers may live in:
- `.agents/skills/` — reusable Trellis skills
- `.codex/agents/` — optional custom subagents

Managed by Trellis. Edits outside this block are preserved; edits inside may be overwritten by a future `trellis update`.

<!-- TRELLIS:END -->

## 项目交付与收尾约定

以下是用户确认的项目长期要求，放在 Trellis 管理块之外。新会话开始及宣布工作完成前，阅读 [交付与临时文件清理规范](.trellis/spec/backend/delivery-and-cleanup.md)。

- aha 的 Windows 功能实施默认交付可直接使用、与最终源码一致的单文件 EXE，放到用户实际桌面并验证；提交代码、归档任务后仍须完成已授权的成品交付。用户明确限定为设计、评审或仅源码时遵守其范围。
- 收尾主动清理自己创建且已确认不再使用的合成大库、任务专用虚拟环境、构建中间件和缓存。先核实归属与运行占用；保留真实资料、源码、主开发环境、必要验收记录和最终成品，不能按 `.gitignore` 批量删除。
- WSL 中的交互 HTML 使用本机 HTTP 服务和应用内浏览器呈现，提供当次验证过的可点击 URL。不要继续使用已失败的内联可视化路径；打开请求返回 queued 时只说明已排队。
- 时间、统计、保存与材料共用 [时间合同](.trellis/spec/backend/time-range-contract.md)；表单动态值、键盘/焦点及迟到请求遵循 [组件](.trellis/spec/frontend/component-guidelines.md) 和 [状态规范](.trellis/spec/frontend/state-management.md)，不能只验外观或成功路径。
- 版本与 GitHub 发布遵循 [版本发布合同](.trellis/spec/backend/release-contract.md)。每项用户可感知的功能/修复随代码提供中文 What’s New 片段，由开发代理按实际改动编写；版本由发布 PR 统一递增，不手工在多处改数字。首次全面本机验收，以后每版自动检查，涉及托盘、Excel、打印或构建环境变化时追加相应专项；没有实际执行的检查不能写成通过。
- 每项工作收尾时主动给出发版评估：本次是否值得单独发布、相对最近公开版本的累计待发内容、建议版本与原因、What’s New预览及验收缺口。先完成已授权的实施、检查和本机交付，再集中引导用户选择“现在发版”“积累到下一版”或“本次无需单独发版”；存在缺口时把第一项改为“先补齐发版条件”。明确推荐项并记录选择，未回复不等于同意；已有明确覆盖本次发布的授权不重复询问。具体流程与示例见发布合同和 [维护说明](docs/RELEASING.md)。
- 复用用户已明确给出的授权，不重复确认同一事项。需要确认的流程节点集中提出，执行结果按实际证据说明；新的用户指令优先于本地默认约定。
