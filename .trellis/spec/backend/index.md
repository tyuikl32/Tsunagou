# Backend implementation rules

Status: documentation baseline; application code is not implemented yet. The rules are sourced from the approved project documents, not claimed as existing code patterns.

## Pre-Development Checklist

Read [implementation index](../../../docs/implementation/README.md), the active task PRD/design/implement, and its module plan. Verify dependency completion in task-plan.json and task metadata before implementation. Do not reopen answered product decisions.

| Guide | Purpose |
|---|---|
| [Structure](directory-structure.md) | Eight modules and public ports |
| [Database](database-guidelines.md) | UoW, SQLite, event/outbox atomicity |
| [Errors](error-handling.md) | Wire errors, unknown outcomes, retry |
| [Logging](logging-guidelines.md) | Secrets and visibility |
| [Quality](quality-guidelines.md) | Tests, protocol and release checks |

## Quality Check

Use the active task acceptance criteria. Until T01 creates product tooling, only `python tools/docs/validate_docs.py` and Trellis context validation are executable project checks. Do not claim product tests passed merely because planning validates.
