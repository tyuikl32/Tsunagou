# Live acceptance deviations

Append each trigger, observation, cause, fix and retest with UTC times. Keep failed automatic wake attempts when a developer or user later follows up.


## 2026-09-28T19:13Z–19:51Z — A4 原 owner 恢复后未执行 stale Attempt 探针

- **Trigger:** daemon restarted in the existing local state directory; main and original Worker bridge were reopened. Main sent a persistent message asking the original owner to recover its existing Task/Attempt, then main explicitly recovered that Attempt as `reopen` and requested one old-Attempt submit check.
- **Observed:** the Desktop wake reached the original Worker. Its `task.begin(expected_task_revision=5)` succeeded and preserved the same Task/Attempt and revision. Main recovery committed at event seq 242, changed Attempt `running → orphaned`, and reopened Task at revision 6. The Worker then read and ACKed the stale-submit request but did not call `task.submit`.
- **Cause:** the Worker treated an earlier request to exit the previous bridge as still binding after the same conversation had later rejoined the current live project. Repeated durable messages did not change that interpretation. No submit Result was written. The Worker stopped its turn, but CLI and current main MCP showed its project Agent still `ready`.
- **Impact:** A4 proves daemon wake after restart, same-owner/same-Attempt `task.begin` recovery, and main recovery state transition. It does not prove that the original owner is rejected when submitting the orphaned Attempt. A4 remains `not_run`.
- **Follow-up:** preserve the gap. Do not impersonate the owner or infer stale-owner rejection from a different Agent's `wrong owner` response. Provide a current, unambiguous exit/rejoin lifecycle and expose the registered `agent.retire` operation through an authorized user/CLI/MCP path; repeat the stale-submit assertion only with the original owner identity and a current instruction.
