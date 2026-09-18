# Logging, evidence and privacy

Source: [evaluation](../../../docs/implementation/modules/08-evaluation.md).

Use registered structlog fields: timestamp, level, event, project/lineage/command/operation IDs, reason codes, durations and digests. Do not log token/ticket, Authorization, raw conversation IDs, private message body, prompt/source code or full host config by default. Hash possession is not read authorization.

OTel is opt-in, local OTLP only. Audit/read projections preserve domain permissions; main is not an inbox superuser. Checkpoint export uses explicit shared profile and never includes usable runtime credentials/grants/leases.

Use secret sentinel tests through failed requests, exception logs, access logs, JSON CLI, telemetry and exports. Missing token usage is unavailable, not zero. Do not request or store hidden chain-of-thought.
