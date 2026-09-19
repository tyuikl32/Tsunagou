# 三缺陷修复记录：2026-09-19（elysia，协同验收人员 elysia080928）

本记录是 [Codex 独立复验](codex-independent-2026-09-19.md)定位的三个缺陷的**修复与修复后复测**，不是首发发布验收。只改产品源码、协议 Schema 与测试，**未 commit / push / release**，未改动 `release_check.py` 判定，未把单测/HTTP 证据写成真实宿主证据。

- 仓库分支 `elysia`，HEAD `166045e`。
- 修复前定位依据：[Codex 独立复验报告](codex-independent-2026-09-19.md)与脱敏 evidence `codex-2026-09-19T2136-independent.json`。

## 三个缺陷与修复（版本差异）

### 1. `cognition__report.claims` schema 与后端对象要求不一致

- **根因**：bridge 工具 schema 把 `claims` 声明为裸 `{type:"array"}`（无 `items`），真实 Codex 据此生成字符串元素；后端 `_claim`（`src/tsunagou/application/handlers.py`）要求 dict 元素，六次返回 `invalid_claim`。
- **修复**：
  - `packages/bridge-server/src/server.ts`：`claims` 改为对象数组（`items` 含 `subject_key`（必填）、`subject`、`claim_type`、`equality_key`、`value`、`evidence_refs: string[]`）；`assumptions` / `uncertainties` 改为 `string[]`。
  - `protocol/schemas/commands/cognition/report.schema.json`：`claims`/`assumptions`/`uncertainties` 三字段同步为上述对象数组 / 字符串数组（该 schema 由 `tools/codegen` 从 command-catalog 粗粒度生成，本文件为手工对齐契约，不被扁平入口运行时校验）。
- **后端未改**：`_claim` 本来就正确拒绝非 dict（`invalid_claim`）与缺 `subject`（`claim_subject_required`）；修复只是让模型不再生成字符串元素。

### 2. `message.respond` 不校验 `response_message_id`

- **根因**：`MessageStore.respond`（`src/tsunagou/modules/messaging.py`）只按 obligation ID 标记 `responded`，不核对 `response_message_id` 是否存在，隔离负例仍返回 200 并关闭义务。
- **修复**（`respond` 前新增三道校验，任何一道不满足即抛错、义务保持 `open`）：
  - `response_message_id` 不存在 → `ValueError("response_message_not_found")`（HTTP 400）；
  - 回应消息 `sender_agent_id != 义务接收者` → `PermissionError("response_sender_mismatch")`（HTTP 403）；
  - 回应消息 `in_reply_to != 义务.message_id` → `ValueError("response_not_linked_to_obligation")`（HTTP 400）。

### 3. 去重键是内容 hash 而非原始 `command_id`

- **根因**：dispatcher 的 `command_hash` 不含原始 `command_id`（`src/tsunagou/interfaces/runtime.py`），`message_send` 用它当去重键（`handlers.py`），导致同 `command_id` 改输入生成第二条消息而非冲突。
- **修复**：
  - `runtime.py`：handler 上下文新增 `command_id = envelope["command_id"]`。
  - `handlers.py`：`message_send` 改用 `command_id=context["command_id"]`。
  - `messaging.py`：`send` 按 `command_id` 命中 `command_index` 后比对（sender/recipient/kind/subject_ref/summary/payload_digest）：一致 → 幂等返回同一消息；不一致 → `ValueError("command_id_conflict")`。
  - `packages/bridge-server/src/server.ts`：`dispatch` 的命令 id 改为内容派生 `"idem:" + sha256(kind + ":" + canonicalJson(payload))`，使真实 MCP 的相同参数重试幂等、不同参数成为不同命令（客户端改内容复用 id 则由服务端拒绝）。

## 回归与修复后复测

