# Module structure

Source: [architecture](../../../docs/implementation/architecture.md).

One Python distribution under src/tsunagou. Eight modules: projects, agents, tasks, cognition, resources, workspaces, durability, evaluation. Each owns its domain/application/public/infrastructure/api as needed; do not create empty layers for appearance.

Domain imports only stdlib and stable shared_kernel values. Cross-module calls use modules.<name>.public. Routers translate protocol and identity, never query another module's ORM. Infrastructure implements ports. bootstrap is the only composition root.

application/workflows coordinates public ports in a shared UoW; application/queries builds blackboard in one read snapshot. Neither owns domain tables. platform holds OS/Git/HTTP/database adapters. generated/protocol is generated, never hand-edited.

Reject cross-module repositories, direct router-to-ORM calls, a ninth blackboard module, and semantic LLM decision logic in mechanical validators. T01/T23 enforce import boundaries.
