# Implementation plan — v2

Current follow-up: [default-wake-followup.md](default-wake-followup.md). User approved default-on for missing settings, preserving explicit false, and authorized source edits and Git submission.

- [x] Narrow authenticated message-query and explicit PowerShell invocation contract.
- [x] Backend current message/grant/host identity validation, independent progress facts and native/fallback fencing.
- [x] Version-gated OpenCode status/wake, original-session checks, DSH unsupported downgrade.
- [x] Shared bridge persistent guide/state dedup and compact hints; existing main completion reminder preserved.
- [x] Protocol, wheel packaging, controlled real OpenCode original-session test and regression checks.
- [x] Independent review, current docs/spec and evidence records.

Scope: [approved-v2.md](approved-v2.md). Concrete choices: [implementation-v2.md](implementation-v2.md). Results: [implementation-progress.md](implementation-progress.md).

Real host execution reached the default model, which returned provider.auth 403; no business response or live enrolled-project closure is claimed. DSH remains explicitly unsupported. No Git commit, deployment or project bootstrap refresh performed. Task retained for review; code delivery is not a user-confirmed project completion.

Rollback must include the new explicit commands, schemas/generated mappings and host runner as one coherent change. Private per-message execution records must not be deleted to manufacture retry eligibility after an uncertain operation.
