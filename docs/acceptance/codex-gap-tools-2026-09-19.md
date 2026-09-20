# 五项缺口能力补齐记录：2026-09-19（elysia，协同验收人员 elysia080928）

本记录是 [Codex 独立复验](codex-independent-2026-09-19.md)定位的五项**宿主无关**缺口能力的**补齐与隔离 HTTP 复测**，不是首发发布验收。只改产品源码、协议 Schema、bridge 工具与测试，**未 commit / push / release**（`081116d` 由仓库所有者另行提交），未改动 `release_check.py` 判定，未把单测/HTTP 证据写成真实宿主证据。

- 仓库分支 `elysia`，HEAD `081116d`（`five-codex-shixiangceshi-1`）。
- 补齐依据：[Codex 独立复验报告](codex-independent-2026-09-19.md)与 [三缺陷修复记录](codex-fixes-2026-09-19.md)的「剩余阻断与最小补证」。

## 五项缺口与补齐（均为后端 / bridge 层，不依赖真实宿主）

### 1. `command.typed_tools` —— 额外字段与 forged actor 拒绝

- **根因**：dispatcher 不核对 payload 字段，未知键（含 `actor_id` 伪造身份）会直接进入 handler；registry 的 `payload_fields` 又因 codegen 对转义竖线解析不可靠而不可信。
- **修复**（`src/tsunagou/interfaces/runtime.py`）：新增手工维护的 `PAYLOAD_FIELDS`（覆盖全部 24 个 handler 命令的合法字段），dispatch 前对 `envelope["payload"]` 做未知字段校验，任何未知键抛 `ValueError("unknown_payload_field")`（HTTP 400）。handler 上下文新增 `command_id`，使去重与身份绑定不再依赖调用者自报 actor。
- **范围说明**：本条是「未知字段即拒绝」的 typed-tool 契约；真实 Codex 经 MCP 传参是否只含合法字段，仍需真实宿主复验。

### 2. `context.project_read` —— 项目 / 任务 / scope 查询工具

- **根因**：原工具只有目录名 digest，没有项目 ID、任务与 worker scope 查询语义。
- **修复**：
  - `src/tsunagou/application/handlers.py`：新增 `context_project_read`，返回当前 agent 的 `agent_id`、`role`、`main_agent_id`、生效能力集（`scope.capabilities`，由 active grant 聚合）与本人已认领任务列表；不含 `secret_token` 或私有绝对路径。
  - `protocol/registry/commands.json`：注册 `context.project_read`（principal B、空 payload）。
  - `protocol/schemas/commands/context/project_read.schema.json`：空属性对象 schema。
  - `packages/bridge-server/src/server.ts`：新增 `context__project_read` 工具。

### 3. `task.lifecycle` —— preflight / progress 工具

- **根因**：bridge 只有 claim/start/submit，缺 preflight/progress 步骤。
- **修复**：
  - `src/tsunagou/modules/tasks.py`：新增 `PreflightResult`、`ProgressRecord` dataclass，`preflight()`（要求 owner 且 task=`claimed`）、`progress()`（要求 owner 且 task/attempt=`running`）；`start()` 增加 `preflight_id` 校验（缺失或错配抛 `preflight_id_mismatch`，尝试保持 `claimed` 不进入 running）。
  - `src/tsunagou/application/handlers.py`：新增 `task_preflight`（`task.coordinate_self`）与 `task_progress`（`task.execute`，按 task/attempt 限定）；`task_start` 透传 `attempt_id` 与 `preflight_id`。
  - `packages/bridge-server/src/server.ts`：新增 `task__preflight`、`task__progress` 工具，`task__start` 补充 `attempt_id`/`preflight_id`。

### 4. `recovery.idempotent_reconnect` —— expected_connection_epoch 校验

- **根因**：`session.reconnect` 只校验 nonce，不校验连接 epoch，重连在旧 epoch 下仍可能轮换凭据。
- **修复**（`src/tsunagou/modules/authority.py`）：`rebind()` 增加 `expected_connection_epoch` 参数，与 `session.connection_epoch` 做比较：不匹配抛 `PermissionError("stale_connection_epoch")`（HTTP 403）。nonce 与 epoch 的 CAS 使重连在重试下幂等（旧 nonce / 旧 epoch 均 fail closed 而非二次轮换）。`handlers.py` 的 `session_reconnect` 透传该参数。
- **仍缺**：「服务端已接收命令而客户端断线」的在途故障注入与旧连接在途提交拒绝，属宿主侧故障注入，非本层可完成。

### 5. `identity.continuity_evidence` —— compact / fork / new 生命周期

- **性质**：纯宿主侧生命周期证据（compact、fork、new），后端无对应可写代码路径。
- **本层动作**：备好 bridge 会话上下文与重连脚本模板，供真实 Codex 复验时直接使用；本轮不伪造任何连续性证据。

