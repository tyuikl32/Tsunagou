# CLI, HTTP and enrollment entrypoint contracts

Current delivery note (2026-09-28): FX1/FX2 are implemented; FX4 runtime/install work is in progress. Independent tickets, private session credentials and epochs are operational. Retain user/main/worker boundaries. Older full-host release requirements below do not block the authorized standalone flow; current interfaces and evidence are in the FX task records.

## 1. Scope / Trigger

Apply when implementing T03/T06/T16/T17 or changing a request example. Sources: [CLI contract](../../../docs/implementation/cli-contract.md), [protocol](../../../docs/implementation/protocol.md), [command catalog](../../../docs/implementation/command-catalog.md), [user manual](../../../docs/overview/cli-http-manual.md). These are planned contracts, not existing application code.

## 2. Signatures

- User CLI: `tsunagou [--project <id>] [--json] <group> <command> ...`.
- `agent enroll --adapter <kind> [--profile <name>] --mode attach|launch` orchestrates U ticket issuance and target-bridge ticket redemption as separate identities/transactions.
- Agent begin: `POST /api/v1/commands/task.begin`, B/task.claim, payload task_id + expected_task_revision.
- User decision: `POST /api/v1/projects/{project_id}/control/decisions/{id}:resolve`, user_control, no Grant.
- REST and MCP adapt into the same dispatcher; neither has a private authorization bypass.
- Current CLI project selection: `--project-root` or the explicit bound environment, then the nearest ancestor `.tsunagou/project.json`. All endpoint/control reads use the same RuntimeContext; conflicting project IDs/roots/endpoints fail with context conflicts.
- Daemon health includes actual service PID/runtime_id/project_ids/source. Stop verifies this identity before terminating. A Windows virtualenv launcher PID is not necessarily the service PID.
- Current local HTTP safety boundary: `create_app(dispatcher=None, *, authenticator=None)`; `LocalCommandAuthenticator.authenticate(principal_kind, authorization, *, session_id, connection_epoch) -> PrincipalContext`. Default construction has no credential and fails closed for business commands.
- Current authority primitives: `issue_ticket(installation_id, conversation_id, ttl_seconds=600) -> secret`, `redeem_ticket(secret, installation_id, conversation_id, *, baseline=None) -> EnrollmentReceipt`, `session_status(baseline) -> ready|degraded`.

## 3. Contracts

CLI request-file contains only typed business payload. CLI creates command_id and protocol envelope, maps expected-revision to If-Match and privately loads control credentials. No token/actor CLI flags or secret environment variables. The bridge privately injects its own session headers; an installation profile is not an authenticated conversation.

HTTP must ignore/remove caller-supplied `X-Principal-Kind` and `X-Principal-Id`: a bearer credential plus server-side session/epoch/grant state determines the principal. The local authenticator recognizes configured U control credentials, one-time T ticket secrets, and ready B/M/X sessions; T and X both fail closed when their credential/grant is absent, never inferred from header names. A domain handler must still enforce command-specific scope/revision. The one-time ticket secret is delivered to the selected bridge only through a 0600 private file (the CLI writes it, never stdout). Durable authority state stores the ticket hash, never the redeemable value.

U ticket creation may include a private Desktop binding intent. Its thread must match the ticket conversation. Enrollment/rebind commits credentials before applying the binding file; retry is idempotent, and an older receipt must not overwrite a newer session epoch or endpoint. Raw thread/pipe stays out of events and shared checkpoints. CLI onboarding and actual-host readiness must still be verified separately.

`baseline_ok: true` is not admission evidence. Ready requires the 4 admission capability rows (`identity.session_isolation`, `identity.continuity_evidence`, `context.project_read`, `command.typed_tools`) to be `supported`, each with non-empty `evidence_refs`; degraded sessions cannot receive agent_base or main authority. The full 11-capability baseline still gates the first-release `release_check.py`. These rows still require trusted real-host provenance before claiming live support: a unit fixture with all rows proves only the gate logic.

Mutation envelope contains command_id/protocol_version/schema_bundle_digest/payload. Header/body protocol and digest must agree. For X execution commands, attempt context belongs to envelope; B coordination commands retain explicitly cataloged attempt fields in payload. Reject conflicting duplicates; never silently choose one.

Begin atomically returns running ownership after preparation; submit automatically captures results and releases. Same-owner begin after restart restores the existing Attempt; no timer transfers ownership. User decision approval does not auto-resume work. CLI must not impersonate main for commands that lack a registered U handler. See [execution contract](standalone-runtime.md).

Decision list authenticates the selected project's U or B principal and projects the persisted proposal's choices/summary, revision/proposal_digest, status/answer and existing UTC entity times. Missing historical proposal content remains null. A successful U resolution atomically creates one user_decision.resolved message for the current main, when appointed, through the existing message/outbox path; replay cannot duplicate it. No decision timeout, task resume, extra read access to private inboxes or business interpretation follows from that notification.

## 4. Validation & Error Matrix

FX4 local daemon routing uses URL project ID or `Tsunagou-Project-Id`; conflicting selectors fail, and unqualified requests to a multi-project daemon fail. Project selection never grants authority. `daemon start --reuse ROOT` authenticates registration with the daemon owner's U token; each attached container receives only its own root/state/control config. Never mutate process-wide environment variables to switch projects. A shared daemon restart restores its registered project set and rewrites each endpoint; stop reports all affected projects.

Codex shared stdio MCP requires host `_meta.threadId` on every call and reads that conversation's private route/session. Never fall back to process-global identity in shared mode. `agent prepare` observes a real host and creates no authority; `connect` reports enrolled after headless bootstrap, and only the original conversation's MCP context establishes host readiness. Ordinary requests reuse saved sessions; reconnect only when required. Connect's Python-only outer serialization uses ProjectLock, not the cross-language socket mutex held across network/Node work.

Project bootstrap writes only selected-host resources, preserves user blocks, and emits RFC3339 UTC updated_at. An unchanged generated content digest preserves the previous timestamp; a digest is never itself a time value. Codex config and global registration use one shared server name, tsunagou.

Concurrent Codex connections serialize the whole global MCP get/add/environment-forwarding operation with the existing OS ProjectLock, separate from per-conversation connect locks. The config forwards CODEX_APP_TOOLS_PIPE_PATH with env_vars instead of storing a frozen endpoint; valid comments on the owned TOML table or env_vars assignment must not create duplicate keys.

The shared bridge may restore an already-enrolled route's binding after a host generation change without reading that Agent's tasks/inbox. This transport recovery is not evidence of an LLM turn or original-host readiness. Compare the desired host generation against the latest session inside the credential mutex, not a caller's prior snapshot: concurrent startup restore and tool calls must share the exchange, and a late caller must reuse the refreshed generation. Authentication-failure recovery can still explicitly request a reconnect.

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
