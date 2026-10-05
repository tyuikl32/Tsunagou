# DSH packaged background wake integration — 2026-10-05

Integrated the user-delivered zero-dependency plugin into Desktop prepare and authenticated original-session onboarding. Private managed credentials/bindings update without environment variables; plugin publishes its actual loopback endpoint. Existing message-scoped status/wake tools invoke the plugin, preserving native fencing and unknown-outcome guards. No UI, clipboard, new scheduler or duplicate queue. DSH hook instructions now point to background plugin tools; setup failure does not mean host-wide unsupported, and setup advice never replaces no-repeat advice.

Verification: combined Python suite **147 passed** (configuration, onboarding, runner, service, generated context, actual CLI integration and assembled Python → actual Node plugin → HTTP contract); plugin **30 passed**; actual stdio reminder suites **3 passed**. Reviewer passed workspace type checks, mypy across 98 source files and targeted Ruff. Docs validation and npm pack dry-run passed. Frozen pnpm installation passed after adding the no-dependency plugin importer to the workspace YAML document, with no dependency updates.

Review fixed an assertion placed in the wrong host fixture and setup text overriding unknown-result advice. See [integration design](dsh-integration.md) and [evidence boundary](../../../docs/acceptance/dsh-wake-integration-2026-10-05.md). Source distribution retains the packaged plugin alongside existing Node adapters. Existing independent plugin blocks fail with an explicit conflict rather than loading two routes.

External deliverables remain read-only. No live profile changes, Desktop restart, enrollment, real messages or wakes. External standalone live evidence proves background reply and busy dedup; the new managed-mode integration has isolated regression evidence, not new live-host acceptance. Cold restore/idle-first/reload and broader task acceptance gaps are retained; task is not archived as complete.

# Guidance simplification — 2026-10-04

Based on the user's read-only historical cross-host wake record, shortened shared reminders and synchronized generated context. Unsupported now describes the current tool path, not a host-wide impossibility. Guide includes verified historical OpenCode CLI shapes and DSH original-window evidence with current-verification conditions; no executor/UI automation or permission changes. Native lane, unknown-result fences, diagnostic facts and main completion reminder preserved. Source record SHA256 unchanged. Existing 3 stdio suites, 9 project integration tests, bridge type check, targeted Ruff and docs validation passed. No runtime reload or live wake; prior live acceptance limits remain.

# Windows runner follow-up — 2026-10-04

Real user acceptance proves Codex native wake, but OpenCode peer wake remains blocked by host_runner_failed. See [windows-runner-followup.md](windows-runner-followup.md). Fixed BOM-less PS5.1 parsing, native stderr handling and native JSON argv quote/space loss; added safe interpreter/stage/error diagnostics and preflight-only not-executed hints. Unknown admission/replay remains unknown, with no blind retry.

Runner 36 tests passed, including 12 native child-process scenarios per actual PowerShell 5.1.26100.6584 and 7.6.5 interpreter against a mock API. Service 30 tests and 3 real stdio bridge suites passed. Targeted Ruff/mypy, all workspace type checks, docs validation and wheel payload byte comparison passed. These are regression checks, not a successful real OpenCode business response. Runtime was not reloaded and no live wake was sent. Task remains open pending minimal live recheck and completion acceptance.

# Default-on follow-up — 2026-10-04

Implemented and independently reviewed; see [default-wake-followup.md](default-wake-followup.md) for behavior and test evidence. This supersedes the earlier absent-setting default. Explicit false is preserved. Live collaboration acceptance is still pending; runtime was not restarted.

# v2 implementation evidence — 2026-10-04

## Delivered
- Four authenticated coordination entries: peer_hosts, wake_candidates, wake_status, wake. No sender/session/endpoint override arguments.
- Real private host route/session binding, current grants and epochs; short committed-state snapshots with host I/O outside database locks.
- Shared recipient lock fences native and explicit fallback; durable message journal precedes side effects, unknown outcomes do not repeat. Corrupt journal fails closed.
- OpenCode 2.0.18 CLI and running-service verification, fixed packaged PowerShell runner using host-owned authentication, original session and actual directory checks. DSH forms return explicit unsupported.
- Full guide once per project/Agent/version across restart; later compact message/state reminders respect backend executable entry. Original business JSON unchanged.
- Existing main completion reminder preserved for every project's authenticated main; no automatic proposal or user confirmation.
- Command policy, request Schema, OpenAPI/generated artifacts, project context template, guide, specs and quick-start synchronized.

## Validation
Parent final combined Python run: 151 passed across wake assistance, real PowerShell mock-host runner, template, hostwake, all protocol tests, Desktop wake integration and M1 runtime flow. Existing FastAPI lifecycle deprecation warnings remain unrelated.

