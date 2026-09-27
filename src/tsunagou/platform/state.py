"""SQLite-backed recovery snapshots for the current module services.

The domain services remain intentionally small and independently testable. This
adapter gives the running daemon one durable source for their current facts and
restores them before the first request. Every snapshot is written by the same
ProjectDatabase transaction as the command idempotency record and event.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, is_dataclass
from typing import Any

from tsunagou.application.workflows.lifecycle import LifecycleService, OperationResolution, UserDecision
from tsunagou.modules.artifacts import ArtifactBlob, ArtifactRef, ArtifactService
from tsunagou.modules.authority import Agent, AuthorityService, EnrollmentTicket, Grant, Session
from tsunagou.modules.cognition import (
    Claim,
    CognitionService,
    CognitiveReport,
    ContractAcceptance,
    ContractProposal,
    Discrepancy,
    RiskAcceptance,
    RiskRequest,
    RiskSubmission,
)
from tsunagou.modules.coordination import (
    CoordinationAssignment,
    CoordinationEvent,
    CoordinationPlan,
    CoordinationService,
    WakeAttempt,
)
from tsunagou.modules.messaging import Delivery, Message, MessageStore, ResponseObligation
from tsunagou.modules.projects import ConfigProvenance, Project, ProjectRegistry
from tsunagou.modules.resources import (
    LeaseSet,
    ResourceIntent,
    ResourceKey,
    ResourceObservation,
    ResourceRequest,
    ResourceService,
)
from tsunagou.modules.tasks import (
    Attempt,
    PreflightResult,
    ProgressRecord,
    ReviewRound,
    SuspensionSnapshot,
    Task,
    TaskResult,
    TaskService,
)
from tsunagou.modules.workspaces import (
    BaselineManifest,
    GitActionRequest,
    IsolationDecision,
    ResultManifest,
    Workspace,
    WorkspaceService,
)
from tsunagou.platform.db.sqlite import UnitOfWork
from tsunagou.shared_kernel.digests import canonical_digest
from tsunagou.shared_kernel.time import now_ms

# These are projections of module-owned entities, not another state machine.
# The explicit map prevents secret map keys (notably hashed ticket lookup keys)
# and arbitrary payload dictionaries from becoming public subject identities.
_ENTITIES: dict[str, dict[str, tuple[str, str]]] = {
    "authority": {"tickets": ("ticket", "ticket_id"), "agents": ("agent", "agent_id"),
                  "sessions": ("session", "session_id"), "grants": ("grant", "grant_id")},
    "tasks": {"tasks": ("task", "task_id"), "attempts": ("attempt", "attempt_id"),
              "results": ("result", "result_id"), "reviews": ("review", ""),
              "scope_requests": ("scope_request", "scope_request_id"),
              "preflights": ("preflight", "preflight_id"), "progress_records": ("progress", "progress_id")},
    "cognition": {"reports": ("report", "report_id"), "discrepancies": ("discrepancy", "discrepancy_id"),
                  "proposals": ("contract", "proposal_id"), "acceptances": ("contract_acceptance", ""),
                  "risk_requests": ("risk_request", "request_id"), "risk_submissions": ("risk_submission", "submission_id"),
                  "risk_acceptances": ("risk_acceptance", "")},
    "messages": {"messages": ("message", "message_id"), "deliveries": ("delivery", "message_id"),
                 "obligations": ("obligation", "obligation_id")},
    "resources": {"intents": ("resource_intent", "intent_id"), "lease_sets": ("lease", "lease_set_id"),
                  "observations": ("resource_observation", "")},
    "workspaces": {"decisions": ("isolation_decision", "decision_id"), "workspaces": ("workspace", "workspace_id"),
                   "git_requests": ("git_request", "request_id"), "baselines": ("baseline", "manifest_id"),
                   "results": ("workspace_result", "manifest_id")},
    "artifacts": {"refs": ("artifact", "artifact_ref")},
    "lifecycle": {"decisions": ("decision", "decision_id"), "resolutions": ("resolution", "")},
    "coordination": {"plans": ("plan", "plan_id"), "assignments": ("assignment", "assignment_id"),
                     "wake_attempts": ("wake_attempt", "wake_attempt_id"), "events": ("coordination_event", "event_id")},
}


def _jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, tuple):
        return {"__tuple__": [_jsonable(item) for item in value]}
    if isinstance(value, (set, frozenset)):
        return {"__set__": sorted((_jsonable(item) for item in value), key=lambda item: json.dumps(item, sort_keys=True))}
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def _plain(value: Any) -> Any:
    if isinstance(value, dict) and set(value) == {"__tuple__"}:
        return tuple(_plain(item) for item in value["__tuple__"])
    if isinstance(value, dict) and set(value) == {"__set__"}:
        return set(_plain(item) for item in value["__set__"])
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


class ServiceStateRuntime:
    """Load, persist and rollback the stateful services used by the daemon."""

    def __init__(
        self,
        *,
        authority: AuthorityService,
        tasks: TaskService,
        cognition: CognitionService,
        messages: MessageStore,
        database: Any,
        resources: ResourceService | None = None,
        workspaces: WorkspaceService | None = None,
        lifecycle: LifecycleService | None = None,
        coordination: CoordinationService | None = None,
        project_registry: ProjectRegistry | None = None,
        artifacts: ArtifactService | None = None,
    ) -> None:
        self.authority = authority
        self.tasks = tasks
        self.cognition = cognition
        self.messages = messages
        self.resources = resources
        self.workspaces = workspaces
        self.lifecycle = lifecycle
        self.coordination = coordination
        self.project_registry = project_registry
        self.artifacts = artifacts
        self.database = database
        self._modules = tuple(
            module for module, service in (
                ("authority", authority), ("tasks", tasks), ("cognition", cognition),
                ("messages", messages), ("resources", resources),
                ("workspaces", workspaces), ("lifecycle", lifecycle),
                ("coordination", coordination),
                ("projects", project_registry),
                ("artifacts", artifacts),
            ) if service is not None
        )
        self.restore_from_database()

    def _service(self, module: str) -> Any:
        services = {
            "authority": self.authority,
            "tasks": self.tasks,
            "cognition": self.cognition,
            "messages": self.messages,
            "resources": self.resources,
            "workspaces": self.workspaces,
            "lifecycle": self.lifecycle,
            "coordination": self.coordination,
            "projects": self.project_registry,
            "artifacts": self.artifacts,
        }[module]
        if services is None:
            raise KeyError(module)
        return services

    def _export(self, module: str) -> dict[str, Any]:
        service = self._service(module)
        if module == "artifacts":
            return {"refs": service.refs, "blobs": service.blobs}
        if module == "projects":
            return {"project": service.project, "bindings": service.local_bindings}
        if module == "authority":
            return {
                "tickets": service.tickets,
                "agents": service.agents,
                "sessions": service.sessions,
                "grants": service.grants,
                "main_agent_id": service.main_agent_id,
                "authority_epoch": service.authority_epoch,
            }
        if module == "tasks":
            return {
                "tasks": service.tasks,
                "attempts": service.attempts,
                "results": service.results,
                "reviews": {f"{key[0]}::{key[1]}": value for key, value in service.reviews.items()},
                "scope_requests": service.scope_requests,
                "preflights": service.preflights,
                "progress_records": service.progress_records,
            }
        if module == "cognition":
            return {
                "reports": service.reports,
                "discrepancies": service.discrepancies,
                "proposals": service.proposals,
                "acceptances": {f"{key[0]}::{key[1]}": value for key, value in service.acceptances.items()},
                "risk_requests": service.risk_requests,
                "risk_submissions": service.risk_submissions,
                "risk_acceptances": service.risk_acceptances,
            }
        if module == "resources":
            return {
                "ttl_seconds": service.ttl_seconds,
                "intents": service.intents,
                "lease_sets": service.lease_sets,
                "observations": service.observations,
                "waiting": service.waiting,
            }
        if module == "workspaces":
            return {
                "decisions": service.decisions,
                "workspaces": service.workspaces,
                "git_requests": service.git_requests,
                "baselines": service.baselines,
                "results": service.results,
            }
        if module == "lifecycle":
            return {
                "decisions": service.decisions,
                "resolutions": service.resolutions,
                "operations": service.operations,
                "succession": service.succession,
            }
        if module == "coordination":
            return {
                "plans": service.plans,
                "assignments": service.assignments,
                "wake_attempts": service.wake_attempts,
                "events": service.events,
            }
        return {
            "messages": service.messages,
            "deliveries": service.deliveries,
            "obligations": service.obligations,
            "command_index": service.command_index,
            "push_failures": service.push_failures,
            "high_watermark": service.high_watermark,
        }

    def _replace(self, module: str, raw: dict[str, Any]) -> None:
        value = _plain(raw)
        service = self._service(module)
        if module == "artifacts":
            service.refs = {key: ArtifactRef(**item) for key, item in value.get("refs", {}).items()}
            service.blobs = {key: ArtifactBlob(**item) for key, item in value.get("blobs", {}).items()}
            return
        if module == "projects":
            project = value.get("project")
            if project is not None:
                project = dict(project)
                config = project.pop("config", None)
                service.project = Project(**project, config=ConfigProvenance(**config) if config else None)
            service.local_bindings = value.get("bindings", {})
            return
        if module in {"resources", "workspaces", "lifecycle", "coordination"}:
            self._replace_optional(module, value)
            return
        if module == "authority":
            service.tickets = {
                key: EnrollmentTicket(**item) for key, item in value.get("tickets", {}).items()
            }
            service.agents = {
                key: Agent(**{
                    **item,
                    "conversation_digest": item.get("conversation_digest") or next(
                        (
                            session.conversation_digest
                            for session in service.sessions.values()
                            if session.agent_id == key
                        ),
                        "",
                    ),
                })
                for key, item in value.get("agents", {}).items()
            }
            service.sessions = {key: Session(**item) for key, item in value.get("sessions", {}).items()}
            service.grants = {
                key: Grant(**{**item, "capabilities": frozenset(item.get("capabilities", []))})
                for key, item in value.get("grants", {}).items()
            }
            service.main_agent_id = value.get("main_agent_id")
            service.authority_epoch = int(value.get("authority_epoch", 1))
            return
        if module == "tasks":
            service.tasks = {
                key: Task(**{
                    **item,
                    "blocks": set(item.get("blocks", [])),
                    "suspension_snapshot": (
                        SuspensionSnapshot(**{
                            **item["suspension_snapshot"],
                            "dependency_refs": tuple(item["suspension_snapshot"].get("dependency_refs", [])),
                            "evidence_refs": tuple(item["suspension_snapshot"].get("evidence_refs", [])),
                        }) if item.get("suspension_snapshot") else None
                    ),
                })
                for key, item in value.get("tasks", {}).items()
            }
            service.attempts = {key: Attempt(**item) for key, item in value.get("attempts", {}).items()}
            service.results = {key: TaskResult(**item) for key, item in value.get("results", {}).items()}
            service.reviews = {
                tuple(key.rsplit("::", 1)): ReviewRound(**item)
                for key, item in value.get("reviews", {}).items()
            }
            service.scope_requests = value.get("scope_requests", {})
            service.preflights = {
                key: PreflightResult(**{**item, "evidence_refs": tuple(item.get("evidence_refs", []))})
                for key, item in value.get("preflights", {}).items()
            }
            service.progress_records = {
                key: ProgressRecord(**{**item, "evidence_refs": tuple(item.get("evidence_refs", []))})
                for key, item in value.get("progress_records", {}).items()
            }
            return
        if module == "cognition":
            service.reports = {}
            for key, item in value.get("reports", {}).items():
                claims = tuple(Claim(**{**claim, "evidence_refs": tuple(claim.get("evidence_refs", []))})
                               for claim in item.get("claims", []))
                service.reports[key] = CognitiveReport(
                    **{**item, "claims": claims, "uncertainties": tuple(item.get("uncertainties", [])),
                       "assumptions": tuple(item.get("assumptions", []))}
                )
            service.discrepancies = {
                key: Discrepancy(**{**item, "claim_ids": tuple(item.get("claim_ids", []))})
                for key, item in value.get("discrepancies", {}).items()
            }
            service.proposals = {
                key: ContractProposal(
                    **{**item, "participants": tuple(item.get("participants", [])),
                       "required_slots": tuple(item.get("required_slots", []))}
                ) for key, item in value.get("proposals", {}).items()
            }
            service.acceptances = {
                tuple(key.rsplit("::", 1)): ContractAcceptance(**item)
                for key, item in value.get("acceptances", {}).items()
            }
            service.risk_requests = {
                key: RiskRequest(**{**item, "candidates": tuple(item.get("candidates", []))})
                for key, item in value.get("risk_requests", {}).items()
            }
            service.risk_submissions = {
                key: RiskSubmission(**{**item, "conditions": tuple(item.get("conditions", [])),
                                       "evidence_refs": tuple(item.get("evidence_refs", []))})
                for key, item in value.get("risk_submissions", {}).items()
            }
            service.risk_acceptances = [RiskAcceptance(**item) for item in value.get("risk_acceptances", [])]
            return
        service.messages = {key: Message(**item) for key, item in value.get("messages", {}).items()}
        service.deliveries = {key: Delivery(**item) for key, item in value.get("deliveries", {}).items()}
        service.obligations = {key: ResponseObligation(**item) for key, item in value.get("obligations", {}).items()}
        service.command_index = value.get("command_index", {})
        service.push_failures = value.get("push_failures", {})
        service.high_watermark = int(value.get("high_watermark", len(service.messages)))

    @staticmethod
    def _resource_request(item: dict[str, Any]) -> ResourceRequest:
        raw_key = item.get("key", {})
        return ResourceRequest(
            ResourceKey(**{**raw_key, "segments": tuple(raw_key.get("segments", ())) }),
            item["mode"],
        )

    def _replace_optional(self, module: str, value: dict[str, Any]) -> bool:
        service = self._service(module)
        if module == "resources":
            service.ttl_seconds = int(value.get("ttl_seconds", 120))
            service.intents = {
                key: ResourceIntent(
                    **{**item, "resources": tuple(self._resource_request(request) for request in item.get("resources", ()))},
                ) for key, item in value.get("intents", {}).items()
            }
            service.lease_sets = {
                key: LeaseSet(
                    **{**item, "resources": tuple(self._resource_request(request) for request in item.get("resources", ()))},
                ) for key, item in value.get("lease_sets", {}).items()
            }
            service.observations = [ResourceObservation(**item) for item in value.get("observations", [])]
            service.waiting = [tuple(item) for item in value.get("waiting", [])]
            return True
        if module == "workspaces":
            service.decisions = {
                key: IsolationDecision(**{**item, "hard_constraints": tuple(item.get("hard_constraints", ())),
                                         "evidence_refs": tuple(item.get("evidence_refs", ()))})
                for key, item in value.get("decisions", {}).items()
            }
            service.workspaces = {
                key: Workspace(**{
                    **item,
                    "root_binding_refs": tuple(item.get("root_binding_refs", ())),
                    "scope_roots": tuple(item.get("scope_roots", ())),
                    "scope_paths": tuple(item["scope_paths"]) if isinstance(item.get("scope_paths"), list) else item.get("scope_paths"),
                }) for key, item in value.get("workspaces", {}).items()
            }
            service.git_requests = {key: GitActionRequest(**item) for key, item in value.get("git_requests", {}).items()}
            service.baselines = {
                key: BaselineManifest(**{**item, "untracked_summary": tuple(item.get("untracked_summary", ())),
                                         "root_identities": tuple(item.get("root_identities", ())),
                                         "root_observations": tuple(item.get("root_observations", ())),
                                         "scope_paths": (
                                             tuple(item["scope_paths"])
                                             if isinstance(item.get("scope_paths"), list)
                                             else item.get("scope_paths")
                                         )})
                for key, item in value.get("baselines", {}).items()
            }
            service.results = {
                key: ResultManifest(**{**item, "commit_refs": tuple(item.get("commit_refs", ())),
                                      "changed_paths": tuple(item.get("changed_paths", ())),
                                      "untracked_summary": tuple(item.get("untracked_summary", ())),
                                      "validation_refs": tuple(item.get("validation_refs", ())),
                                      "validation_metadata": tuple(item.get("validation_metadata", ())),
                                      "root_observations": tuple(item.get("root_observations", ())),
                                      "scope_paths": (
                                          tuple(item["scope_paths"])
                                          if isinstance(item.get("scope_paths"), list)
                                          else item.get("scope_paths")
                                      )})
                for key, item in value.get("results", {}).items()
            }
            return True
        if module == "lifecycle":
            service.decisions = {key: UserDecision(**item) for key, item in value.get("decisions", {}).items()}
            service.resolutions = [
                OperationResolution(**{**item, "evidence_refs": tuple(item.get("evidence_refs", ()))})
                for item in value.get("resolutions", [])
            ]
            service.operations = dict(value.get("operations", {}))
            service.succession = list(value.get("succession", []))
            return True
        if module == "coordination":
            service.plans = {
                key: CoordinationPlan(
                    **{**item, "assignment_ids": tuple(item.get("assignment_ids", ()))},
                )
                for key, item in value.get("plans", {}).items()
            }
            service.assignments = {
                key: CoordinationAssignment(
                    **{**item, "dependencies": tuple(item.get("dependencies", ()))},
                )
                for key, item in value.get("assignments", {}).items()
            }
            service.wake_attempts = {
                key: WakeAttempt(**item)
                for key, item in value.get("wake_attempts", {}).items()
            }
            service.events = [CoordinationEvent(**item) for item in value.get("events", [])]
            service._task_index = {
                item.task_id: item.assignment_id for item in service.assignments.values()
            }
            return True
        return False

    def restore_from_database(self) -> None:
        for module in self._modules:
            raw = self.database.module_state(module)
            if raw:
                self._replace(module, json.loads(raw))

    def capture(self) -> dict[str, Any]:
        # Keep rollback snapshots independent from live dataclass instances.
        # A failed command must be able to restore the exact same shape that
        # SQLite would load after a process restart.
        return {
            module: json.loads(json.dumps(_jsonable(self._export(module)), ensure_ascii=False))
            for module in self._modules
        }

    def restore(self, snapshot: dict[str, Any]) -> None:
        for module, value in snapshot.items():
            self._replace(module, value)

    def import_shared(self, domains: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
        """Import owner-validated public history into an empty local replica.

        This is a recovery port, never a live authority restore. Runtime-only
        collections remain empty and unfinished tasks require main review.
        """
        project_records = domains.get("project", [])
        if len(project_records) != 1 or self.project_registry is None:
            raise ValueError("checkpoint_project_required")
        from tsunagou.shared_kernel.ids import new_id

        project = {**project_records[0], "current_replica_id": new_id(), "runtime_epoch": new_id()}
        self._replace("projects", {"project": project, "bindings": {}})
        for module in ("tasks", "cognition", "workspaces", "lifecycle", "artifacts"):
            records = domains.get(module, [])
            if len(records) > 1:
                raise ValueError("checkpoint_module_duplicate")
            if records and module in self._modules:
                self._replace(module, records[0])
        # Historic authors remain visible but cannot authenticate or reclaim
        # their former role through imported installation/conversation IDs.
        for key, item in domains.get("authority", [{}])[0].get("agents", {}).items():
            self.authority.agents[key] = Agent(item["agent_id"], "", status="retired")
        self.authority.main_agent_id = None
        self.authority.sessions.clear()
        self.authority.grants.clear()
        self.authority.tickets.clear()
        imported_before = self.capture()
        for task in self.tasks.tasks.values():
            task.current_attempt_id = None
            task.suspension_snapshot = None
            if task.status not in {"completed", "cancelled", "failed"}:
                task.status, task.block_reason = "blocked", "recovery_review"
                task.revision += 1
        for attempt in self.tasks.attempts.values():
            if attempt.status in {"claimed", "running"}:
                attempt.status = "orphaned"
                attempt.ended_at = time.time()
                attempt.execution_epoch += 1
                attempt.revision += 1
        for workspace in self.workspaces.workspaces.values() if self.workspaces is not None else ():
            workspace.status = "recovery_review"
        if self.lifecycle is not None:
            for decision in self.lifecycle.decisions.values():
                if decision.status == "pending":
                    decision.status = "superseded"
        return imported_before

    def invalidate_execution_state(self) -> None:
        """Fence work owned by a previous daemon process before serving requests."""
        for key, grant in list(self.authority.grants.items()):
            if grant.kind == "task_attempt" and grant.status == "active":
                self.authority.grants[key] = Grant(
                    **{**asdict(grant), "capabilities": grant.capabilities, "status": "revoked"},
                )
        for task in self.tasks.tasks.values():
            attempt = self.tasks.attempts.get(task.current_attempt_id or "")
            if task.status in {"claimed", "running"} and attempt is not None:
                if self.resources is not None:
                    self.resources.release_for_attempt(
                        attempt.attempt_id, reason="runtime_epoch_rotated",
                    )
                attempt.status = "orphaned"
                attempt.ended_at = time.time()
                attempt.revision += 1
                task.current_attempt_id = None
                # A daemon restart invalidates execution authority and the
                # in-memory claim. Leave the durable task in the public queue
                # for any later Agent; the old Attempt remains evidence.
                task.status = "open"
                task.orphan_reason = "runtime_epoch_rotated"
                task.revision += 1
        if self.coordination is not None:
            self.coordination.invalidate_execution_state()

    @property
    def lineage_id(self) -> str:
        if self.project_registry is not None and self.project_registry.project is not None:
            return self.project_registry.project.current_lineage_id
        return str(self.database.lineage_id)

    def audit_actor(self, context: dict[str, Any]) -> str:
        if context.get("kind") == "T":
            secret_hash = hashlib.sha256(str(context["principal_id"]).encode()).hexdigest()
            ticket = self.authority.tickets.get(secret_hash)
            if ticket is None:
                raise ValueError("audit_ticket_identity_missing")
            return f"ticket/{ticket.ticket_id}"
        return str(context["principal_id"])

    @staticmethod
    def _entities(module: str, snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
        plain = _plain(snapshot)
        entities: dict[str, dict[str, Any]] = {}
        if module == "projects":
            project = plain.get("project")
            if project:
                entities[f"project/{project['project_id']}"] = project
                for root_id, root in project.get("roots", {}).items():
                    entities[f"root/{root_id}"] = {**root, "binding": plain.get("bindings", {}).get(root_id)}
                for repository_id, repository in project.get("repositories", {}).items():
                    entities[f"repository/{repository_id}"] = repository
            return entities
        for collection, (kind, identity_field) in _ENTITIES.get(module, {}).items():
            items = plain.get(collection, {})
            pairs = items.items() if isinstance(items, dict) else enumerate(items)
            for key, item in pairs:
                if isinstance(item, dict):
                    # Lists without IDs already have append-only positional
                    # identity within their owning aggregate; keep that index.
                    identity = item.get(identity_field, key) if identity_field else key
                    entities[f"{kind}/{identity}"] = item
        return entities

    @staticmethod
    def _domain_revision(item: dict[str, Any] | None) -> int | None:
        if item is None:
            return None
        value = item.get("revision", item.get("policy_revision"))
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    @staticmethod
    def _subject(command_kind: str, payload: dict[str, Any], result: dict[str, Any], changes: list[dict[str, Any]]) -> str | None:
        # Command family decides the primary target. Related changes remain
        # separately attributable in the change list, e.g. task.claim -> Attempt.
        candidates: list[tuple[str, str]] = []
        family = command_kind.split(".")[0]
        if family == "task":
            candidates = [("task_id", "task"), ("source_task_id", "task")]
        elif family in {"message", "inbox"}:
            candidates = [("message_id", "message"), ("obligation_id", "obligation")]
        elif family == "contract":
            candidates = [("proposal_id", "contract")]
        elif family == "cognition":
            candidates = [("report_id", "report")]
        elif family == "workspace":
            candidates = [("workspace_id", "workspace"), ("decision_id", "isolation_decision"), ("request_id", "git_request")]
        elif family == "resource":
            candidates = [("lease_set_id", "lease"), ("intent_id", "resource_intent"), ("attempt_id", "attempt")]
        else:
            candidates = [("decision_id", "decision"), ("discrepancy_id", "discrepancy"),
                          ("root_id", "root"), ("repository_id", "repository"), ("session_id", "session"),
                          ("agent_id", "agent"), ("main_agent_id", "agent"), ("plan_id", "plan"),
                          ("assignment_id", "assignment"), ("ticket_id", "ticket"), ("project_id", "project")]
        refs = {change["subject_ref"] for change in changes}
        for field, kind in candidates:
            value = result.get(field) or payload.get(field)
            if isinstance(value, str) and f"{kind}/{value}" in refs:
                return f"{kind}/{value}"
        return str(changes[0]["subject_ref"]) if changes else None

    def persist(
        self, uow: UnitOfWork, *, actor_ref: str, command_kind: str,
        before: dict[str, Any] | None = None, command_payload: dict[str, Any] | None = None,
        result: dict[str, Any] | None = None, session_id: str | None = None,
    ) -> None:
        payload = command_payload or {}
        result = result or {}
        uow.recorded_at = now_ms()
        changes: list[dict[str, Any]] = []
        modules_changed: list[str] = []
        for module, current in self.capture().items():
            stored = uow.conn.execute(
                "SELECT payload_json FROM module_state WHERE project_id=? AND module=?", (uow.project_id, module),
            ).fetchone()
            previous = before.get(module, {}) if before is not None else (json.loads(stored[0]) if stored else {})
            if stored is None or json.loads(stored[0]) != current:
                uow.put_module_state(module, json.dumps(current, ensure_ascii=False, sort_keys=True))
            if previous == current:
                continue
            modules_changed.append(module)
            old_entities, new_entities = self._entities(module, previous), self._entities(module, current)
            for ref in sorted(old_entities.keys() | new_entities.keys()):
                old, new = old_entities.get(ref), new_entities.get(ref)
                if old == new:
                    continue
                change = uow.record_entity_change(
                    lineage_id=self.lineage_id, subject_ref=ref, existed=old is not None,
                    revision_before=self._domain_revision(old), revision_after=self._domain_revision(new),
                )
                change.update({"change_kind": "created" if old is None else "deleted" if new is None else "updated",
                               "state_before": old.get("status") if old else None,
                               "state_after": new.get("status") if new else None})
                changes.append(change)
        if not modules_changed:
            return
        subject = self._subject(command_kind, payload, result, changes) or f"project/{uow.project_id}"
        primary = next((change for change in changes if change["subject_ref"] == subject), {})
        reason = payload.get("reason_code") or result.get("reason_code")
        if not isinstance(reason, str) or not re.fullmatch(r"[a-z][a-z0-9_.-]{0,79}", reason):
            # Free-form reasons belong to the owning domain; audit indexes only
            # a registered/mechanical category and never private request text.
            reason = "user_decision" if command_kind in {"user_decision.resolve", "project.completion.confirm"} else None
            if reason is None and any(part in command_kind for part in ("block", "revoke", "cancel", "fail", "recover", "expired")):
                reason = command_kind.replace(".", "_")
        refs = []
        for field in ("evidence_refs", "artifact_refs", "validation_refs"):
            for ref in payload.get(field) or ():
                if isinstance(ref, str):
                    refs.append(ref)
        for field in ("workspace_result_ref", "checkpoint_digest", "patch_artifact_ref"):
            result_ref = result.get(field) or payload.get(field)
            if isinstance(result_ref, str):
                refs.append(result_ref)
        # No raw request, response, credential or message text is copied.
        evidence_level = "agent_asserted" if refs else "system_verified"
        if actor_ref == "user_control":
            evidence_level = "user_confirmed"
        elif result.get("evidence_level") in {"agent_asserted", "host_observed", "system_verified"}:
            # Only a domain-handler output may attest observation/verification;
            # an arbitrary client payload cannot upgrade evidence provenance.
            evidence_level = str(result["evidence_level"])
        event_payload = {"command_kind": command_kind, "modules_changed": modules_changed,
                         "changes": changes, "session_id": session_id,
                         "evidence_level": evidence_level,
                         "request_digest": canonical_digest(payload)}
        seq = uow.append_event(
            lineage_id=self.lineage_id, event_type=command_kind, aggregate_ref=subject, actor_ref=actor_ref,
            payload=event_payload, subject_ref=subject, reason_code=reason,
            revision_before=primary.get("revision_before"), revision_after=primary.get("revision_after"),
            evidence_refs=tuple(dict.fromkeys(refs)),
        )
        for change in changes:
            uow.conn.execute(
                "UPDATE entity_audit_metadata SET last_event_seq=? WHERE project_id=? AND lineage_id=? AND subject_ref=?",
                (seq, uow.project_id, self.lineage_id, change["subject_ref"]),
            )
