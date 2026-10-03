# Adapter and TypeScript guidance

Status: shared bridge and diagnostic adapters are implemented. Existing Codex/OpenCode acceptance remains unchanged. The DeepSeek Harness 0.2.0-rc.2 ordinary Desktop onboarding repair passed live acceptance on 2026-10-02; release-gate status remains unchanged. Use the [single acceptance report](../../../docs/acceptance/deepseek-harness-11-baseline-2026-10-01.md) for evidence and retained limitations.

Host fact proven on OpenCode v2.0.18: local MCP servers receive no session env vars; the host conversation id arrives per tool call via `_meta["ai.opencode/sessionID"]`. Bridge identity for such hosts must be derived from that field, and a project-shared bridge must keep one private session file per conversation.

Host fact observed on DeepSeek Harness 0.2.0-rc.2: the stock MCP client supplies no per-call conversation metadata; the existing host identity provider adds it from `exec.agent.session.id`. A private overlay alone does not prove caller identity. The 2026-10-02 authorized Desktop repair uses a credential-free shared provider entry and a separate private route for each real conversation. The local `tsunagou_connect` action takes its directory from `exec.agent.session.header.cwd`; model arguments never supply identity, commands or credentials. DeepSeek routing must not invoke Codex Desktop wake/binding recovery. Original-chat context, not helper enrollment, establishes readiness. Test helpers must reuse `tools/conformance/probes/common.py` and the existing host probe rather than maintain another baseline framework.

## Pre-Development Checklist

Read the T02 verified host/version matrix before coding a host adapter. Require reliable host_conversation_id across resume/compact and distinct IDs on new/clear/fork. Unknown identity cannot become ready. Read the active task and shared bridge contract.

Read the [subagent onboarding guide](../../../docs/overview/subagent-guide.md) and [coordination trace](../../../docs/implementation/coordination-walkthrough.md). Host-native subagents do not automatically become Tsunagou members; enrollment must prove a distinct conversation and session. CLI issues tickets as user_control, while the selected bridge redeems them through the ticket bootstrap path.

## Implementation rules

DeepSeek's CLI subprocess environment must set `PYTHONIOENCODING=utf-8` after merging inherited and configured environment values, because the provider decodes stdout as UTF-8. On Windows, CP936 JSON output otherwise corrupts non-ASCII pending project paths before they enter the connect arguments. Keep project/role/route validation strict; switching path transport does not repair already-corrupted JSON. Regression tests must exercise real Python stdout with a CP936 input environment and Chinese/space-containing paths, not only Node CLI doubles. This is an automated encoding contract, not evidence of original Desktop readiness.

DeepSeek native connect must query the installed CLI's `agent pending --adapter deepseek` before connecting. A matching request supplies `--project-root` and the hidden `--pending-enrollment-id` to `agent connect`; only no request permits cwd fallback. Keep identity/cwd host-derived and all project paths model-inaccessible. Python revalidates the request and private conversation route before creating bridge material. See [project-selection contract](../backend/entrypoint-contracts.md#scenario-deepseek-console-project-selection).

Use strict TypeScript, ESM/NodeNext and workspace:* dependencies. bridge-sdk owns auth injection, command IDs/retry/dedup, typed clients, inbox, epoch recovery and prompt rendering. Host adapters translate official lifecycle/tool surfaces; no duplicate task state machines or private DTO forks.

Tokens remain in private bridge memory/user-only files, never model tool arguments, prompt, command args, env or static MCP config. Shared project MCP still authenticates each HostSession separately. stdio forwarders are per-session.

Capabilities are supported/unsupported/unknown with evidence and advisory/observed/enforced strength. Never infer that configured hooks are enabled. Preserve mandatory identity/auth/blocker prompt fragments. No wake is an allowed enhancement downgrade; no reliable identity is a baseline failure.

## Quality Check

Run common Vitest/simulator conformance, cross-language schema fixtures, secret isolation and real host lifecycle tests. All 11 baseline capabilities must pass per host/version. Save sanitized evidence, install/uninstall instructions, unsupported enhancements and exact dependency versions.

## Scenario: authenticated replay across reconnect

### 1. Scope / Trigger

This contract applies when bridge command deduplication, retry, connection epoch, inbox delivery, or capability evidence changes. It prevents a cached result from bypassing current credentials and prevents an unknown external result from being executed twice.

### 2. Signatures

- `BridgeClient.send<T>(envelope: CommandEnvelope, kind?: CommandKind): Promise<T>`
- `BridgeClient.reconnect(connection: BridgeConnection): boolean`
- `BridgeClient.pullInbox(source, cursor?)`, `markInboxPresented(...)`, `ackInbox(...)`

