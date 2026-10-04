# CLI, HTTP and enrollment entrypoint contracts

## Scenario: completion-triggered exclusive daemon shutdown

### 1. Scope / Trigger

Applies to a fresh `project.completion.confirm` committed during this daemon run. Process lifecycle belongs to bootstrap, not domain handlers. No startup scan, historical cleanup, idle timer or console autostart change.

### 2. Signatures

Existing `POST /api/v1/commands/project.completion.confirm` and its `operation_id`/`checkpoint_status` result remain unchanged. CLI daemon start launches a runner owning `uvicorn.Server`; its internal shutdown callback sets `should_exit`. No new public command, schema or migration.

### 3. Contracts

Track the exact completion checkpoint operation in process memory after durable dispatch. Stop only after its succeeded outcome and successful final confirmation response send. Deferred success is observed through existing maintenance; a failed checkpoint keeps the daemon usable for retry. Domain completion remains committed if materialization fails.

Final exclusive-project check and closing transition use the same asyncio lock as project registration. Once closing, refuse registration using the existing registration failure contract. More than one registered project always suppresses automatic shutdown. Request graceful server exit once and reuse existing lifespan cleanup; do not kill a PID or terminate from inside the completion transaction.

### 4. Validation & Error Matrix

| Condition | Behavior |
|---|---|
| Fresh confirmed completion, exact checkpoint succeeds, response sent, one project | Graceful daemon exit |
| Checkpoint pending or failed | Stay running; retry of that operation may later permit exit |
| Shared daemon | Stay running regardless of member completion states |
| Denied/stale/unauthorized confirmation | No shutdown eligibility |
| Confirmation replay from an earlier daemon run | No historical shutdown eligibility |
| Registration wins the lock before closing | Preserve newly shared daemon |
| Closing wins before registration | Registration refused |

### 5. Good/Base/Bad Cases

Good: client receives completion response, then the service PID exits and the port is released. Base: restart a completed project for online inspection and keep it running. Bad: stop after a genesis checkpoint, on `completed` alone, before sending the response, or while another registered project needs the daemon.

### 6. Tests Required

Cover failed checkpoint then successful same-operation retry, delayed success, response barriers, concurrent registration, shared project isolation, denial/replay and restart. Real Windows subprocess coverage must observe service PID exit and bind the released listener port; mocked callbacks alone are insufficient.

### 7. Wrong vs Correct

Wrong: call `taskkill` from the completion handler or scan all completed projects on startup. Correct: associate the new committed command with its checkpoint, wait for response completion, and let bootstrap request the server's existing graceful shutdown after the exclusive-project check.

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
- DeepSeek `agent connect` inserts the matching active console selection before cwd discovery. Explicit selection must match that request; no request preserves manual cwd discovery. See the DeepSeek project-selection scenario below.
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


## Scenario: console-selected Codex join (2026-10-02)

### 1. Scope / Trigger

The local console selects a project and main/worker role before the real Codex chat is known. Do not sign a ticket for a display profile or derive the target project from that chat's cwd. See [console join decision](../../../docs/decisions/2026-10-02-console-codex-join.md).

### 2. Signatures

- `tsunagou agent join`: no project/role arguments; validates the actual Desktop conversation and claims the console selection.
- `GET /api/v1/console/enrollments/current`: recover the current public wait or `{ "status": "none" }`.
- Existing project `agents:prepare`, enrollment status and cancel routes remain; Codex prepare returns `host_registration.status=deferred` without a ticket or MCP registration.
- `EnrollmentStore.create/active/current/claim/mark_enrolled/fail/mark_arrived/cancel/forget_project` own local handoff state, not daemon Agent authority.

### 3. Contracts

Private store defaults to `~/.tsunagou/console-enrollments`; `TSUNAGOU_ENROLLMENT_DIR` isolates tests. A record contains enrollment_id, absolute project_root, project_id, requested_role, nickname, revision, lifecycle times and receipt_file; claim adds the verified thread_id, enrollment adds exact agent_id. One active request per OS user spans projects and consoles. The 900-second timeout applies only while pending; claimed work remains owned by its chat. Matching project/root/role preparation reuses the record and original nickname. A same-chat retry finds its prior binding before any newer pending request. Late failure must not downgrade enrolled/arrived.

