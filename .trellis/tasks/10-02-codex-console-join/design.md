# Design

Keep one active Codex enrollment for the local OS user in a private persistent store, with records retained by enrollment_id. TSUNAGOU_ENROLLMENT_DIR overrides the store for isolated tests. Console prepares an intent, not a ticket. Short cross-language file locks protect compare/write only; never hold across network operations.

Lifecycle: pending -> claimed -> enrolled -> arrived; pending can expire/cancel, claimed errors are retryable by the same thread. Claimed work is not reassigned on a timer. Root and role come only from the intent. Actual Codex identity is verified using existing onboarding preparation. Join composes the existing connect service using explicit runtime context, then records the exact agent and bound route.

The shared route carries a console-enrollment reference and a private receipt path. The existing shared bridge emits an original-host receipt only after a successful context read with matching project/role/session, excluding the explicitly marked bootstrap helper. Console verifies the receipt against the claimed record and daemon roster. Cancel never unregisters shared MCP or deletes enrolled identities.

No daemon authorization/schema changes. Shared MCP first loading remains an installation prerequisite; skill calls context from the original chat and reports missing tools explicitly.

Review refinements: validate pre-existing routes and real project manifests before claim; preserve enrolled state against late retry failures; reuse identical preparations and expose current enrollment for page reload recovery; reconcile original receipts before allocating a new global slot.