### 3. Contracts

- Within one connection epoch, the same `command_id` plus canonical protocol/schema/kind/payload fingerprint may share an in-flight or completed result; changed input returns `idempotency_conflict`.
- A higher connection epoch clears completed local results. A replay must reach the authoritative transport with the new epoch and current credential; server-side idempotency returns the original result.
- A higher epoch also detaches old in-flight promises. An epoch-1 completion after reconnect must reject as `stale_connection_epoch`, never populate epoch-2 completed results; its cleanup must not delete the epoch-2 in-flight entry for the same command ID. An old retry must not silently use the new credential/epoch.
- Inbox claim, body fetch, presentation evidence, and ACK remain distinct and recipient-scoped. ACK requires a successful presentation record.
- Capability evidence is a non-empty sanitized reference. `supported` with missing or empty evidence remains not ready.

### 4. Validation & Error Matrix

- lower epoch or different session -> `stale_connection_epoch`
- old in-flight result or retry after a higher-epoch reconnect -> `stale_connection_epoch`; same ID may be retried separately through epoch-2 transport
- same epoch with changed capabilities -> `connection_epoch_conflict`
- reused command ID with changed fingerprint -> `idempotency_conflict`
- typed 4xx, unknown error, or unknown external result -> no automatic retry
- explicit 429/503, queue/transient code, or recognized connection-reset/timeout -> bounded retry

### 5. Good/Base/Bad Cases

- Good: same command is coalesced within epoch 1; after reconnect to epoch 2 it reaches transport once with epoch 2 and receives the authoritative replay result.
- Base: identical reconnect response returns `false` and does not rotate state.
- Bad: returning epoch 1's local cached success after epoch 2, retrying `unknown_external_result`, auto-ACKing on fetch, or accepting `evidence: ""`.
- Bad: preserving the epoch-1 in-flight promise so an epoch-2 caller receives its response without new transport authentication.

### 6. Tests Required

- Assert concurrent identical commands call transport once and changed payload conflicts.
- Assert post-reconnect replay calls transport with the new epoch.
- Hold the epoch-1 transport response, reconnect, send the same command in epoch 2, then release epoch 1 first: the old call rejects, the new call remains coalesced with its own duplicate and caches only epoch-2 result.
- Assert typed/unknown failures are not retried and explicit transient failures are bounded.
- Assert fetch/presented/ACK ordering and duplicate suppression.
- Assert empty evidence leaves every claimed capability missing.

### 7. Wrong vs Correct

```typescript
// Wrong: old local success bypasses epoch-2 authentication.
bridge.reconnect(epoch2);
return completed.get(commandId);

// Correct: clear completed local results; preserve the fingerprint and let the
// authoritative service fence epoch 2 and deduplicate the command ID.
bridge.reconnect(epoch2); // clears completed results
return transport.send(envelope, { connectionEpoch: 2, authorization });
```


## Local DSH console association

The existing pending-enrollment-id connects the validated DSH CLI result to the local
console request. Keep the record pending until a fresh roster shows that exact active
Agent with the requested role and ready session. Never infer local arrival from baseline
membership. New local/network requests record their place; legacy records retain their
existing behavior until an original-chat retry explicitly links a local DSH result.
Codex receipts, OpenCode, and network roster attribution remain separate. Repeated links
are idempotent; wrong project/role/Agent and terminal records cannot be overwritten.

## OpenCode original-chat onboarding

OpenCode local console onboarding uses a user-level credential-free plugin and native MCP entry, with private routes per actual conversation. `agent prepare --adapter opencode` installs once; after the initial reload, joining adds only a route. The zero-argument host tool obtains identity from the live execution context and calls the installed `agent join --adapter opencode`; models cannot supply identity, project, role or commands. Do not clone the DSH MCP transport: OpenCode supplies `ai.opencode/sessionID` natively. Keep Codex wake independent of generic receipt handling.

Installed OpenCode 2.0.18 uses a directory plugin exporting `{id, setup(api)}`, `api.tool.transform`, plain JSON Schema input and `execute(args, ctx)` returning MCP content; identity is `ctx.sessionID`. Upstream dev/v1 plugin examples are not evidence of this installed API. Original-chat readiness requires its successful MCP context and exact receipt, excluding the CLI helper. Legacy project bindings and user config conflicts fail explicitly; no bulk migration or fabricated replacement identity. See the [decision](../../../docs/decisions/2026-10-03-opencode-original-chat.md).
