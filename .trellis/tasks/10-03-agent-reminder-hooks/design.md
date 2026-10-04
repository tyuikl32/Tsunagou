# Design

The authoritative scope is [approved-v2.md](approved-v2.md); concrete tradeoffs are in [implementation-v2.md](implementation-v2.md).

## Presentation
Shared bridge rules append text after unchanged business JSON. Authenticated context supplies current main identity. A private project/Agent/version record survives bridge restart; message/state fingerprints suppress repeated incidental hints. Explicit status queries stay fresh. Static context and MCP instructions point to the guide.

## Authenticated explicit operation
coordination.peer_hosts provides safe host facts. coordination.wake_candidates correlates successful business commands to concrete authorized recipients. coordination.wake_status observes one authorized message; coordination.wake explicitly invokes the packaged PowerShell-backed runner. The hook never invokes wake. Raw shell calls cannot prove the initiating conversation, so MCP authentication is retained instead of exposing credentials or transferable intent tickets.

The backend verifies current grants, message association, target binding and private local route records. It exposes no recipient inbox, raw host conversation ID, endpoint or credential. Host I/O occurs outside SQLite write transactions. Shared recipient serialization and a durable per-message reservation fence native and fallback operations. Unknown outcomes require observation, not repeat dispatch.

## Routing and evidence
Codex to Codex returns only the native lane. Other verified local combinations are eligible only when an existing lane does not own delivery. OpenCode requires the installed verified version and a proven original session. Host session location is distinct from the coordination root, supporting worktrees. Unverified DSH forms return unsupported.

Runtime state and queue support are independent. Queue admission, turn start, presentation and related reply are separate facts. No last-active-time inference or interpretation of conversational completion.

## Main reminder and failures
Compare agent_id and main_agent_id from current authenticated context. Context reads and successful review/self acceptance retain conditional completion proposal guidance for each project's main. Internal role lookup does not write console arrival receipts. Workers receive no directed completion proposal instruction; user confirmation is unchanged.

On failure verify host, version, machine and original session first. Observe unknown outcomes; stop unsupported paths. Workers escalate unresolved evidence to main once; main retains blockers without requiring manual user wake. Existing native provider behavior and project switches remain unchanged. Bootstrap refresh updates generated context; long instructions stay in docs and stable operations in scripts.
