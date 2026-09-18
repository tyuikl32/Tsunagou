# Quality gates

Sources: [validation](../../../docs/implementation/validation.md), [command catalog](../../../docs/implementation/command-catalog.md).

T01 establishes Ruff/mypy/pytest and exact invocations in project configuration. T03 establishes schema/codegen fixtures. Run the relevant task checks, then required shared gates; do not invent command success before tooling exists.

Every public command must have one registered policy, typed request/response and positive/negative authorization tests. JSON Schema is authoritative; generated files and OpenAPI must regenerate without diff. Test ownership, stale epochs, all-or-none mutations and recipient-only visibility.

Use injected clocks for TTL/backoff and real SQLite/Git fixtures for persistence. Keep Windows release-blocking and record actual macOS/Linux coverage. Four host simulator passes do not replace four live-host records. Research outcome gates are separate from engineering correctness.

Only user-approved product boundaries can change; ordinary internal implementation choices are recorded by the main implementation Agent. Keep PRD/design/implement and public documentation aligned.
