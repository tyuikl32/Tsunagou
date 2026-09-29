"""Explicit cognition records and deterministic contract/risk checks."""

from __future__ import annotations

import copy
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from tsunagou.shared_kernel.digests import canonical_digest
from tsunagou.shared_kernel.ids import new_id


def _normalised_literal(value: Any) -> Any:
    """Comparison form of a literal claim value, with writing differences collapsed.

    Only presentation is normalised: surrounding whitespace and letter case inside
    strings, and equivalent number spellings. A *type* difference is kept on purpose,
    because ``"1"`` and ``1`` disagree about the wire type — a real disagreement
    rather than a formatting one. Reports keep the raw values, so replay still sees
    exactly what was submitted; normalisation lives only in this comparison.
    """
    if isinstance(value, bool):
        return ("bool", value)
    if isinstance(value, int):
        return ("number", Decimal(value))
    if isinstance(value, float):
        return ("number", Decimal(str(value)))
    if isinstance(value, str):
        return ("string", value.strip().casefold())
    if isinstance(value, list | tuple):
        return ("list", tuple(_normalised_literal(item) for item in value))
    if isinstance(value, dict):
        return ("object", tuple(sorted(
            ((key, _normalised_literal(item)) for key, item in value.items()),
            key=lambda item: repr(item[0]),
        )))
    return ("other", repr(value))


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
    # What the report says it was working from. The ``contract`` entries are what turn
    # "these two reports were written under different agreements" into something a
    # machine can point at; the rest is kept exactly as declared.
    input_revisions: dict[str, Any] = field(default_factory=dict)


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
    proposed_by: str | None = None
    # The proposal this one replaces, if any. The chain plus each digest is the
    # mechanical identity of a contract "version"; a human-readable version label
    # belongs in ``payload`` and is never compared mechanically.
    supersedes_id: str | None = None

    # Why the proposal stopped being open, when the actor said so. The audit trail
    # deliberately keeps no free text, so this is the only place a rejection reason can
    # survive — and "why was this refused" is the whole semantic content of a refusal.
    resolution_reason: str | None = None


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
        input_revisions: dict[str, Any] | None = None,
    ) -> CognitiveReport:
        declared = dict(input_revisions or {})
        body = {
            "task_id": task_id, "attempt_id": attempt_id, "actor_agent_id": actor_agent_id,
            "claims": [claim.__dict__ if hasattr(claim, "__dict__") else {
                "subject_key": claim.subject_key, "claim_type": claim.claim_type,
                "equality_key": claim.equality_key, "value": claim.value,
                "evidence_refs": claim.evidence_refs,
            } for claim in claims],
            "uncertainties": uncertainties or [], "assumptions": assumptions or [],
            # The declared premises are part of the fingerprint: a report that changed
            # what it says it read is a different report.
            "input_revisions": declared,
        }
        report = CognitiveReport(
            new_id(), task_id, attempt_id, actor_agent_id, tuple(claims),
            tuple(uncertainties or ()), tuple(assumptions or ()), canonical_digest(body), time.time(),
            declared,
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
                if _normalised_literal(peer.value) == _normalised_literal(claim.value):
                    continue
                input_digest = canonical_digest({"left": peer.value, "right": claim.value, "subject": claim.subject_key})
                self._record_discrepancy("claim.literal_mismatch", claim.subject_key, input_digest, report)
        self._detect_contract_drift(report)

    def _record_discrepancy(
        self, rule_id: str, subject_key: str, input_digest: str, report: CognitiveReport,
    ) -> None:
        """The one place a rule hit becomes a durable, deduplicated discrepancy."""
        version, severity = self.rules[rule_id]
        key = canonical_digest({"rule": rule_id, "subject": subject_key, "input": input_digest})
        if key in self.discrepancies:
            return
        self.discrepancies[key] = Discrepancy(
            new_id(), rule_id, version, subject_key, severity, input_digest, (report.report_id,),
        )

    def _detect_contract_drift(self, report: CognitiveReport) -> None:
        """Judge the incoming report's declared premises against the versions in force.

        A report may declare which contract versions it was produced under. When that
        declaration is not what is in force now, someone is working from an outdated
        agreement -- the mechanical disagreement that only became possible once contracts
        could be revised. Only the incoming report is judged, so history (an earlier
        attempt under an earlier version) never turns into a false positive.
        """
        declared = report.input_revisions.get("contract")
        if not isinstance(declared, (list, tuple)):
            return
        in_force = list(self.current_contract_versions(report.task_id))
        if sorted(str(item) for item in declared) == in_force:
            return
        self._record_discrepancy(
            "claim.contract_digest_mismatch", report.task_id,
            canonical_digest({"declared": sorted(str(item) for item in declared), "in_force": in_force}),
            report,
        )

    def create_discrepancy(
        self, *, subject_ref: str, report_refs: list[str], severity: str,
        summary: str = "", participants: list[Any] | None = None,
        affected_actions: list[Any] | None = None,
    ) -> Discrepancy:
        if not subject_ref:
            raise ValueError("subject_ref_required")
        if severity not in {"soft", "hard", "critical"}:
            raise ValueError("invalid_discrepancy_severity")
        refs = tuple(str(ref) for ref in report_refs if str(ref))
        if not refs:
            raise ValueError("report_refs_required")
        missing = [ref for ref in refs if ref not in self.reports]
        if missing:
            raise KeyError(missing[0])
        input_digest = canonical_digest({
            "subject_ref": subject_ref, "report_refs": refs, "severity": severity,
            "summary": summary, "participants": participants or [],
            "affected_actions": affected_actions or [],
        })
        key = canonical_digest({"rule": "manual.discrepancy", "subject": subject_ref, "input": input_digest})
        existing = self.discrepancies.get(key)
        if existing is not None:
            return existing
        discrepancy = Discrepancy(
            new_id(), "manual.discrepancy", "1", subject_ref, severity,
            input_digest, refs,
        )
        self.discrepancies[key] = discrepancy
        return discrepancy

    def advance_discrepancy(self, discrepancy_id: str, status: str) -> Discrepancy:
        discrepancy = self._discrepancy(discrepancy_id)
        allowed = {"open": {"clarifying"}, "clarifying": {"negotiating"}, "negotiating": set()}
        if status not in allowed.get(discrepancy.status, set()):
            raise ValueError("invalid_discrepancy_transition")
        object.__setattr__(discrepancy, "status", status)
        return discrepancy

    def resolve_discrepancy(self, discrepancy_id: str, kind: str) -> Discrepancy:
        discrepancy = self._discrepancy(discrepancy_id)
        terminal = {"consensus": "resolved", "dismissal": "dismissed", "override": "overridden"}
        if kind not in terminal:
            raise ValueError("invalid_discrepancy_resolution")
        if discrepancy.status in {"resolved", "dismissed", "overridden"}:
            raise ValueError("discrepancy_already_resolved")
        object.__setattr__(discrepancy, "status", terminal[kind])
        return discrepancy

    def _discrepancy(self, discrepancy_id: str) -> Discrepancy:
        for discrepancy in self.discrepancies.values():
            if discrepancy.discrepancy_id == discrepancy_id:
                return discrepancy
        raise KeyError(discrepancy_id)

    def propose_contract(
        self, payload: dict[str, Any], participants: list[dict[str, Any]],
        *, proposed_by: str | None = None, supersedes_id: str | None = None,
    ) -> ContractProposal:
        if not participants:
            raise ValueError("contract_requires_participant")
        if supersedes_id is not None:
            target = self.proposals.get(supersedes_id)
            if target is None:
                raise ValueError("supersede_target_not_found")
            if target.status == "superseded":
                raise ValueError("supersede_target_not_current")
            # A contract has one successor at a time: the replacement chain is what
            # makes "which version is current" mechanical, and two competing
            # successors would leave that ambiguous. A rejected or withdrawn
            # proposal can still be replaced — that is how such a state is left
            # behind.
            if any(
                item.supersedes_id == supersedes_id and item.status in {"proposed", "accepted"}
                for item in self.proposals.values()
            ):
                raise ValueError("supersede_already_pending")
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
        proposal = ContractProposal(
            new_id(), frozen_payload, frozen_participants, required, digest,
            proposed_by=proposed_by, supersedes_id=supersedes_id,
        )
        self.proposals[proposal.proposal_id] = proposal
        return proposal

    def accept_contract(
        self, proposal_id: str, *, participant_slot: str, proposal_digest: str, actor_id: str
    ) -> ContractAcceptance:
        proposal = self.proposals[proposal_id]
        if proposal.status != "proposed":
            raise ValueError("proposal_not_open")
        if proposal.digest != proposal_digest:
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
        # A proxy signs a slot of a live proposal, exactly like the participant would.
        # Without this, a proxy could put a refused or withdrawn proposal back on the
        # books — a one-sided undo of a refusal everyone else already made.
        if proposal.status != "proposed":
            raise ValueError("proposal_not_open")
        if proposal.digest != proposal_digest or participant_slot not in proposal.required_slots:
            raise ValueError("proposal_digest_or_slot_mismatch")
        acceptance = ContractAcceptance(proposal_id, participant_slot, proposal_digest, real_actor_id, represented_participant, True)
        self.acceptances[(proposal_id, participant_slot)] = acceptance
        self._mark_proposal_accepted_if_complete(proposal)
        return acceptance

    def reject_contract(
        self, proposal_id: str, *, proposal_digest: str, actor_id: str, reason: str,
    ) -> ContractProposal:
        proposal = self.proposals[proposal_id]
        if proposal.status != "proposed":
            raise ValueError("proposal_not_open")
        if proposal.digest != proposal_digest:
            raise ValueError("proposal_digest_mismatch")
        participant = next(
            (item for item in proposal.participants if item.get("agent_id") == actor_id), None
        )
        if participant is None:
            raise PermissionError("participant_slot_denied")
        object.__setattr__(proposal, "status", "rejected")
        object.__setattr__(proposal, "resolution_reason", reason)
        return proposal

    def withdraw_contract(self, proposal_id: str, *, actor_id: str, reason: str) -> ContractProposal:
        proposal = self.proposals[proposal_id]
        if proposal.status != "proposed":
            raise ValueError("proposal_not_withdrawable")
        if proposal.proposed_by is not None and proposal.proposed_by != actor_id:
            raise PermissionError("proposal_owner_required")
        object.__setattr__(proposal, "status", "withdrawn")
        object.__setattr__(proposal, "resolution_reason", reason)
        return proposal

    def _mark_proposal_accepted_if_complete(self, proposal: ContractProposal) -> None:
        if all((proposal.proposal_id, slot) in self.acceptances for slot in proposal.required_slots):
            object.__setattr__(proposal, "status", "accepted")
            self._retire_superseded(proposal)

    def _retire_superseded(self, proposal: ContractProposal) -> ContractProposal | None:
        """Retire the contract a completed revision replaces.

        Only a *completed* revision may retire its predecessor. Retiring at proposal
        time would hand any proposer a one-sided veto over a contract everyone had
        already agreed to. A predecessor that is already superseded is left alone.
        """
        if proposal.supersedes_id is None:
            return None
        target = self.proposals.get(proposal.supersedes_id)
        if target is None or target.status == "superseded":
            return None
        object.__setattr__(target, "status", "superseded")
        return target

    def linked_contracts(self, task_id: str) -> dict[str, ContractProposal]:
        """Every proposal that covers this task.

        A payload naming the task is the convention for "this contract covers this
        task"; anything that replaces such a proposal is pulled in as well, so a
        revision inherits the dependency even when its proposer does not repeat the
        task id.
        """
        linked = {
            proposal.proposal_id: proposal
            for proposal in self.proposals.values()
            if isinstance(proposal.payload, dict) and proposal.payload.get("task_id") == task_id
        }
        growing = True
        while growing:
            growing = False
            for proposal in self.proposals.values():
                if proposal.proposal_id in linked or proposal.supersedes_id is None:
                    continue
                if proposal.supersedes_id in linked:
                    linked[proposal.proposal_id] = proposal
                    growing = True
        return linked

    def current_contract_versions(self, task_id: str) -> tuple[str, ...]:
        """The versions in force for a task, as ``"<proposal_id>:<digest>"``.

        These are exactly the strings a caller reads and hands back through
        ``expected_revisions`` when it starts work, which is what turns "I am working
        from the version in force" into something the boundary can check. A task can
        depend on more than one contract, so this is a set rather than one digest.
        """
        return tuple(sorted(
            f"{proposal.proposal_id}:{proposal.digest}"
            for proposal in self.linked_contracts(task_id).values()
            if proposal.status == "accepted"
        ))

    def unaligned_contracts_for_task(self, task_id: str) -> list[ContractProposal]:
        """Contracts a task depends on that no agreement in force covers.

        Aligned means an accepted version is in force *and* nothing is still under
        discussion: a pending revision is precisely the "which version governs" ambiguity
        the contract layer exists to stop, so it holds the boundaries. A rejected or
        withdrawn proposal does not — the accepted version is still the one in force,
        and any participant can settle the ambiguity by rejecting the revision.
        """
        linked = self.linked_contracts(task_id)
        if any(proposal.status == "accepted" for proposal in linked.values()):
            unaligned = [
                proposal for proposal in linked.values() if proposal.status == "proposed"
            ]
        else:
            # Nothing is in force yet, so every declared version is still an open demand.
            unaligned = list(linked.values())
        return sorted(unaligned, key=lambda proposal: proposal.proposal_id)

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
