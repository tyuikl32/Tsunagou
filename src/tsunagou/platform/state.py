"""SQLite-backed recovery snapshots for the current module services.

The domain services remain intentionally small and independently testable. This
adapter gives the running daemon one durable source for their current facts and
restores them before the first request. Every snapshot is written by the same
ProjectDatabase transaction as the command idempotency record and event.
"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from typing import Any

from tsunagou.application.workflows.lifecycle import LifecycleService, OperationResolution, UserDecision
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
from tsunagou.modules.messaging import Delivery, Message, MessageStore, ResponseObligation
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


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, tuple):
        return {"__tuple__": [_jsonable(item) for item in value]}
    if isinstance(value, (set, frozenset)):
        return {"__set__": [_jsonable(item) for item in value]}
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
    ) -> None:
        self.authority = authority
        self.tasks = tasks
        self.cognition = cognition
        self.messages = messages
        self.resources = resources
        self.workspaces = workspaces
        self.lifecycle = lifecycle
        self.database = database
        self._modules = tuple(
            module for module, service in (
                ("authority", authority), ("tasks", tasks), ("cognition", cognition),
                ("messages", messages), ("resources", resources),
                ("workspaces", workspaces), ("lifecycle", lifecycle),
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
        }[module]
        if services is None:
            raise KeyError(module)
        return services

    def _export(self, module: str) -> dict[str, Any]:
        service = self._service(module)
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
        if module in {"resources", "workspaces", "lifecycle"}:
            self._replace_optional(module, value)
            return
        if module == "authority":
            service.tickets = {
                key: EnrollmentTicket(**item) for key, item in value.get("tickets", {}).items()
            }
            service.agents = {key: Agent(**item) for key, item in value.get("agents", {}).items()}
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
            service.workspaces = {key: Workspace(**item) for key, item in value.get("workspaces", {}).items()}
            service.git_requests = {key: GitActionRequest(**item) for key, item in value.get("git_requests", {}).items()}
            service.baselines = {
                key: BaselineManifest(**{**item, "untracked_summary": tuple(item.get("untracked_summary", ())),
                                         "root_identities": tuple(item.get("root_identities", ()))})
                for key, item in value.get("baselines", {}).items()
            }
            service.results = {
                key: ResultManifest(**{**item, "commit_refs": tuple(item.get("commit_refs", ())),
                                      "changed_paths": tuple(item.get("changed_paths", ())),
                                      "untracked_summary": tuple(item.get("untracked_summary", ())),
                                      "validation_refs": tuple(item.get("validation_refs", ()))})
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

    def invalidate_execution_state(self) -> None:
        """Fence work owned by a previous daemon process before serving requests."""
        for key, grant in list(self.authority.grants.items()):
            if grant.kind == "task_attempt" and grant.status == "active":
                self.authority.grants[key] = Grant(
                    **{**asdict(grant), "capabilities": grant.capabilities, "status": "revoked"},
                )
        for task in self.tasks.tasks.values():
            attempt = self.tasks.attempts.get(task.current_attempt_id or "")
            if task.status == "running" and attempt is not None:
                attempt.status = "orphaned"
                attempt.revision += 1
                task.status = "orphaned"
                task.orphan_reason = "runtime_epoch_rotated"
                task.revision += 1

    def persist(self, uow: UnitOfWork, *, actor_ref: str, command_kind: str) -> None:
        changed = False
        for module in self._modules:
            payload = json.dumps(_jsonable(self._export(module)), ensure_ascii=False, sort_keys=True)
            uow.put_module_state(module, payload)
            changed = True
        if changed:
            uow.append_event(
                lineage_id="local-lineage",
                event_type=f"command.{command_kind}",
                aggregate_ref=f"project/{uow.project_id}",
                actor_ref=actor_ref,
                payload={"command_kind": command_kind},
            )
