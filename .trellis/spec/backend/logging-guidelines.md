# Logging, evidence and privacy

Source: [evaluation](../../../docs/implementation/modules/08-evaluation.md).

Use registered structlog fields: timestamp, level, event, project/lineage/command/operation IDs, reason codes, durations and digests. Do not log token/ticket, Authorization, raw conversation IDs, private message body, prompt/source code or full host config by default. Hash possession is not read authorization.

OTel is opt-in, local OTLP only. Audit/read projections preserve domain permissions; main is not an inbox superuser. Checkpoint export uses explicit shared profile and never includes usable runtime credentials/grants/leases.

Audit visibility must authorize the exact subject, change references and evidence references the projection will emit, including legacy payload fallbacks. Apply visibility before the page limit; continue scanning hidden rows to find the next visible event. Unknown private-message audiences fail closed. Bind signed cursors to the authenticated viewer, project, lineage, filters and fixed event high watermark.

Store new audit times as server UTC integer milliseconds and serialize RFC3339 UTC with three fractional digits. Preserve unknown historical timestamps as null. Reject malformed timezone offsets and UTC conversion overflow as input errors. Read-only queries and idempotent retries must preserve event and entity timestamps/revisions.

Use secret sentinel tests through failed requests, exception logs, access logs, JSON CLI, telemetry and exports. Missing token usage is unavailable, not zero. Do not request or store hidden chain-of-thought.

Workspace observation is scoped to the task's registered roots and relative paths. Hash the complete admitted tree and Git index mode/blob/stage, not status labels alone. Porcelain v1 `-z` renames carry destination before source; account for both without reading outside scope. Use literal pathspecs and disable ext-diff/textconv/fsmonitor. Exclude private path segments and the artifact store even if Git tracks them. Links, reparse points and exceptional files remain observation-only; do not feed them back into Git diff to read their targets. Preserve their kinds/digests in the result so a link-only result can be submitted without an unsafe patch.

Artifacts use independent domain references over content-addressed blobs. Never treat a hash, main role or shared physical bytes as authority for another domain or private recipient. Reads and caller-supplied references verify project/lineage/owner/scope and blob digest; deduplication must verify an existing blob before reusing it. Workspace observation evidence does not upgrade worker-reported tests or commit claims. Persist validation times, exact tool/version digest and output hashes; reject raw text in digest fields.
