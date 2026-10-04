# On-demand coordination guidance and explicit local wake

## 1. Scope / Trigger
Shared bridge guidance is presentation-only. Explicit authenticated status/wake commands fill same-machine gaps, not a second automatic scheduler. Codex-to-Codex stays on the existing Tsunagou native lane; completion proposal/user-confirmation boundaries remain unchanged.

## 2. Signatures
`coordination.wake_status` and `coordination.wake` take only `message_id`; MCP maps to `coordination__wake_status` / `coordination__wake`. Caller comes from current authentication, never arguments. Original business tool JSON stays `content[0].text`; hints are additional text. Execution entry is an explicit authenticated tool, then trusted packaged PowerShell runner, not a credential-bearing model shell command.

Native status includes a safe `native` summary of effective `enabled`, `outbox_status`, `attempt_count`, `attempt_state` and `error_code`; missing records stay unknown. `progress.host_turn_started` is nullable on the native path: null means unproven. A positive value requires actual correlated execution evidence, not mere routing or queue admission. No raw provider record is exposed.

## 3. Contracts
- Peer host evidence uses real local route/session registration and observed host facts. Model brand/nickname/caller host never determine recipient host; unknown/conflicting/stale binding fails closed. Raw host IDs, paths to credentials, endpoints and tokens stay private.
- Sender-authorized direct/system message only; main is not inbox superuser. Same-machine execution only, no new enrollment or scope expansion.
- Persistent guide-version presentation is per authenticated project/Agent; restarts do not repeat it. Changed guide version may show once. Dedup same message/state; explicit status always fresh.
- Later hints: targeted assignment, response_contract.required messages and result submission needing main. Ordinary query/ACK/obligation closure/review do not append wake hints. No natural-language response detection or untargeted publish inference.
- Native Codex lane respects existing policy and dispatch. Native pending/inflight/unknown work prevents fallback; same recipient serializes across both paths. Persist external attempt before side effect, never replay unknown effects blindly. No host HTTP/process work while holding SQLite write transaction.
- Effective project `auto_wake_multi_agent` defaults to true when absent, including older persisted empty settings; explicitly saved false remains false. Runtime delivery and context/control views must agree. Do not infer host support from enabling this policy. Native lane selection alone proves neither dispatch nor execution; hints must distinguish routing and observed wake evidence, and never present missing turn evidence as proof of inactivity.
- idle/running from actual current host evidence, can_queue independent. Last activity is not liveness. Same-request running requires correlation. Check unknown state before execution; no busy interruption or approval changes.
- Four independent progress facts: message durable receipt, actual turn start, recipient presentation, associated response. ACK/exit-zero/queued is not proof of another stage.
- Explicit wake authenticates and checks message/target, then fixed PowerShell runner. DSH unsupported form is honest supported downgrade; OpenCode must prove original session exists and omit --auto.
- OpenCode 2.0.18 managed service authentication belongs to installed `opencode api`; direct HTTP and explicit --server are not interchangeable. Verify CLI and service versions, resolve the bound original session and distinguish its directory from project coordination root. No credentials in script args. A queued/delivered input does not prove an associated turn.
- Failure self-check host/vendor/session/entry first; no request for user manual wake. Stop unsupported path, escalate main once with evidence, no configure/rebind loops.
- Existing main-only completion hint uses fresh authenticated agent_id == main_agent_id. Internal identity reads must not create original-host arrival receipts. Optional hint failure does not invalidate successful business operation.

## 4. Validation / Error Matrix
| Condition | Behavior |
| --- | --- |
| Codex sender + Codex recipient | Native lane only, no fallback wake entry |
| Project setting absent / explicitly false | Default enabled / remain disabled; no automatic override of explicit false |
| Unknown/conflicting host or cross-machine | No execution; explicit verification/unsupported reason |
| Unrelated message / other project / stale identity | Reject without revealing private target data |
| Native pending/inflight or same request already started | No second host execution |
| Host status unknown / timeout | Preserve unknown; inspect before another attempt |
| DSH unverified form/version | Explicit unsupported, no fabricated capability |
| Ordinary successful query/review/ACK | No wake long text; completion hint unaffected |

## 5. Good / Base / Bad Cases
Good: worker sends required-response message, checks target, explicitly wakes verified idle peer. Base: DSH unsupported response records a blocker. Bad: raw shell takes sender credentials, duplicate native/fallback dispatch, metadata caches misidentify vendor, CLI --session silently creates replacement.

## 6. Tests Required
Real stdio tests for persistent first-guide dedup across restart, per-Agent isolation, compact trigger selection, explicit fresh lookup and completion regression. Authenticated backend tests for sender/system actor, stale session, foreign project, status distinctions, native fencing, concurrency/crash unknown and no secret leakage. Host fixtures cover versions/missing session/idle/busy/timeout/unsupported. Controlled real OpenCode original-session evidence must be distinguished from domain-auth fixtures; DSH unverified paths remain downgrade.

## 7. Wrong vs Correct
Wrong: infer recipient host from model name, or pass arbitrary sender/session-file to PowerShell. Correct: authenticated MCP message entry resolves and fences private host mapping, then runs fixed script. Wrong: repeated context reads emit full wake guide or automatically execute it. Correct: persist first-guide version and return compact advisory only when relevant.
