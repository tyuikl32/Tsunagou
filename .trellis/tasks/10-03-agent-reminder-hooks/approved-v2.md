# Approved v2 — 2026-10-04

User explicitly requested IMPLEMENT THIS PLAN, superseding v1 repeat-reminder behavior. Complete approved contract follows; this file is authoritative over older PRD/design/implement statements.

## Routing and identity
Hook temporarily fills gaps in existing wake coverage; sender explicitly executes, no new automatic scheduler. Agents first read and remember peer Agent ID, actual host type/version/machine/evidence, not nickname/model brand/caller host. Verify current binding before execution; missing/conflicting facts require verification.
- Codex -> Codex: existing Tsunagou Codex channel ONLY, no fallback command, no extra wake, preserve project switch, binding checks and retries. Failure cannot automatically switch path or enable policy.
- Cross-host and OpenCode->OpenCode / DSH->DSH: verified fallback if existing channel does not cover it. Check no native in-flight/pending dispatch before fallback to avoid duplicate paths.
- Unknown host: status/identity verification only. Cross-machine: unsupported in v1, explain and escalate main.

## Reminders
- First successful authenticated Agent context read: full guide plus host-info entry, persist guide version per Agent so bridge restart doesn't repeat. New version shows once.
- Later compact hints ONLY targeted assignment, response-required messages, worker submit needing main review, or explicit check detecting not running/failure.
- response_contract.required decides response need; no natural language heuristics.
- Ordinary queries/ACK/obligation closure/review no wake long text. Untargeted task publish no guessed recipients.
- Same message/same state not repeated; explicit queries always fresh.
- main/worker equal eligible senders, directly operate within authorization; escalate main only if cannot resolve. Existing main-only completion reminder and user confirmation remain.

## Status / executable entry
Thin authenticated message-scoped query returns allowed target host facts, state evidence, delivery progress and executable local entry, not private inbox/chat. Original tool JSON unchanged; extra MCP content only.
- idle only from positive current host proof, running only from actual active turn; same-request claim requires association evidence.
- can_queue separate capability, unknown if unproven. Unknown state -> fixed status check, not infer from heartbeat/last activity.
- same request running -> no new turn; other running -> queue only if supported and allowed.
- PowerShell command prefilled message reference. Trusted script privately resolves sender/recipient/original-session maps, no secret/endpoint/session-file copied into model commands. Limited to current project, existing target and caller-associated message; system assignment/submit origin must correlate actual sender.

## Stable scripts / failures
OpenCode and DSH stable status/wake entries, current installed launchers only, common compact JSON host/version/state/queue/result/time/error evidence.
- OpenCode current verified version: prove original session exists BEFORE drive (CLI --session can create new); no --auto or permission change.
- DSH Desktop/Web/TUI distinguished; unsupported version/form yields explicit unsupported+reason+escalation. This downgrade is explicitly accepted.
- No UI automation, installs, Codex wake changes.
- Per-message serialized execution; accepted/unknown result first inspect, no blind retry. Minimal local operation record, not a second task state machine.
- Failure first recheck target host/vendor, version/machine/session/entry. Correct based on new evidence. Unsupported stops path; preserve error and escalate main once. Do not ask user manual wake. Main records own blocker without self-message loop. No automatic configure/probe/rebind rabbit hole.
- Four independent progress facts: message durably received by Tsunagou; actual host turn started; recipient presented/read; associated business response. Use existing message/presentation/reply evidence; ACK/queue/exit-zero do not imply other facts.

## Acceptance
Host fact refresh and model-brand mismatch; Codex-only native routing and no double dispatch; same-machine main->worker/worker->main/worker->worker; reject cross-project/unrelated-message/stale identity/cross-machine fallback. First-guide dedup across restart, quiet ordinary calls, all idle/busy/queue/unknown/timeout/unsupported/concurrency cases. Mock-host abnormal tests plus controlled real OpenCode original-session worker direct wake; DSH verified forms real or downgrade acceptance. Protocol/policy/schema/CLI/MCP/script packaging/docs updated. No git commit/push asked. Existing active project identities must never be fabricated/enrolled; disposable host test sessions are not enrolled project Agents. Tell parent any live test authorization ambiguity before creating enrollment.

## Implementation coordination
Backend/protocol: implement_reminders. Bridge/scripts/template/CLI: enhance_wake_guidance. Parent: artifacts/spec/docs and live acceptance. Review: check_reminders after code ready. Agree contract before broad edits. Native workers share cwd, no reverting others. Old hook commits already in HEAD; do not revert them globally.
