# A2A 边界实现

Tsunagou 的初版设计要求 Agent 之间可以通过 A2A 交换澄清、依赖询问、设计异议、变更通知、冲突协商和验证结果。当前代码已经提供一个本机、同步的 A2A JSON-RPC 边界；MCP bridge 仍是 Coding Agent 连接 daemon 的工具入口，不能把 MCP tools 目录称作 A2A 实现。

## 1. 端点和发现

真实 daemon 通过 loopback HTTP 提供：

| 方法 | 路径 | 作用 |
|---|---|---|
| `GET` | `/.well-known/agent-card.json` | 返回无秘密的 Agent Card |
| `POST` | `/api/v1/a2a` | 接受通用 JSON-RPC A2A 请求；收件人写在 `metadata.tsunagou.recipient_agent_id` |
| `POST` | `/api/v1/a2a/agents/{recipient_agent_id}` | 接受路由到指定 Agent 的 JSON-RPC A2A 请求 |

Agent Card 当前声明：

- `protocolVersion=1.0`、`protocolBinding=JSONRPC`；
- skill `agent-coordination`，覆盖消息发送、任务进度查询和受授权的任务状态转换；
- `streaming=false`、`pushNotifications=false`、`stateTransitionHistory=false`；
- `x-tsunagou.wake=unsupported`，`delivery=durable-pull-or-client-poll`。

这些值是能力声明，不是占位符。generic Codex bridge 没有经过验证的反向唤醒 API，因此 daemon 不会把 inbox 写入误报为唤醒对话。消息先持久化为内部 Delivery，目标 Agent 下次 pull/fetch 或客户端轮询时可见。

## 2. 认证和内部真相

每个 A2A 请求都必须使用已 ready 的 Agent session：

```text
Authorization: Bearer <当前 bridge 的 session token>
Tsunagou-Session-Id: <当前 session id>
Tsunagou-Connection-Epoch: <当前连接代次>
```

daemon 通过现有 `LocalCommandAuthenticator` 得到 principal，再把写入交给 `CommandDispatcher` 的 `message.send`；不会信任 A2A body 中的 `sender`、`authority`、`owner` 或自报 Agent ID。项目范围、agent grant、session 状态、connection epoch、命令注册表和幂等规则沿用 HTTP/MCP 路径。

Project、Task、Attempt、Grant、Lease、Contract、Operation 和事件历史仍是唯一事实源。A2A `contextId`、`messageId` 和 `taskId` 是边界关联值：

- `contextId` 写入内部消息的 `subject_ref` 默认值，并在返回消息中原样保留；
- 外部 `messageId` 变成 `a2a:message:<messageId>` 的内部 command id，同一主体重试只产生一次内部消息；
- `tsunagou:task:<id>` 映射到 query provider 返回的内部 task；
- 原始 A2A message、parts、metadata 保存在内部消息 payload 的 `a2a` 区域，便于审计和后续扩展；
- 当前最小 profile 只要求文本 Part。非文本 Part 不作为摘要参与路由，但会保留在 `a2a.parts`；二进制 Artifact 的上传、读取和权限仍使用 Tsunagou artifact 端口，未在首版 A2A 路由中声明为独立传输能力。

## 3. 支持的方法

### `message/send`

消息至少需要一个带 `text` 的 Part。收件人可以由路由路径指定，也可以由 Tsunagou metadata 指定：

```json
{
  "jsonrpc": "2.0",
  "id": "rpc-1",
  "method": "message/send",
  "params": {
    "message": {
      "messageId": "review-request-1",
      "contextId": "task-123",
      "role": "agent",
      "parts": [{"text": "请先检查当前契约和接口边界。"}],
      "metadata": {
        "tsunagou": {
          "recipient_agent_id": "AGENT_ID",
          "kind": "request",
          "subject_ref": "task:task-123",
          "priority": 1,
          "payload": {"request": "contract-review"}
        }
      }
    }
  }
}
```

成功返回的 `result.message.metadata.tsunagou` 会说明内部消息 ID、`delivery=pending` 和 `wake=unsupported`。它表示 daemon 已接受并持久化，不表示目标宿主已经阅读或继续执行。响应 Agent 只需要使用自己的 session 再发送一条 `message/send`，并在 metadata 中设置 `in_reply_to`；消息 ACK、业务响应和契约接受仍是不同内部动作。