Use CODEX_THREAD_ID (or CODEX_SESSION_ID) plus the existing app-tools read_thread verification. Before claim, require the selected project's real manifest and reject a conflicting existing Codex route. Connect and join share `application.agent_connection.connect_agent`; never mutate process-wide environment to switch roots. Store/route locks cover only local compare/write operations, never host or daemon calls.

The private shared route optionally carries `console_enrollment={enrollment_id,requested_role,receipt_file}`. Only a successful original `context.project_read` with ready session and matching identity/role writes a receipt: format_version=1, enrollment_id, thread_id, project_id, agent_id, role, session_id, connection_epoch, observed_at (RFC3339). The CLI helper sets `TSUNAGOU_CONNECT_HELPER=1` after config env merge; it and startup restoration produce no arrival receipt. Receipts may not overwrite another binding or a newer epoch.

Console completion requires that receipt plus a fresh daemon roster with matching exact Agent, ready status, role and epoch. HTTP projects only an allowlist; raw thread, pipe, receipt path and credentials stay private. Current-status and prepare reconcile completed receipts so a refreshed page cannot occupy the global slot forever. The frontend restores waiting by ID without advancing an unrelated project wizard. Cancellation never unregisters the shared MCP.

### 4. Validation & Error Matrix

| Condition | Outcome |
|---|---|
| No pending request / missing real Desktop context | enrollment_not_pending / desktop_context_missing; no project initialization |
| Manifest or explicit root conflicts with selection | onboarding_project_mismatch (or project_context_conflict); no claim |
| Existing chat route names another project/root | host_route_project_conflict before claim; connecting retains its own route check |
| Another chat owns request | enrollment_claimed_by_another_chat |
| Different selection while a request is active | HTTP 409 enrollment_already_pending with public detail.enrollment and actionable note |
| Claim versus pending cancel/expiry race | one locked state transition wins; no reassignment |
| Cancel after claim | HTTP 409 enrollment_already_claimed; continue polling |
| Missing/stale receipt, wrong role/Agent/epoch, unavailable fresh roster | waiting, never arrived |

### 5. Good/Base/Bad Cases

Good: a chat running in another directory joins the console-selected main and repeats with the same Agent identity. Base: first installation or upgrading an already-running older bridge requires one host reload before original MCP verification. Bad: missing request falls back to initializing cwd, default worker, or a fabricated conversation profile.

### 6. Tests Required

`test_enrollment_store.py` covers concurrent claims, retries, persistence and lifecycle fencing. `test_console_enrollment.py` covers deferred preparation, public projections, exact receipt/epoch, stale roster, refresh recovery and cancel conflict. `test_console_join.py` verifies unrelated cwd, main/worker, no implicit initialization, real-host validation and preclaim route checks. `test_console_join_flow.py` exercises a real daemon/bridge with a fixture Desktop client; helper enrollment stays waiting until original-client context. Bridge credential tests fence receipts; frontend smoke tests cover deferred/failed phases, cancel races and restored waits. Fixtures do not establish real Desktop acceptance.

### 7. Wrong vs Correct

Wrong: `prepare --role worker` after a console join error, or report success because any new Agent appeared. Correct: `agent join`, retry only in the owning chat, then call the original conversation's MCP context; the console checks the bound Agent and its receipt.

## Scenario: DeepSeek Console Project Selection

### 1. Scope / Trigger

Apply to DSH `tsunagou_connect` and DeepSeek CLI connect. The console's project selection must not be displaced by host cwd or its ancestor project. This contract does not change console observation, claims, receipts, or other adapters.

### 2. Signatures

- `agent pending --adapter deepseek`: public non-secret selection including `enrollment_id`, `project_root`, `project_id`, `role`, and record `state`.
- `tsunagou [--project-root ROOT] agent connect --adapter deepseek [--pending-enrollment-id ID]`: the enrollment ID option is hidden and used by the host adapter to pin a selection.
- `tsunagou_connect` accepts only optional `role`; project paths and identity never come from model arguments.

### 3. Contracts

