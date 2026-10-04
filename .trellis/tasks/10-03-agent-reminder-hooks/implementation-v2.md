# v2 concrete implementation choices

## Authentication and PowerShell entry
Plain PowerShell invocations cannot authenticate an OpenCode/DSH caller's original host conversation. Do not emit sender IDs, credential paths or transferable bearer intent handles as a substitute. The executable entry is the explicit authenticated MCP command `coordination__wake` with its already-filled message_id. The backend then invokes a fixed packaged PowerShell helper using trusted internally resolved target/session data. `coordination__wake_status` is the read/check entry. The hook never invokes wake automatically. This is the minimum implementation of the approved PowerShell flow without new per-host caller-identity plugins.

## Boundaries
Backend worker owns command registration/validation, message authorization, local host resolution, existing native lane fencing and minimal per-message durable execution records. Bridge worker owns compact extra content, first-guide/delivery-state presentation dedup, host runner and fixed packaged PS wrapper. No change to original Codex provider behavior.

External host checks and execution happen outside SQLite write transactions. Current authenticated session and capability are fenced before processing; status is refreshed rather than replaying stale observations. A durable unknown/inflight record precedes externally visible execution. Same message cannot be driven twice after timeout/crash; observation determines subsequent disposition.

## Verification scope
Installed OpenCode v2.0.18 has `run --session`, `--server`, `--format json`; `--auto` is auto-approval and excluded. Exact current host status API must be locally inspected; historical v1 probe endpoints are not proof for v2. DSH unsupported forms are accepted downgrade, no generic Desktop assumptions. Live evidence must separate actual host running from mock protocol/authority fixtures; no unauthorized enrollment of an active project conversation.

## Final verified host entry
The runner uses installed `opencode api` without `--server`: direct localhost HTTP failed authentication, and specifying a server bypasses the managed CLI's credential discovery. It checks CLI and `/api/info` version 2.0.18, then GETs the bound original session, its actual location, active map and only its deterministic input. A missing original session never triggers creation. Prompt admission uses `delivery=queue`, `resume=true`; no approval change. A delivered input is not correlated execution evidence, so `turn_started=false` means unproven, not proof that a turn never ran.

`peer_hosts` and `wake_candidates` provide safe discovery/correlation alongside the two explicit message entries. All four use existing capabilities. The latter correlates task submission's source command because its unchanged business JSON has no message ID.
