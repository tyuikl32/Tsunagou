# Completion-triggered exclusive daemon shutdown

## Approved requirement
The user approved implementation of the plan in this chat and explicitly consented to this Trellis task. After the user confirms project completion, the corresponding checkpoint succeeds, and the confirmation response is sent, automatically stop that project's exclusive daemon. Preserve completion authorization and persistence semantics.

## Acceptance
- A real single-project daemon returns the complete successful confirmation response, exits, and releases its listener and process resources.
- Pending/failed completion checkpoint keeps the daemon running; successful retry of the corresponding operation during this run permits shutdown.
- Multi-project daemons never automatically stop because of a completion confirmation.
- Unauthorized, denied, stale or conflicting commands do not trigger shutdown; replay cannot duplicate shutdown.
- Project attachment cannot race past shutdown eligibility and get interrupted.
- Existing start parameters, Windows process isolation and manual stop keep working.

## Non-goals
No idle timers, automatic shutdown of all-completed shared daemons, historical process cleanup, changes to console browsing/autostart, public command/API/schema additions, or scan-and-exit on daemon startup. Previous broader product decisions were explicitly revoked.
