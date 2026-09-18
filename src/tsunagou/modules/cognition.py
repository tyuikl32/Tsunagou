"""Explicit cognition records and deterministic contract/risk checks."""

from __future__ import annotations

import copy
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from tsunagou.shared_kernel.digests import canonical_digest
from tsunagou.shared_kernel.ids import new_id


@dataclass(frozen=True, slots=True)
class Claim:
    subject_key: str
    claim_type: str
    equality_key: str
    value: Any
    evidence_refs: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class CognitiveReport:
    report_id: str
    task_id: str
    attempt_id: str
    actor_agent_id: str
    claims: tuple[Claim, ...]
    uncertainties: tuple[str, ...]
    assumptions: tuple[str, ...]
    digest: str
    created_at: float


@dataclass(frozen=True, slots=True)
class Discrepancy:
    discrepancy_id: str
    rule_id: str
    rule_version: str
    subject_key: str
    severity: str
    input_digest: str
    claim_ids: tuple[str, ...]
    status: str = "open"


@dataclass(frozen=True, slots=True)
class ContractProposal:
    proposal_id: str
    payload: dict[str, Any]
    participants: tuple[dict[str, Any], ...]
    required_slots: tuple[str, ...]
    digest: str
    status: str = "proposed"


@dataclass(frozen=True, slots=True)
class ContractAcceptance:
    proposal_id: str
    participant_slot: str
    proposal_digest: str
    real_actor_id: str
    represented_participant: str | None = None
    via_proxy: bool = False


@dataclass(slots=True)
class RiskRequest:
    request_id: str
    attempt_id: str
    input_snapshot: dict[str, Any]
    input_digest: str
    candidates: tuple[dict[str, Any], ...]
    deadline_at: float
    status: str = "pending"


@dataclass(frozen=True, slots=True)
class RiskSubmission:
    request_id: str
    assessor_id: str
    risk_level: str
    reason: str
    recommended_driver: str | None
    scope: dict[str, Any]
    conditions: tuple[str, ...]
    evidence_refs: tuple[dict[str, Any], ...]
    input_digest: str


@dataclass(frozen=True, slots=True)
class RiskAcceptance:
    subject_ref: str
    actor_main_id: str
    reason: str
    accepted_risks: tuple[str, ...]
    input_digest: str
    valid_until_task_terminal: bool = True
    status: str = "active"
    effective_outcome: str = "risk_accepted"


