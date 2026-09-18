# Adapter and TypeScript guidance

Status: approved design, no adapter implementation yet. Sources: [adapter plan](../../../docs/implementation/adapters.md), [wire protocol](../../../docs/implementation/protocol.md), [runtime prompts](../../../docs/implementation/runtime-prompts.md).

## Pre-Development Checklist

Read the T02 verified host/version matrix before coding a host adapter. Require reliable host_conversation_id across resume/compact and distinct IDs on new/clear/fork. Unknown identity cannot become ready. Read the active task and shared bridge contract.

Read the [subagent onboarding guide](../../../docs/overview/subagent-guide.md) and [coordination trace](../../../docs/implementation/coordination-walkthrough.md). Host-native subagents do not automatically become Tsunagou members; enrollment must prove a distinct conversation and session. CLI issues tickets as user_control, while the selected bridge redeems them through the ticket bootstrap path.

## Implementation rules

Use strict TypeScript, ESM/NodeNext and workspace:* dependencies. bridge-sdk owns auth injection, command IDs/retry/dedup, typed clients, inbox, epoch recovery and prompt rendering. Host adapters translate official lifecycle/tool surfaces; no duplicate task state machines or private DTO forks.

Tokens remain in private bridge memory/user-only files, never model tool arguments, prompt, command args, env or static MCP config. Shared project MCP still authenticates each HostSession separately. stdio forwarders are per-session.

Capabilities are supported/unsupported/unknown with evidence and advisory/observed/enforced strength. Never infer that configured hooks are enabled. Preserve mandatory identity/auth/blocker prompt fragments. No wake is an allowed enhancement downgrade; no reliable identity is a baseline failure.

## Quality Check

Run common Vitest/simulator conformance, cross-language schema fixtures, secret isolation and real host lifecycle tests. All 11 baseline capabilities must pass per host/version. Save sanitized evidence, install/uninstall instructions, unsupported enhancements and exact dependency versions.
