# CLI, HTTP and enrollment entrypoint contracts

## 1. Scope / Trigger

Apply when implementing T03/T06/T16/T17 or changing a request example. Sources: [CLI contract](../../../docs/implementation/cli-contract.md), [protocol](../../../docs/implementation/protocol.md), [command catalog](../../../docs/implementation/command-catalog.md), [user manual](../../../docs/overview/cli-http-manual.md). These are planned contracts, not existing application code.

## 2. Signatures

- User CLI: `tsunagou [--project <id>] [--json] <group> <command> ...`.
- `agent enroll --adapter <kind> [--profile <name>] --mode attach|launch` orchestrates U ticket issuance and target-bridge ticket redemption as separate identities/transactions.
- Agent claim: `POST /api/v1/projects/{project_id}/tasks/{task_id}:claim`, B/agent_base/task.claim.
- User decision: `POST /api/v1/projects/{project_id}/control/decisions/{id}:resolve`, user_control, no Grant.
- REST and MCP adapt into the same dispatcher; neither has a private authorization bypass.

## 3. Contracts

CLI request-file contains only typed business payload. CLI creates command_id and protocol envelope, maps expected-revision to If-Match and privately loads control credentials. No token/actor CLI flags or secret environment variables. The bridge privately injects its own session headers; an installation profile is not an authenticated conversation.

Mutation envelope contains command_id/protocol_version/schema_bundle_digest/payload. Header/body protocol and digest must agree. For X execution commands, attempt context belongs to envelope; B coordination commands retain explicitly cataloged attempt fields in payload. Reject conflicting duplicates; never silently choose one.

Claim returns claimed ownership, not running execution. Resume returns claimed preparation, not start. User decision approval does not auto-resume an Attempt. CLI must not impersonate main for commands that lack a registered U handler.

## 4. Validation & Error Matrix

| Condition | Required outcome |
|---|---|
| Header/body protocol mismatch | 400 malformed_request |
| Missing required revision | 428 revision_required |
| Stale displayed decision | 412 revision_conflict / digest conflict; require review |
| Same command_id, different semantic input | 409 idempotency_conflict |
| Agent token on control endpoint | 403 user_only |
| Missing baseline identity evidence | diagnostic-only degraded, no claim |
| CLI Operation wait expires | exit 6, operation remains active |
| Agent-only action invoked through user CLI | no executable subcommand; use correct actor tool |

## 5. Good / Base / Bad Cases

Good: user attaches two conversations; each bridge redeems a distinct worker ticket, gets an independent session and reports baseline. User appoints only one main.

Base: host has no managed_launch/wake/gate enhancement. User opens the host and attaches; supported baseline still allows pull-based coordination.

Bad: an internal host subagent shares its parent's token, then supplies actor_agent_id to appear as a project worker. Reject this model; formal membership requires independent identity and enrollment.

## 6. Tests Required

Map every executable CLI command to its registry principal/kind/URI. Validate manual JSON examples against generated DTOs after replacing explicit demonstration placeholders with valid fixture values. Assert no unknown actor/secret fields, no auto-approval of a changed decision, no token output, no automatic running state after enroll/claim/resume. Preserve equivalent errors and idempotency between HTTP and MCP.

## 7. Wrong vs Correct

Wrong: expose task publish in user CLI by reading current main's token. Correct: only register U-backed CLI actions; current main uses its own task.publish tool.

Wrong: `P/events:stream` is treated as MCP transport. Correct: business SSE is a high-watermark hint; MCP Streamable HTTP has its own protocol/session semantics at P/mcp.