## 回归与隔离复测

| 检查 | 结果 |
|---|---|
| 全量单测 | `pytest` **98 passed**（新增 `test_task_lifecycle_claim_preflight_start_progress_submit`、`test_task_start_rejects_bogus_preflight_id`、`test_context_project_read_returns_own_scope`、`test_reconnect_rejects_stale_connection_epoch`、`test_unknown_payload_field_rejected`） |
| 协议校验 | `tools/codegen/validate_protocol.py` 通过（107 command policies / 112 schemas） |
| 协议 Schema 有效性 | `tests/protocol/test_protocol_codegen.py` 通过；`schema_bundle_digest` 已随 `commands.json` 变更重新计算为 `sha256:f2c3d8…`，并同步 `server.ts` 硬编码值 |
| bridge 类型检查 | `tsc -p packages/bridge-server/tsconfig.json` **exit 0** |
| 隔离真实 HTTP 复测 | 一次性 uvicorn（独立 loopback 端口 + 内存状态 + 一次性凭据），脚本 `http_probe_5caps.py`（stdlib urllib，非 TestClient），结果 9/9 通过 |

隔离 HTTP 复测（真实 HTTP 正负例，非单测/模拟器）：

```json
{
  "task.lifecycle": {
    "claim/preflight/start/preflight/progress": "200/200/200/200",
    "bogus_preflight_http": 400,
    "bogus_preflight_code": "preflight_id_mismatch"
  },
  "context.project_read": {"http": 200, "scope_has_coordination_read": true, "owned_task_listed": true},
  "command.typed_tools": {"unknown_field_http": 400, "code": "unknown_payload_field"},
  "recovery.idempotent_reconnect": {
    "rotate_fresh_nonce_correct_epoch": 200,
    "stale_expected_connection_epoch_http": 403,
    "stale_expected_connection_epoch_code": "stale_connection_epoch"
  }
}
```

脱敏证据见 [本轮 evidence](../research/evidence/codex-gap-tools-2026-09-19T2317-http.json)。票据 secret、session token、nonce、原始 thread ID、完整转录与私有绝对路径均不进入本文件或 evidence。

## 十项状态表（补齐后、真实 Codex 复验前）

「正式状态」继续沿用 [首轮验收规则](first-live-acceptance.md)：只有真实宿主完整正例 + 必要负例才算 `supported`。本轮只做源码/工具补齐与**隔离 HTTP/单测**复测，**不构成真实 Codex 模型工具调用证据**，故补齐项仍保持 `unknown`。

| 能力 | 补齐前 | 本轮补齐 | 正式状态（补齐后） |
|---|---|---|---|
| `identity.session_isolation` | supported | — | supported |
| `contract.participation` | supported | — | supported |
| `inbox.pull_fetch_ack` | supported | — | supported |
| `command.typed_tools` | unknown（缺额外字段/actor 拒绝） | 未知字段 dispatcher 拒绝 | unknown：已修，待真实 Codex 复验 |
| `context.project_read` | unknown（无项目/任务/scope 查询） | `context__project_read` 工具 | unknown：已修，待真实 Codex 复验 |
| `task.lifecycle` | unknown（缺 preflight/progress） | `task__preflight`/`task__progress` 工具 | unknown：已修，待真实 Codex 复验 |
| `recovery.idempotent_reconnect` | unknown（缺 epoch CAS） | `expected_connection_epoch` CAS | unknown：已修；仍缺在途断线故障注入 |
| `identity.continuity_evidence` | unknown | 脚本/模板备好 | unknown：仍需 compact / fork / new 生命周期 |
| `cognition.report` | unknown（已修 schema） | — | unknown：待真实 Codex 复验 |
| `response.structured` | unknown（已修存在/发送者/关联） | — | unknown：仍缺 response schema 契约校验 |
| `delivery.deduplicate` | unknown（已修 command_id 冲突） | — | unknown：待真实 Codex 复验 |

## 剩余阻断与最小补证

- 四项已补齐能力的**正式转正**取决于真实 Codex（`codex-cli 0.155.0-alpha.9.2`）重新经 bridge 调用 `task__preflight`/`task__progress`、`context__project_read`、`message__send`（含未知字段负例）并留下 MCP 状态与返回内容；这是任务 #37 的范围。
- `recovery.idempotent_reconnect` 还差「服务端已接收命令而客户端断线」的在途故障注入。
- `identity.continuity_evidence` 还差有内容会话的 compact 与 fork/new 生命周期观察。
- `response.structured` 还差「回应消息符合 response_contract schema」的校验，是独立后续工作。

交付的命令与退出码：`pytest` exit 0（98 passed）；`tsc` exit 0；`validate_protocol.py` exit 0；`http_probe_5caps.py` 9/9 通过。未修改 `release_check.py`；本轮不改变 OpenCode / DeepSeek Harness 与首发发布门禁。
