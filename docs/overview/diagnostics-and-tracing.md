# 查询失败时间线与技术追踪

当前 FX5 提供三层记录：任务历史回答业务状态发生了什么变化；diagnostics 回答消息投递和宿主唤醒在哪里失败；可选 OpenTelemetry 解释技术调用的因果与耗时。后两者不决定任务完成，也不把人工跟进变成自动唤醒成功。

## 查询与导出

在已初始化的项目目录执行，`project_id`、`task_id` 来自项目上下文或现有 `agent list`/任务查询结果。下面变量只表示这些已知业务 ID，不是 enrollment 要求用户填写的宿主 ID。

```powershell
$projectId = (Get-Content .tsunagou/project.json -Raw | ConvertFrom-Json).project_id
tsunagou project diagnostics $projectId --json
tsunagou project diagnostics $projectId --task-id $taskId --from '2026-09-28T00:00:00Z' --to '2026-09-29T00:00:00Z' --json |
  Set-Content -Encoding utf8 .\delivery-diagnostics.json
tsunagou task history $taskId --json
tsunagou project history $projectId --json
tsunagou project timings $projectId --task-id $taskId --json
```

对应 HTTP 为 `GET /api/v1/projects/{project_id}/diagnostics`，过滤参数是 `message_id`、`task_id`、`from`、`to`。HTTP 使用既有 U 或当前 Agent 的认证凭据；CLI 私下读取自己的控制凭据。过滤不会提高读取权限。

用户和 main 能看到脱敏的传输失败概况；私信 ID 仅向其发送者或接收者显示。非受众按该私信 ID 过滤得到空结果；可改按共享任务和时间查故障。Worker 不能查询其他 Worker 的私信或拒绝记录。共享 task.submit 的附带通知不会再隐藏提交事实，但明确引用私有 evidence 的事件仍按原权限整体验证。

| 字段 | 含义 |
| --- | --- |
| occurred_at | 已知源事实发生时间；无法证实则 null |
| recorded_at | daemon 写入诊断的时间；本轮较早记录缺失时仍为 null |
| observed_at | 实际读到宿主观测的时间；不冒充源发生时间 |
| trigger_source | daemon_delivery、user_followup、developer_followup 或 unknown；普通 inbox.presented 默认 unknown |
| command_id / task_id / attempt_id / message_id / wake_attempt_id | 已知且允许显示的关联；未知或不可见为 null |
| error_code | 机械失败类别，避免把异常正文、私信或配置抄入记录 |

所有公开时间统一为 `2026-09-28T00:00:00.000Z`。过滤可输入其他 RFC3339 时区，服务端转换为 UTC。普通查询不写领域事件或续期资源。处理消息或 ACK 不会把先前 failed/unknown 唤醒改为成功。

## 按 Attempt 查看流程经过时间

`tsunagou project timings $projectId --json` 自动读取完整 history 分页和公开 attempts/results；加 `--task-id $taskId` 只显示该任务的各次 Attempt。JSON 的 items 只含公开身份、状态、时间、来源、可见事件数和经过时间，不输出 payload、evidence 或私信引用。`state` 是本次读取的 Attempt 状态，开始、提交、审查分别保留自己的来源：

| 时间 | 来源 | 缺失与歧义 |
| --- | --- | --- |
| started_at | 可见 begin 事件 occurred_at；started_source=task_begin_event | 只认对应 Attempt 进入 running；不能把另一个 Attempt 的 begin 或 created_at 当开始 |
| submitted_at | 可见 submit 事件 occurred_at；submitted_source=task_submit_event。事件不可见时，可用唯一匹配 Result.created_at，来源为 result_created_at | 多个 Result、多个 submit 事件或两个来源时间冲突时为 null；不取 updated_at 或 Attempt.ended_at |
| reviewed_at | 明确关联该 Attempt/Result 的可见 review 事件 occurred_at；reviewed_source=task_review_event | 不按同一任务的最近提交猜测；缺失或多个审查事件时为 null |

Result.created_at 是服务器在原提交事务中记录的 Result 创建时间，与该事务事件使用同一计时口径；它不测量实际 COMMIT/fsync 完成瞬间。显式私信证据会继续隐藏整条 submit 审计事件，但独立公开 Result 仍可提供这个时间。因此 `submit_events=0`、`submitted_source=result_created_at` 是有效结果，不意味着已读取到私信或 submit 事件。单事件查询、history 和 export 保留原权限。

`work_elapsed` 是 started_at 到 submitted_at 的流程经过时间，`review_wait_elapsed` 是提交到审查的等待时间；两者包含 elapsed_ms 和 clock_status。缺失或歧义为 null/unknown，终点早于起点为 null/clock_inconsistent，正常为非负毫秒/ok。保留各 Attempt 的独立区间，不把并行 Worker 的经过时间相加当项目总工期，也不称为纯编码时间。重复只读、幂等提交重放和同库重启保持原 Result 时间。三个 HTTP 查询不是跨请求原子快照；运行中的新阶段可能在下一次查询才齐全。

## 可选本机 OpenTelemetry

追踪默认关闭。下面使用已安装源码路径 `$sourceRoot`，无需在业务仓库复制源码。先按安装记录核对该路径。测试接收器属于开发验收工具，关掉它不影响任务或持久化。

```powershell
# 在没有其他安装/测试正在修改该环境时补充可选依赖。
uv sync --project $sourceRoot --locked --extra telemetry --inexact
# 终端一：实际接收 SDK 发出的 OTLP protobuf；Ctrl+C 结束。
uv run --project $sourceRoot --no-sync python "$sourceRoot/tools/dev/collect_acceptance_trace.py" `
  --output '.\acceptance-spans.jsonl' --port 4318
# 终端二：仅新启动的 daemon 读取此环境；已有 daemon 需按其正常停止/启动流程重启。
$env:TSUNAGOU_OTEL_ENDPOINT = 'http://127.0.0.1:4318/v1/traces'
tsunagou daemon start
```

接收器文件包含实际 SDK span 的 trace_id、span_id、parent_span_id、起止时间、duration_ms、业务关联和状态。仅有五个埋点：command.execute、a2a.submit、outbox.deliver、host.wake、onboarding.restore；不记录完整 HTTP、prompt、文件内容或每次查询。outbox 通过同事务的 event_seq 找回 traceparent，不新增协调数据库。

当前 SDK 锁定为 1.45.0。只允许 localhost/loopback 的 HTTP OTLP 端点；导出失败不回滚业务提交。日志边界记录带 trace_id/span_id；SDK 默认异常正文记录已关闭。token_usage 为 unavailable，不能当 0。span 的技术耗时、任务开始到提交的流程经过时间和并行项目总工期是三种不同指标，不能相互替代。

采用的 SDK 接口见 [官方手工埋点](https://opentelemetry.io/docs/languages/python/instrumentation/)及[官方 OTLP exporter](https://opentelemetry.io/docs/languages/python/exporters/)。真实原 Desktop 的完整验收另记录于 FX3/FX6；本机接收器测试本身不证明 LLM 已收到或执行任务。
