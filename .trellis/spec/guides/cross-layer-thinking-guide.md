# Cross-layer changes

Source: [protocol](../../../docs/implementation/protocol.md), [command catalog](../../../docs/implementation/command-catalog.md), [lifecycle](../../../docs/implementation/lifecycle.md).

For an interface change, enumerate affected Schema, generated Python/TS, REST/MCP mappings, CommandPolicy, domain handler, event/export profile, adapter conformance and user guide. One schema owns each concept. Updating only a host adapter is not a complete protocol change.

Cross-module mutations share one UoW via public ports. External effects go through persistent Operation/Job and return evidence with input digest. A file operation cannot be made atomic by leaving a SQLite transaction open.

Maintain distinctions: user confirmation vs conversation preference, ACK vs response vs acceptance, completed task vs completed project, resource Lease vs Job lease, logical permission vs OS enforcement, main role vs Attempt owner.

When a host capability or enrollment path changes, trace evidence origin → server admission → HostSession credential → adapter tool call → domain handler. A green unit test or self-reported principal/`baseline_ok` at one layer cannot close a live-host release gate at another.