### `tasks/get`

`tasks/get` 读取内部任务的当前可见快照：

```json
{
  "jsonrpc": "2.0",
  "id": "rpc-2",
  "method": "tasks/get",
  "params": {"id": "tsunagou:task:task-123"}
}
```

内部状态映射为 A2A `TaskStatus.state`：`draft/ready/open/claimed -> submitted`，执行中状态 -> `working`，`blocked/input_required -> input-required`，`completed/accepted -> completed`，`failed -> failed`，`cancelled/canceled -> canceled`。返回 metadata 中的 `source_digest` 用于判断快照是否变化；它不是可用于覆盖内部 revision 的客户端版本号。

### `tasks/cancel`、`tasks/fail`、`tasks/retry`

任务状态转换也经过同一内部 command dispatcher：

- `tasks/cancel` 要求 A2A session 同时拥有主 Agent authority，映射到 `task.cancel_request`，只记录取消请求，不直接删除或强制结束 Attempt；
- `tasks/fail` 由当前执行 Agent 携带 `attemptId` 和停止证据，映射到 `task.fail`，内部仍检查 Attempt owner 和执行授权；
- `tasks/retry` 是 Tsunagou 扩展，要求主 Agent authority，携带 `attemptId`，映射到 `task.recover` 的 `reopen` disposition；
- 三个方法的返回值都是带 `transition` 和内部 revision 的 A2A Task 投影。重复 JSON-RPC request ID 使用同一内部 command id，改变语义会触发幂等冲突。

`message/stream`、`tasks/resubscribe` 和推送端点仍未实现。没有真实 receiver 或 host wake API 时，取消/失败/重试也不会自动启动新一轮 LLM；目标 Agent 通过 inbox/`tasks/get` 看到持久状态。项目显式开启 multi-agent auto-wake 后，新 `coordination.plan` 会保留 WakeAttempt，并要求 host acceptance 与 worker.ready 两层 evidence；未验证的 Codex App Server transport 仍导出 `wake=unsupported`。

## 4. 错误、重试和恢复

当前端点返回 HTTP JSON 文档中的 JSON-RPC 结果；业务拒绝放在 `error.data.code`，例如 `authentication_failed`、`capability_denied`、`project_scope_denied`、`idempotency_conflict`、`task_not_found` 和 `a2a_method_not_supported`。客户端应按 code 处理，不把“HTTP 200 且有 error”误判为业务成功。

`messageId` 是外部重试幂等键的一部分。相同 session、收件人、消息语义和 `messageId` 重试会重放相同内部消息结果；改变正文而复用 ID 必须由内部 dispatcher 的幂等检查拒绝。daemon 重启后，内部消息仍在项目持久化目录中，目标 Agent 通过 pull/fetch 恢复；A2A 层不启动新的 LLM 对话。

## 5. 运行验证

从项目环境启动 loopback daemon 后，可以先发现能力：

```powershell
$card = Invoke-RestMethod "$baseUrl/.well-known/agent-card.json"
$card | ConvertTo-Json -Depth 10
```

调试时使用当前 bridge 的私有 session 凭据，不要使用 `control.token`：

```powershell
$headers = @{
  Authorization = "Bearer $agentToken"
  "Tsunagou-Session-Id" = $sessionId
  "Tsunagou-Connection-Epoch" = "$connectionEpoch"
}
$body = Get-Content tests/fixtures/a2a/message-send.json -Raw
Invoke-RestMethod "$baseUrl/api/v1/a2a/agents/$recipientAgentId" `
  -Method Post -Headers $headers -ContentType 'application/json' -Body $body
```

验收必须分别记录：daemon 接收并持久化（delivery）、目标 Agent pull/fetch（presentation）以及宿主是否真的开始新一轮（host wake）。没有宿主证据时最后一项必须是 `unsupported` 或 `unknown`。

官方概念和字段背景：[A2A specification](https://a2a-protocol.org/latest/specification/)、[A2A and MCP](https://a2a-protocol.org/latest/topics/a2a-and-mcp/)、[Life of a task](https://a2a-protocol.org/latest/topics/life-of-a-task/)。
