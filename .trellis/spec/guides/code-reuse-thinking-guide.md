# Reuse and ownership

Source: [architecture](../../../docs/implementation/architecture.md), [principles](../../../docs/overview/principles.md).

Reuse shared protocol types, bridge-sdk transport and narrow public ports. Shared kernel contains IDs, revisions, clocks, hash/envelope/error values, not a growing generic business service. Do not introduce generic workflow DSLs, policy languages, repository access or LLM semantic validators.

Each table belongs to one of eight modules. Blackboard is query composition and workflows are stateless composition. Git mutations belong to the runtime main Agent; daemon performs only registered read-only verification. Ordinary implementation choices should be made and documented without burdening the user.
