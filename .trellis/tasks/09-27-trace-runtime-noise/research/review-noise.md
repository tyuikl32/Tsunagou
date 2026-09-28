# PT6 运行噪声与唤醒证据复核

- reviewed_at: 2026-09-28T01:48:27Z
- reviewer: tyuikl32 / Codex

## 分层结论

领域事实继续写入 SQLite events/module state：任务、Attempt、消息、认知、契约、权限、workspace、checkpoint 和恢复。宿主 wake、A2A callback、thread/turn 状态和 Agent presentation 属于传输诊断，写入 `.tsunagou/local/diagnostic-events.json`，不推进 domain revision、entity time 或 checkpoint watermark。

`WakeDispatcher` 以 `(agent_id, message_id)` 作为 delivery 幂等键。重复 `on_delivery` 直接返回原记录，不重复宿主 turn 或诊断记录；进程重启把原 running wake 标为 `unknown`，并留下一个带原 wake/message 关联的诊断事实，后续 retry 才可启动新的 attempt。

## 证据类型

- `wake_requested`: daemon 已请求宿主适配器。
- `callback_received`: A2A push callback 的 HTTP 结果已观察；不代表 Agent 开始 turn。
- `thread_started`/`thread_resumed`: 宿主 thread 操作已观察。
- `turn_started`/`turn_completed`: 宿主 turn 生命周期已观察；仅这些证据能说明宿主实际开始/结束 turn。
- `agent_presented`: Agent 通过 `inbox.presented` 报告读取/呈现了消息；不等同于 turn completion。
- `wake_unknown`/`wake_failed`: 诊断状态不可观察或明确失败；durable inbox pull 仍是恢复路径。

每条记录带 `diagnostic_id`、`project_id`、`agent_id`、`message_id`、`wake_attempt_id`、时间、evidence digest 和白名单 details；不保存宿主原始 thread、prompt、token、callback credential 或文件绝对路径。

## 查询

`GET /api/v1/projects/{project_id}/diagnostics` 和 `tsunagou project diagnostics <project_id>` 只读该诊断投影。`project history`/`task history` 仍只返回领域 AuditPage；调用者需要同时查看 diagnostics 才能判断 delivery、wake、presentation 和 turn 的分层状态。

## 保留边界

现有 reconnect、wake-attempt 和旧 audit 行不删除、不改写；新修复继续创建新 task/result，并以已有 `caused_by_command_id`、subject 和 evidence 引用关联，不把新事实追补进旧验收记录。
