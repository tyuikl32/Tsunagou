# Backend implementation rules

Status: partial application implementation exists. The 2026-09-20 assembled-runtime audit found persistence, ownership, protocol and packaging gaps despite passing unit tests. Current delivery follows the [standalone M1 plan](../../../docs/standalone/implementation-plan.md); complete design remains normative for retained behavior.

## Pre-Development Checklist

Read [implementation index](../../../docs/implementation/README.md), the active task PRD/design/implement, and its module plan. Verify dependency completion in task-plan.json and task metadata before implementation. Do not reopen answered product decisions.

| Guide | Purpose |
|---|---|
| [Structure](directory-structure.md) | Eight modules and public ports |
| [Database](database-guidelines.md) | UoW, SQLite, event/outbox atomicity |
| [Errors](error-handling.md) | Wire errors, unknown outcomes, retry |
| [Logging](logging-guidelines.md) | Secrets and visibility |
| [Quality](quality-guidelines.md) | Tests, protocol and release checks |
| [Entrypoints](entrypoint-contracts.md) | CLI/HTTP/MCP identity, enrollment, examples and errors |
| [Standalone Runtime](standalone-runtime.md) | Real process/HTTP audit, persistent state, M1 repair order and delivery checks |

For build order and file placement, read [build guide](../../../docs/implementation/build-guide.md) and [planned directory layout](../../../docs/implementation/directory-layout.md). Official knowledge and adoption limits are indexed in [references](../../../docs/implementation/references.md).

## Quality Check

Use the active task acceptance criteria and real assembled runtime checks. Python/TypeScript tests and packaging tools exist; passing service-object tests does not prove that CLI/HTTP, persistence and workflows are connected. Run `python tools/docs/validate_docs.py` for documentation changes.
