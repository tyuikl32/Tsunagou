# Real acceptance follow-up: Windows runner diagnostics

## Evidence and scope
User forwarded actual hook-v3 collaboration evidence. Codex native delivery completed with daemon_delivery requested/accepted/started/completed observations; worker3 claimed the original task. OpenCode peer wake failed with host_runner_failed during status/wake and produced no business response. DSH returned the agreed unsupported downgrade. Main did not falsely propose completion.

The observed daemon PID 27312 started 2026-10-04 16:10 Asia/Shanghai, before the 17:14 default-on/native-status commit 7b57214. It was not restarted. Thus the old native_channel_only/false/empty evidence response is not evidence that the new native projection failed. No claim is made about which PowerShell executable that historical process selected: old results did not record it.

## Smallest repair
Make the packaged fixed PowerShell script work on both supported interpreter paths (Windows PowerShell 5.1 and PowerShell 7). Add safe fixed-field runner diagnostics, forward them through the authenticated message query and include concise failure-stage guidance. Stop repeated failing-path advice; unknown admission outcome requires inspection, never blind resend. No new scheduler, retry state machine, host binding, model change or project enrollment.

Ownership: runner implementation agent owns host_wake_runner.py/.ps1 and runner tests; presentation implementation agent owns wake_assistance.py, reminders.ts and their tests. Parent owns task/spec/docs and Git. Preserve successful native mechanism and prior default-on policy; no live daemon restart during this code repair.

## Verification
Actual installed 5.1 and 7 interpreters must parse and execute the fixed script against a controlled mock host, including Unicode input/paths where applicable. Cover subprocess spawn/nonzero/parse/JSON/timeout diagnostics and confirm no credentials, session IDs, endpoints, paths or raw stderr are exposed. Verify diagnostics survive authenticated query output; errors do not recommend repeated wake/status loops. Existing main completion reminder behavior stays unchanged.

Independent code review, relevant Python and actual stdio reminder tests, type/lint, packaging and docs checks. Real OpenCode business response still requires a fresh original-session retry after runtime reload; do not call the repair itself live acceptance.

## Repair evidence
36 runner tests passed: actual Windows PowerShell 5.1.26100.6584 and PowerShell 7.6.5 each exercise 12 scenarios through an npm-style PowerShell shim, a native CLI double and mock HTTP. This exposed and fixed legacy JSON quote/space loss that a PowerShell-only fixture missed, alongside BOM-less parsing and native stderr handling. Exact decoded POST content and Unicode/space paths are asserted. 30 service and 3 real stdio reminder suites passed, including idle followed by failed preflight with no wake call. Safe diagnostics survive query/replay; no prior attempt permits an explicit preflight_failed flag, while uncertain prior/actual admission never does.

Targeted lint/type checks, workspace type checks, docs validation and rebuilt wheel runner-byte comparison passed. No daemon/bridge restart, user project mutation, live wake or enrollment occurred. Historical interpreter selection remains unknown; original live failure root cause is not retroactively asserted.