Parent final JavaScript run: 104 Vitest tests passed across frontend and adapters. Bridge credentials/arrival regression: 38 tests passed plus both late-ticket smoke variants. Implementer and independent reviewer also passed all 3 real stdio reminder suites (Codex/OpenCode/DSH metadata), workspace type checks, targeted Python Ruff/mypy and docs validation. Wheel built and inspected for both runner .py and .ps1. Protocol regeneration checks passed.

Independent reviewer resolved and rechecked uncommitted-state visibility, unknown machine misclassification, misleading repeated wake advice, prior-journal retry entry and formatting. No blocking code findings remain.

## Controlled live evidence and limits
See [live-opencode-evidence.json](live-opencode-evidence.json) and [acceptance record](../../../docs/acceptance/agent-wake-assistance-2026-10-04.md). Synthetic authenticated Worker identities drove one real disposable OpenCode original session: idle -> queued -> one user input and one assistant execution. Default provider returned provider.auth 403, so no business response. Repeated status/wake and an actual bearer-authenticated duplicate check returned request_already_delivered; no new user input. Not an enrolled production project end-to-end test. DSH live wake not claimed.

The attempted combined cleanup of the disposable host session and temporary directory was rejected by automatic approval review (only reason returned: blocked by policy). No bypass or deletion retry; isolated artifacts remain. No Git commit/push, active host reconfiguration, enrollment or project refresh was performed. The task remains for user review; no formal project completion proposal is issued from an unenrolled source checkout.

---

The following v1 evidence is retained only as history; current behavior is defined above and in approved-v2.md.

# Implementation evidence — 2026-10-03

## Delivered
- Shared bridge reminder rules in reminders.ts; original JSON remains first MCP content block.
- Wake guidance in MCP instructions, generated context and relevant successful coordination tool results; native exception requires both sender and recipient Codex.
- Main-only completion guidance on context reads and acceptance, using fresh authenticated identity. Internal lookup suppresses original-host console arrival receipts. Failed optional lookup preserves successful result.
- No new wake/continuation/proposal/confirmation actions; domain protocols and frontend unchanged.
- Agent quick-start and adapter spec synchronized. Existing project templates use bootstrap refresh; already-running bridge needs reload.

## Verification
Trellis implement agent ran and reported passing:
- Reminder real stdio MCP tests: 3/3 for threadId, ai.opencode/sessionID and tsunagou.hostSessionId metadata.
- Existing bridge credential/arrival/message regression tests: 39/39.
- tests/unit/test_project_integration.py: 9/9, including template parity and refresh preservation.
- Workspace TypeScript checks: all 8 packages; targeted Ruff passed.
- Bridge build output is ignored; tracked generated protocol files unchanged.

Independent trellis-check agent reviewed all changes and ran bridge TypeScript check, node syntax check on the new stdio test, targeted Ruff, mypy for project_integration.py and git diff --check: all passed; no blocking findings or fixes.

Parent ran python tools/docs/validate_docs.py: PASS (48 unchanged archived sources, 424 Markdown files, 1082 links, 1194 context entries). git diff --check passed.

## Limits and disposition
- Actual stdio process with simulated authenticated daemon responses, not three live host or frontend acceptance. No user project was refreshed or enrolled, no active bridge process restarted.
- Extra post-acceptance authenticated context query inherits existing transport waiting behavior; a slow daemon can delay successful tool output. No dedicated reminder timeout was added; review judged nonblocking for this scope.
- Source checkout has no .tsunagou/agent-context.md or enrolled runtime context; no identity was fabricated. Native Trellis helpers are not new project members.
- No Git commit/push requested or performed. Implementation/review finished; task retained for review rather than claiming committed delivery.

## Follow-up: host operation guide and failure self-check
The original hooks were committed outside this agent's work as c5edb36 (`hooks`). This follow-up remains uncommitted; no commit/push was performed by the implementation helpers or coordinator.

User requested practical host operation pointers and less reliance on incomplete Tsunagou automatic wake, then clarified failures must trigger self-investigation of misidentified host/vendor rather than asking the user to manually wake. Updated both inline/template reminder text, source-local guide path, and added docs/overview/agent-wake-guide.md with Codex/OpenCode/DeepSeek sections. OpenCode example omits historical --auto to preserve existing approval settings; DSH web evidence is not represented as universal Desktop support. Reminder rules and completion hook are unchanged.

Passing checks reported by implementer:
- `uv run pytest -q tests/unit/test_project_integration.py`: 9 passed.
- `corepack pnpm --filter @tsunagou/bridge-server test:reminders`: 3 actual stdio scenarios passed.
- `corepack pnpm run check`: passed.
- `python tools/docs/validate_docs.py` and `git diff --check`: passed.

Independent reviewer verified command/evidence accuracy and reran targeted Ruff, mypy, bridge TypeScript, node syntax and diff checks: passed with no source fixes needed. Online guide is a publication fallback; new content currently exists in local source only. No real wake, host enrollment or user-project refresh was executed; no stronger live-host reliability claim is made.
