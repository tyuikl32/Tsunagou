# Default native wake follow-up — 2026-10-04

User explicitly approved default-on automatic wake and related hook fixes, then lifted the source/Git restriction. This decision overrides earlier requirements to preserve the absent-setting default; explicit user false remains respected.

## Boundary
The observed gap is that a new project stores empty settings and never dispatches its pending Codex wake intents. Change effective project policy at its existing runtime/context/control readers: missing means enabled; explicit false means disabled. Existing provider support, identity/binding checks, wake-worthy events and duplicate protection remain in force. No new scheduler, automatic mode enum, enrollment, or cross-host support is added.

Hook native-channel guidance must distinguish routing from execution. It must not imply that a wake is already dispatched or prohibit normal native processing. Unproven host-turn evidence means unknown, not proof of no execution. Use existing native policy/outbox/attempt evidence where available, without external side effects from status queries.

## Verification
- Empty/new and persisted older empty settings: native delivery enabled and visible settings agree.
- Explicit false: remains disabled across persistence/restart; no forced enabling.
- Existing binding/unsupported-host/duplicate checks remain effective.
- Native hint does not claim successful scheduling from native_channel_only; reports observed pending/failure/unknown honestly.
- Relevant Python/runtime and real stdio reminder tests, type/lint, docs validation, independent review.

No live daemon restart or automatic backlog delivery is implied by source implementation. Deployment state must be reported separately.

## Implementation and verification outcome
Implemented centralized `Project.automatic_wake_enabled`; missing true, explicit false retained without rewriting settings. Native delivery, Agent context and control snapshots share this policy. Original provider implementation remains unchanged. Native status adds sanitized policy/outbox/attempt evidence; positive turn proof requires same-message `turn_started` plus digest and excludes coalesced aliases. Route-only and missing evidence do not imply execution or inactivity. Guide version bumped so corrected instructions are shown once.

Implementer/reviewer: 53 relevant Python cases passed, 1 existing symlink-environment skip; final wake-assistance rerun 28 passed after correlated evidence correction. Three real stdio reminder suites passed. Targeted Ruff, mypy across 95 source files, workspace TypeScript checks and docs validator passed. First-dispatch Desktop fixture now leaves settings empty rather than explicitly enabling wake. Independent review found no remaining blocking product-code issue.

Source/build verification does not prove live host acceptance. No active daemon was restarted, no project setting rewritten, and no real project completion claimed. Already-running daemon/bridge processes require loading the new build before the default and corrected hints take effect. Existing live collaboration acceptance remains open.
