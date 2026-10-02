# Codex console one-line enrollment

User approved the feasibility proposal and implementation on 2026-10-02.

## Requirements
- In a Codex Desktop conversation, saying "请接入 Tsunagou" joins the one current console enrollment without entering project root or role.
- The console selection supplies immutable project/role; the actual conversation supplies its verified thread identity.
- No pending intent means a clear error, never project initialization or implicit worker enrollment.
- Same-thread retry preserves identity; a second thread cannot consume the same intent.
- Completion matches the bound conversation and requires an original-host context-read receipt, not the CLI helper.
- Preserve user HTML/CSS, existing permissions, other host flows, and Git state. The implementation phase excluded commit/push; the user authorized local commit and GitHub tsunagouDev delivery on 2026-10-02.

## Acceptance
Cover different cwd, main/worker, cancellation/expiry, concurrent claims, repeated join, restart persistence, precise arrival, bootstrap exclusion and existing loaded shared bridge. Run targeted checks and tools/dev/check.ps1. Actual Desktop validation is separate from fixtures and must be reported honestly.