The adapter probes pending through the installed CLI using real host identity/cwd. Matching selection supplies the project root and enrollment ID to connect; `status:none` retains cwd fallback. Invalid or failed probe must not become a successful manual fallback. CLI rechecks the exact active request, manifest root/id, and existing private conversation route before creating bridge identity, ticket, or agent. Explicit root/environment and pending selection must agree. With no DeepSeek request, manual cwd/ancestor discovery remains supported. Other host requests are ignored.

### 4. Validation & Error Matrix

| Condition | Outcome |
|---|---|
| Pending manifest/root/id or explicit selection differs | `onboarding_project_mismatch`; no connection side effects |
| Existing DSH conversation route names another project | `onboarding_project_mismatch`; existing route preserved |
| Pinned request cancelled/expired/missing | `enrollment_not_pending`; no cwd fallback |
| Pinned request replaced by another ID | `enrollment_selection_changed`; no connection side effects |
| No matching request and no pin | Existing manual project discovery |

### 5. Good/Base/Bad Cases

Good: console A and chat cwd B connect to A. Base: no request connects to the project discovered in cwd. Bad: returning immediately because cwd found B, allowing the model to pass a project, or swallowing a failed pending probe and joining B.

### 6. Tests Required

Exercise cwd at another project, a project subdirectory, no project, and the selected project; no-request manual fallback; another adapter's request; explicit-root/environment conflicts; manifest mismatch; existing-route conflict before identity/ticket writes; cancellation/replacement between adapter probe and connect. Adapter subprocess tests must cover the probe and connect invocations and verify sanitized output. Live DSH verification remains distinct from fixture tests.

### 7. Wrong vs Correct

Wrong: `runtime.project_id` exists, so return before inspecting DeepSeek pending. Correct: retain explicit selectors, validate the pending project when present, and use cwd discovery only when no corresponding request exists.

## Scenario: OpenCode original-chat join

### 1. Scope / Trigger

Local OpenCode console requests bind the existing original conversation regardless of cwd. Legacy ticket records and network invitations retain their paths; no bulk migration.

### 2. Signatures

- `agent prepare --adapter opencode`: install user-level credential-free entry only.
- `agent join --adapter opencode`: claim and enroll with host-provided identity; default `agent join` remains Codex.
- Host `tsunagou_connect`: empty arguments; no new daemon command, state or permission.

### 3. Contracts

The plugin passes live `ctx.sessionID` through the fixed CLI child's `TSUNAGOU_HOST_CONVERSATION_ID`, cleans inherited host/project identity and forces UTF-8. CLI matches adapter, project manifest, role and route before claim; no cwd fallback. OpenCode routes live under `hosts/opencode`; native MCP supplies `ai.opencode/sessionID` on every call. New local prepare saves a request without daemon startup or ticket issuance. Shared route receipt handling must not enable Codex wake for OpenCode.

Arrival requires the exact original-call receipt and fresh matching Agent/role/epoch on every polling endpoint. CLI helper reads never satisfy arrival. Same-chat retry preserves ownership. Reuse existing store locks and lifecycle; project config/legacy-binding conflicts are explicit, never silently overwritten.

### 4. Validation & Error Matrix

| Condition | Result |
|---|---|
| No matching request or missing real identity | Error before claim; no project initialization |
| Foreign route, manifest, old binding or role conflict | Refuse before issuing credentials |
| Another conversation owns request | Existing claim-owner rejection |
| Missing or stale original-call receipt | Waiting, never arrived |
| User config or plugin conflict | Prepare fails without overwriting user content |

### 5. Good/Base/Bad Cases

Good: unrelated cwd joins the console-selected project and role. Base: initial installation requires one reload, then later joins only add routes. Bad: fabricate a session name, reuse another conversation's credential, or equate helper enrollment with arrival.

### 6. Tests Required

Extend console join/store, registration, bridge receipt and real-daemon integration tests for OpenCode; retain Codex/DSH regression coverage. Host tool subprocess tests assert trusted identity, empty arguments, cleaned environment and sanitized results. Live host evidence must separately prove matching plugin/MCP identities, reload continuity and real CLI/daemon/bridge arrival; document whether the model driver is a controlled fixture.

### 7. Wrong vs Correct

Wrong: derive the selected project from cwd or mark arrived when CLI reports enrolled. Correct: match and claim the console request, then require a successful original native MCP context and exact receipt.