class CognitionService:
    def __init__(self) -> None:
        self.reports: dict[str, CognitiveReport] = {}
        self.discrepancies: dict[str, Discrepancy] = {}
        self.proposals: dict[str, ContractProposal] = {}
        self.acceptances: dict[tuple[str, str], ContractAcceptance] = {}
        self.risk_requests: dict[str, RiskRequest] = {}
        self.risk_submissions: dict[str, RiskSubmission] = {}
        self.risk_acceptances: list[RiskAcceptance] = []
        self.rules = {
            "claim.literal_mismatch": ("1", "hard"),
            "claim.contract_digest_mismatch": ("1", "hard"),
            "claim.resource_use_mismatch": ("1", "soft"),
        }

    def submit_report(
        self, *, task_id: str, attempt_id: str, actor_agent_id: str,
        claims: list[Claim], uncertainties: list[str] | None = None,
        assumptions: list[str] | None = None,
    ) -> CognitiveReport:
        body = {
            "task_id": task_id, "attempt_id": attempt_id, "actor_agent_id": actor_agent_id,
            "claims": [claim.__dict__ if hasattr(claim, "__dict__") else {
                "subject_key": claim.subject_key, "claim_type": claim.claim_type,
                "equality_key": claim.equality_key, "value": claim.value,
                "evidence_refs": claim.evidence_refs,
            } for claim in claims],
            "uncertainties": uncertainties or [], "assumptions": assumptions or [],
        }
        report = CognitiveReport(
            new_id(), task_id, attempt_id, actor_agent_id, tuple(claims),
            tuple(uncertainties or ()), tuple(assumptions or ()), canonical_digest(body), time.time(),
        )
        self.reports[report.report_id] = report
        self._detect_discrepancies(report)
        return report

    def _detect_discrepancies(self, report: CognitiveReport) -> None:
        all_claims = [claim for item in self.reports.values() for claim in item.claims]
        for claim in report.claims:
            peers = [
                peer for peer in all_claims
                if peer is not claim and peer.subject_key == claim.subject_key
                and peer.equality_key == claim.equality_key and peer.claim_type == claim.claim_type
            ]
            for peer in peers:
                if peer.value == claim.value:
                    continue
                rule_id = "claim.literal_mismatch"
                version, severity = self.rules[rule_id]
                input_digest = canonical_digest({"left": peer.value, "right": claim.value, "subject": claim.subject_key})
                key = canonical_digest({"rule": rule_id, "subject": claim.subject_key, "input": input_digest})
                if key not in self.discrepancies:
                    self.discrepancies[key] = Discrepancy(
                        new_id(), rule_id, version, claim.subject_key, severity,
                        input_digest, (report.report_id,),
                    )

    def propose_contract(self, payload: dict[str, Any], participants: list[dict[str, Any]]) -> ContractProposal:
        if not participants:
            raise ValueError("contract_requires_participant")
        slots = [str(item["slot"]) for item in participants]
        if len(slots) != len(set(slots)):
            raise ValueError("duplicate_contract_slot")
        required = tuple(
            slot for slot, item in zip(slots, participants, strict=True)
            if item.get("required", False)
        )
        if not required:
            raise ValueError("contract_requires_required_slot")
        frozen_payload = copy.deepcopy(payload)
        frozen_participants = tuple(copy.deepcopy(participants))
        digest = canonical_digest({"payload": frozen_payload, "participants": frozen_participants})
        proposal = ContractProposal(new_id(), frozen_payload, frozen_participants, required, digest)
        self.proposals[proposal.proposal_id] = proposal
        return proposal

    def accept_contract(
        self, proposal_id: str, *, participant_slot: str, proposal_digest: str, actor_id: str
    ) -> ContractAcceptance:
        proposal = self.proposals[proposal_id]
        if proposal.status != "proposed" or proposal.digest != proposal_digest:
            raise ValueError("proposal_digest_mismatch")
        participant = next((item for item in proposal.participants if item["slot"] == participant_slot), None)
        if participant is None or participant.get("agent_id") != actor_id:
            raise PermissionError("participant_slot_denied")
        acceptance = ContractAcceptance(proposal_id, participant_slot, proposal_digest, actor_id)
        self.acceptances[(proposal_id, participant_slot)] = acceptance
        self._mark_proposal_accepted_if_complete(proposal)
        return acceptance

    def accept_proxy(
        self, proposal_id: str, *, participant_slot: str, proposal_digest: str,
        real_actor_id: str, represented_participant: str, main_allowed: bool,
    ) -> ContractAcceptance:
        if not main_allowed:
            raise PermissionError("proxy_not_allowed")
        proposal = self.proposals[proposal_id]
        if proposal.digest != proposal_digest or participant_slot not in proposal.required_slots:
            raise ValueError("proposal_digest_or_slot_mismatch")
        acceptance = ContractAcceptance(proposal_id, participant_slot, proposal_digest, real_actor_id, represented_participant, True)
        self.acceptances[(proposal_id, participant_slot)] = acceptance
        self._mark_proposal_accepted_if_complete(proposal)
        return acceptance

    def _mark_proposal_accepted_if_complete(self, proposal: ContractProposal) -> None:
        if all((proposal.proposal_id, slot) in self.acceptances for slot in proposal.required_slots):
            object.__setattr__(proposal, "status", "accepted")

    def supersede_contract(self, proposal_id: str, payload: dict[str, Any], participants: list[dict[str, Any]]) -> ContractProposal:
        proposal = self.proposals[proposal_id]
        object.__setattr__(proposal, "status", "superseded")
        return self.propose_contract(payload, participants)

    def request_risk(
        self, *, attempt_id: str, input_snapshot: dict[str, Any],
        candidates: list[dict[str, Any]], now: float | None = None,
    ) -> RiskRequest:
        now = time.time() if now is None else now
        request = RiskRequest(
            new_id(), attempt_id, copy.deepcopy(input_snapshot), canonical_digest(input_snapshot),
            tuple(copy.deepcopy(candidates)), now + 120,
        )
        self.risk_requests[request.request_id] = request
        return request

    def submit_risk(self, submission: RiskSubmission) -> None:
        request = self.risk_requests[submission.request_id]
        if request.input_digest != submission.input_digest:
            raise ValueError("risk_input_digest_mismatch")
        self.risk_submissions[submission.request_id] = submission
        request.status = "answered"

    def fallback_risk(self, request_id: str, *, now: float | None = None) -> dict[str, Any] | None:
        request = self.risk_requests[request_id]
        now = time.time() if now is None else now
        if request.status != "pending" or now < request.deadline_at:
            return None
        request.status = "fallback_used"
        for candidate in request.candidates:
            if candidate.get("hard_constraints_met", False):
                return copy.deepcopy(candidate)
        return None

    def accept_risk(
        self, *, subject_ref: str, actor_main_id: str, reason: str,
        accepted_risks: list[str], input_digest: str,
        ceiling_allows: Callable[[dict[str, Any]], bool],
    ) -> RiskAcceptance:
        payload = {"subject_ref": subject_ref, "accepted_risks": accepted_risks, "input_digest": input_digest}
        if not ceiling_allows(payload):
            raise PermissionError("user_ceiling_denied")
        if "unknown" in accepted_risks:
            outcome = "risk_accepted_unknown"
        else:
            outcome = "risk_accepted"
        acceptance = RiskAcceptance(subject_ref, actor_main_id, reason, tuple(accepted_risks), input_digest, effective_outcome=outcome)
        self.risk_acceptances.append(acceptance)
        return acceptance
