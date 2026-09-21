# CLI, HTTP and enrollment entrypoint contracts

Current delivery note (2026-09-20): [D183](../../../docs/decisions/2026-09-20-standalone-priority.md) prioritizes the local standalone M1 flow. The planned local_session admission mode uses independent tickets, private session credentials and epochs; host capability reports are not an M1 execution prerequisite. This is not implemented yet. Retain user/main/worker boundaries; do not fabricate supported capabilities. Existing contracts below describe the original full-host profile where applicable.

## 1. Scope / Trigger

Apply when implementing T03/T06/T16/T17 or changing a request example. Sources: [CLI contract](../../../docs/implementation/cli-contract.md), [protocol](../../../docs/implementation/protocol.md), [command catalog](../../../docs/implementation/command-catalog.md), [user manual](../../../docs/overview/cli-http-manual.md). These are planned contracts, not existing application code.

## 2. Signatures

- User CLI: `tsunagou [--project <id>] [--json] <group> <command> ...`.
- `agent enroll --adapter <kind> [--profile <name>] --mode attach|launch` orchestrates U ticket issuance and target-bridge ticket redemption as separate identities/transactions.
- Agent claim: `POST /api/v1/projects/{project_id}/tasks/{task_id}:claim`, B/agent_base/task.claim.
- User decision: `POST /api/v1/projects/{project_id}/control/decisions/{id}:resolve`, user_control, no Grant.
- REST and MCP adapt into the same dispatcher; neither has a private authorization bypass.
- Current local HTTP safety boundary: `create_app(dispatcher=None, *, authenticator=None)`; `LocalCommandAuthenticator.authenticate(principal_kind, authorization, *, session_id, connection_epoch) -> PrincipalContext`. Default construction has no credential and fails closed for business commands.
- Current authority primitives: `issue_ticket(installation_id, conversation_id, ttl_seconds=600) -> secret`, `redeem_ticket(secret, installation_id, conversation_id, *, baseline=None) -> EnrollmentReceipt`, `session_status(baseline) -> ready|degraded`.

## 3. Contracts

CLI request-file contains only typed business payload. CLI creates command_id and protocol envelope, maps expected-revision to If-Match and privately loads control credentials. No token/actor CLI flags or secret environment variables. The bridge privately injects its own session headers; an installation profile is not an authenticated conversation.

HTTP must ignore/remove caller-supplied `X-Principal-Kind` and `X-Principal-Id`: a bearer credential plus server-side session/epoch/grant state determines the principal. The local authenticator recognizes configured U control credentials, one-time T ticket secrets, and ready B/M/X sessions; T and X both fail closed when their credential/grant is absent, never inferred from header names. A domain handler must still enforce command-specific scope/revision. The one-time ticket secret is delivered to the selected bridge only through a 0600 private file (the CLI writes it, never stdout). Durable authority state stores the ticket hash, never the redeemable value.

`baseline_ok: true` is not admission evidence. Ready requires the 4 admission capability rows (`identity.session_isolation`, `identity.continuity_evidence`, `context.project_read`, `command.typed_tools`) to be `supported`, each with non-empty `evidence_refs`; degraded sessions cannot receive agent_base or main authority. The full 11-capability baseline still gates the first-release `release_check.py`. These rows still require trusted real-host provenance before claiming live support: a unit fixture with all rows proves only the gate logic.

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
| Missing/invalid bearer or stale session connection epoch | 401 authentication_failed; no handler call |
| Authenticated session lacks main authority grant | 403 capability_denied; no handler call |
| Unsupported T/X authentication path | fail closed until ticket/attempt verification is wired |
| Boolean-only or incomplete baseline | degraded; no agent_base and no main appointment |
| Duplicate or mismatched one-time ticket | invalid_or_consumed_enrollment_ticket or enrollment_identity_mismatch; no second session |
| Malformed/non-serializable baseline snapshot | reject before ticket consumption or credential rotation; no partial in-memory authority change |
| CLI Operation wait expires | exit 6, operation remains active |
| Agent-only action invoked through user CLI | no executable subcommand; use correct actor tool |

## 5. Good / Base / Bad Cases

Good: user attaches two conversations; each bridge redeems a distinct worker ticket, gets an independent session and reports baseline. User appoints only one main.

Base: host has no managed_launch/wake/gate enhancement. User opens the host and attaches; supported baseline still allows pull-based coordination.

Bad: an internal host subagent shares its parent's token, then supplies actor_agent_id to appear as a project worker. Reject this model; formal membership requires independent identity and enrollment.

Base: `create_app()` without configured credentials keeps health available but rejects business mutations with 401. Good: a ready HostSession bearer resolves its own agent ID and current epoch. Bad: a request with `X-Principal-Kind: M` is accepted without a real credential, or a synthetic `baseline_ok` boolean appoints a main.

## 6. Tests Required

Map every executable CLI command to its registry principal/kind/URI. Validate manual JSON examples against generated DTOs after replacing explicit demonstration placeholders with valid fixture values. Assert no unknown actor/secret fields, no auto-approval of a changed decision, no token output, no automatic running state after enroll/claim/resume. Preserve equivalent errors and idempotency between HTTP and MCP.

Assert the generated OpenAPI no longer declares `X-Principal-*`; default HTTP rejects missing bearer; ready B bearer resolves server-side agent ID; stale epoch/degraded session is 401; U and agent credentials cannot replace each other; boolean-only baseline cannot grant ready/main; malformed baseline leaves ticket redeemable and reconnect epoch unchanged; persisted authority JSON contains neither ticket secret nor session token. Codex/bridge unit tests do not upgrade a live host capability.

## 7. Wrong vs Correct

Wrong: expose task publish in user CLI by reading current main's token. Correct: only register U-backed CLI actions; current main uses its own task.publish tool.

Wrong: `P/events:stream` is treated as MCP transport. Correct: business SSE is a high-watermark hint; MCP Streamable HTTP has its own protocol/session semantics at P/mcp.

Wrong: `dispatcher.dispatch(..., principal_kind=request.header("X-Principal-Kind"), principal_id=request.header("X-Principal-Id"))`. Correct: `principal = authenticator.authenticate(policy["principal"], bearer, session_id=session_id, connection_epoch=epoch)` then `dispatcher.dispatch(..., principal=principal)`; missing trusted authentication rejects the command.
