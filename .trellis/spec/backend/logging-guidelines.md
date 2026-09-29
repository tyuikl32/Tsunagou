# Logging, evidence and privacy

Source: [evaluation](../../../docs/implementation/modules/08-evaluation.md).

Use registered structlog fields: timestamp, level, event, project/lineage/command/operation IDs, reason codes, durations and digests. Do not log token/ticket, Authorization, raw conversation IDs, private message body, prompt/source code or full host config by default. Hash possession is not read authorization.

OTel is opt-in, local OTLP only. Audit/read projections preserve domain permissions; main is not an inbox superuser. Checkpoint export uses explicit shared profile and never includes usable runtime credentials/grants/leases.

Audit visibility must authorize the exact subject, change references and evidence references the projection will emit, including legacy payload fallbacks. Apply visibility before the page limit; continue scanning hidden rows to find the next visible event. Unknown private-message audiences fail closed. Bind signed cursors to the authenticated viewer, project, lineage, filters and fixed event high watermark.

FX5 compound task commands may also create a private notification. Preserve the shared primary fact and omit inaccessible ancillary message/delivery/obligation changes. Explicit evidence_refs still require authorization in full. Apply the same projection to history, individual events and exports; never grant main private inbox access.

Wake transitions pass through one diagnostic update path, including provider-returned failed without evidence, exceptions, restart unknown and coalesced messages. Diagnostics distinguish occurred_at, recorded_at and observed_at. Presentation/ACK alone has unknown trigger_source and cannot change a failed automatic wake into success. Preserve the original attempt and failure.

Before sending a new outbox notification or retrying a never-sent queued batch, inspect committed, recipient-scoped delivery ACKs. If every message in that batch is ACKed, finish only the notification with state=completed, completion_reason=messages_already_acked and wake_skipped evidence. Propagate the reason to coalesced rows; never synthesize host_accepted, turn_started, turn_completed or a turn digest. Partial ACK/presentation is insufficient. Already-sent starting/running/unknown attempts continue observing the real host, and previous failures remain in history. Read SQLite outside the dispatcher global lock; retain recipient serialization across batch inspection, provider poll and its state update.

Optional SDK tracing uses platform/telemetry.py and a local HTTP OTLP endpoint; five boundaries only. Persist traceparent in the committed event payload and recover it through outbox.event_seq for the executor thread. The context is not an authorization credential. Do not trace secrets, raw host IDs, exception text or read-only context calls; keep core diagnostics functional without the extra. See [query and tracing guide](../../../docs/overview/diagnostics-and-tracing.md).

Store new audit times as server UTC integer milliseconds and serialize RFC3339 UTC with three fractional digits. Preserve unknown historical timestamps as null. Reject malformed timezone offsets and UTC conversion overflow as input errors. Read-only queries and idempotent retries must preserve event and entity timestamps/revisions.

Use secret sentinel tests through failed requests, exception logs, access logs, JSON CLI, telemetry and exports. Missing token usage is unavailable, not zero. Do not request or store hidden chain-of-thought.

Workspace observation is scoped to the task's registered roots and relative paths. Hash the complete admitted tree and Git index mode/blob/stage, not status labels alone. Porcelain v1 `-z` renames carry destination before source; account for both without reading outside scope. Use literal pathspecs and disable ext-diff/textconv/fsmonitor. Exclude private path segments and the artifact store even if Git tracks them. Links, reparse points and exceptional files remain observation-only; do not feed them back into Git diff to read their targets. Preserve their kinds/digests in the result so a link-only result can be submitted without an unsafe patch.

Artifacts use independent domain references over content-addressed blobs. Never treat a hash, main role or shared physical bytes as authority for another domain or private recipient. Reads and caller-supplied references verify project/lineage/owner/scope and blob digest; deduplication must verify an existing blob before reusing it. Workspace observation evidence does not upgrade worker-reported tests or commit claims. Persist validation times, exact tool/version digest and output hashes; reject raw text in digest fields.
