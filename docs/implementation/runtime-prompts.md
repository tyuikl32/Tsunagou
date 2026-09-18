# 黑板、上下文注入与运行提示

## 一致读结构

`GET P/blackboard?task_id=<optional>&after_seq=<optional>` 返回 BlackboardSnapshot：project_id、lineage_id、runtime_epoch、snapshot_event_seq、generated_at；self 的 agent/session/connection/role/grant_summary；authority；以及 sections。

sections 固定包括 objective、assigned_tasks、task_dependencies、active_blockers、user_decisions、discrepancies、contracts、workspace_summary、inbox_summary、response_obligations、pending_operations。每项 `{revision,items,truncated,next_query}`。一次 SQLite read transaction 通过各模块 query ports 取一致快照，没有独立黑板业务表。

每 section 默认最多20项、摘要合计64KiB；先按 self/选中 task 关联度，再 severity、创建顺序。超限明确 truncated 和详情 query，不能静默裁掉身份/阻塞。after_seq 只标注变化，仍返回当前有界 snapshot，不承诺全事件 replay。

普通 Agent 的 user_decisions 仅相关阻塞摘要；全文给 main/user。inbox 仅 self。绝对路径/ceiling/敏感 evidence 遵守源模块授权；组合查询不能扩权。

## 注入时机

核心维护 `protocol/prompts/v1/` 的 host-neutral 文本与 manifest digest，片段为 identity、responsibility、runtime_principles、blockers、coordination_tools。attach/resume/task 边界注入最小包：身份与代次、项目目标、当前 Task/Attempt、相关 blocker、水位、详情查询入口。历史和正文按需工具获取。

HostSession 保存 template version/digest。adapter 只格式转换和预算裁剪；身份、权限、当前阻塞、查询入口不可裁剪。预算不足先移除可选摘要，仍不足则诊断，不能漏约束继续运行。

模板必须表达：你代表哪个 Agent，Full Access 不扩大协调授权；以当前黑板事实为准；主动公开相关理解/假设/不确定性；只接受核对过的契约版本；上游阻塞时保存进度并挂起相关工作，无关任务可继续；resume 不等于 start；ACK 不等于接受；Git 写由 main，重大设计/项目完成由用户确认。

不索取隐藏思维链，不将消息正文拼入系统权限片段，不允许外部文本改写身份。自然语言约束是 advisory，API 仍做机械校验。

## 用户交互

main 在对话中解释重大决定、选项和建议，创建 UserDecision 后提供 ID、摘要与 CLI 入口。用户经 control 提交 exact revision/digest，任意时间回复都合法。首发不以宿主 user-role 证明完成审批。

main 负责展示 pending decisions；CLI `decision list/show` 是可靠入口，无桌面通知中心。普通可授权选择由 main 处理，不把每个技术参数都变成用户问题。

## 验收

同一 read snapshot 不跨版本拼接；私信与敏感字段在所有 section 过滤；截断可追踪；四 adapter 保留必需模板内容；resume 不注入旧 epoch；已 fetch 消息不反复灌入；blocked 与无关 running 共存；无 wake 仍可恢复查询。
