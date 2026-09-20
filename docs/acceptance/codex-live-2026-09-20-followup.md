# Codex 单宿主缺口补证：2026-09-20 后续

本轮在 `elysia` 分支 `081116d` 上补齐了三个产品语义缺口，并完成本地/隔离 HTTP 验证；真实 Codex 模型复验因本机 API key 返回 `401 invalid_api_key` 而 blocked。未改 OpenCode、DeepSeek Harness、发布门禁或已有六项 supported 的正式状态，也未 commit、push、release。

## 已改动的产品语义

1. `context.project_read`
   - `context_project_read` 现在会返回 `project_id`。
   - `build_application()` 优先读取 `TSUNAGOU_PROJECT_ID`，否则从 `TSUNAGOU_PROJECT_ROOT/.tsunagou/project.json` 读取。

2. `response.structured`
   - `inbox__claim` / `inbox__fetch` 会向收件方暴露自己的 `response_obligations`，包括 `obligation_id`、`status` 和 `contract`。
   - `MessageStore.respond` 在关闭义务前，用 `Draft202012Validator` 校验回应消息 payload 是否满足 `response_contract.schema`；不满足返回 `response_schema_violation`，义务保持 `open`。

3. `delivery.deduplicate`
   - 同一 `command_id` 的冲突比较现在覆盖 `priority`、`response_contract` 和 `in_reply_to`。
   - bridge 的 `message__send` 增加可选 `command_id`，用于真实 MCP 安全演示“同一原始 command ID、改输入”的冲突负例；缺省时仍从完整 payload 派生 id。

## 本地质量与隔离复测

```text
pytest: passed
ruff: passed
mypy: passed
validate_protocol.py: passed
validate_docs.py: passed
corepack pnpm run check: passed
bridge-server build: passed
```

隔离 HTTP 探针（真实 uvicorn，非单测/模拟器）验证了：

- `context.project_read` 返回项目 ID。
- 坏 schema 回应被 `response_schema_violation` 拒绝且义务仍 open，好 schema 回应令义务 responded。
- 同一命令 ID 同输入幂等，同一命令 ID 改输入返回 `command_id_conflict`。

## 真实 Codex 模型复验

本轮尝试使用全新专用 main/worker thread、空 Git 项目、独立 loopback 服务和状态目录，通过 `--ignore-user-config` 和 bridge MCP 配置发起真实 Codex 调用。

失败事实：

- `codex login status` 显示本机使用一个 API key，但模型采样请求返回 `HTTP 401 invalid_api_key`。
- 两个 seed turn 退出码均为 1，三个业务 turn 退出码均为 2。
- 没有 MCP 工具调用 completed；失败 enroll 后会话为 `degraded`。
- 原始 thread ID、票据、session token 和 raw JSONL 只在私有临时区使用，提取脱敏结果后已清理。

因此本轮不能把任何 unknown 能力改写成 supported。`context.project_read`、`response.structured`、`delivery.deduplicate` 已有产品语义和隔离 HTTP 证据，但仍缺少真实 Codex 模型工具调用的正负例。

## 后续最小动作

在 Codex API key 恢复可用后，按 [前轮报告](codex-live-2026-09-20.md) 中的安全命令骨架继续：

- 一次真实 `context__project_read`，核对 `project_id`、任务和 worker scope。
- 一次带 response schema 的真实回应正负例。
- 一次真实 MCP 同 command ID 幂等正例与改输入冲突负例。

`identity.continuity_evidence` 与 `recovery.idempotent_reconnect` 仍分别等待有内容会话的 compact/fork/new 脚本，以及在途断线故障注入脚本。
