# Design

## Boundary
The missing behavior is the connection between a committed user completion command with a successful checkpoint and the daemon's existing shutdown lifecycle. Domain handlers must not kill processes. The bootstrap daemon owns registration and server lifecycle; the existing maintenance loop owns deferred checkpoint progress.

Expected implementation areas: dispatcher/HTTP response boundary to associate the successful completion and its operation; existing maintenance/checkpoint status plumbing for delayed success; bootstrap daemon and CLI launch entry for process-owned graceful exit. Change only these areas as needed, plus focused tests, spec and user documentation. Do not add a second domain state machine or lifecycle service.

## Contract
- Associate only completion commands received during this daemon run with their exact checkpoint operation, after successful durable dispatch. Do not infer eligibility from completed project state alone or a genesis/unrelated checkpoint.
- Keep this tracking process-local. Observe delayed success using existing maintenance, without another service/thread. Failure leaves the existing retry path usable; retry of the tracked operation can later trigger exit.
- Gate exit on the confirmation response having finished sending. Avoid treating the mere completion of a sync route function as response delivery. Consider failures/disconnects and retries without invalidating the durable command.
- The daemon coordinates on its asyncio event loop. Reuse its registration lock for final single-project verification and the closing transition. Once closing, reject further project registration through the existing registration error contract. Shared daemons skip automatic shutdown regardless of completion state of members.
- A bootstrap runner owns uvicorn.Server and exposes an internal callback setting should_exit. Request orderly shutdown once; reuse per-project lifespan cleanup and keep CLI isolation, environment, host/port, logs, endpoints and manual stop semantics.
- No new public command, route, or response field; no migrations. Test seams may inject callbacks.
- Startup does not scan historical completion operations. Explicitly restarting a completed project therefore does not immediately shut it down.

## Validation
Prove response/registration ordering using deterministic barriers, checkpoint failure then retry with real storage, denied/stale/replay behavior, shared daemon preservation and a real Windows process test that observes PID exit and rebinds the released port. Existing checkpoint, maintenance, CLI launch and multi-project tests must pass. Preserve framework-factory use for tests if feasible; the supported CLI launcher must use the server-owning runner.