| 检查 | 结果 |
|---|---|
| 定向 + 全量单测 | `pytest` **94 passed**（含新增/更新的 `test_messaging.py`、`test_business_handlers.py`、`test_cognition_report_rejects_string_claims`） |
| 协议 Schema 有效性 | `tests/protocol/test_protocol_codegen.py` 通过（`Draft202012Validator`） |
| bridge 类型检查 + 构建 | `tsc -p packages/bridge-server/tsconfig.json` **exit 0**，`dist/server.js` 含新 claims items 与 `idem:` 命令 id |
| 隔离真实 HTTP 复测 | 一次性 uvicorn（独立 loopback 端口 + 独立状态目录 + 一次性 control token），脚本 `fixes_probe.py`，结果见下 |

隔离 HTTP 复测（真实 HTTP 正负例，非单测/模拟器）：

```json
{
  "cognition": {"object_claims_http": 200, "string_claims_http": 400, "string_claims_code": "invalid_claim"},
  "dedup": {"same_input_same_id": true, "changed_input_http": 400, "changed_input_code": "command_id_conflict"},
  "respond": {"nonexistent_response_http": 400, "nonexistent_response_code": "response_message_not_found",
              "real_response_http": 200, "real_response_status": "responded"}
}
```

`respond` 的负例后紧跟正例：负例 400 之后正例仍 200 `responded`，证明坏回应未把义务关成 `responded`（否则正例会撞 `obligation_already_closed`）。

## 十项状态表（修复后、真实 Codex 复验前）

“正式状态”继续沿用 [首轮验收规则](first-live-acceptance.md)：只有真实宿主完整正例 + 必要负例才算 `supported`。我本轮只做了源码修复与**隔离 HTTP/单测**复测，**不构成真实 Codex 模型工具调用证据**，故三处已修复项仍保持 `unknown`，等待真实 Codex 复验确认。

| 能力 | 修复前（Codex 独立复验） | 本轮修复 | 正式状态（修复后） |
|---|---|---|---|
| `identity.session_isolation` | supported | — | supported |
| `contract.participation` | supported | — | supported |
| `inbox.pull_fetch_ack` | supported | — | supported |
| `cognition.report` | unknown（`invalid_claim` 阻断） | claims 对象数组 schema | unknown：源码+HTTP 已修，待真实 Codex 复验 |
| `response.structured` | unknown（坏回应被接受） | respond 校验存在/发送者/关联 | unknown：存在/发送者/关联已修；仍缺 response schema 契约校验，待真实 Codex 复验 |
| `delivery.deduplicate` | unknown（改输入建第二条） | 按 command_id 冲突语义 | unknown：源码+HTTP 已修，待真实 Codex 复验 |
| `command.typed_tools` | unknown（claims 元素 schema 缺失） | 补 claims 元素 schema | unknown：仍缺额外字段与 actor 拒绝验证 |
| `identity.continuity_evidence` | unknown | — | unknown：仍需 compact / fork / new 生命周期 |
| `context.project_read` | unknown | — | unknown：仍需项目 ID / 任务 / scope 查询工具 |
| `task.lifecycle` | unknown | — | unknown：仍需 preflight / progress |
| `recovery.idempotent_reconnect` | unknown | — | unknown：仍需在途断线故障注入 |

## 剩余阻断与最小补证

- 三项已修复能力的**正式转正**取决于真实 Codex（`codex-cli 0.155.0-alpha.9.2`）重新经 bridge 调用 `cognition__report`（对象 claims）、`message__respond`（含坏回应负例）、`message__send`（同参幂等 + 改参冲突）并留下 MCP 状态与返回内容。
- `response.structured` 仍缺「回应消息符合 response_contract schema」的校验，是独立的后续工作。
- `command.typed_tools`、`identity.continuity_evidence`、`context.project_read`、`task.lifecycle`、`recovery.idempotent_reconnect` 有各自独立的补齐项，与本轮三缺陷无关，仍需对应工具 / 生命周期 / 故障注入。

交付的命令与退出码：`pytest` exit 0（94 passed）；`tsc` exit 0；`fixes_probe.py` 见上表。未修改 `release_check.py`；本轮不改变 OpenCode / DeepSeek Harness 与首发发布门禁。
