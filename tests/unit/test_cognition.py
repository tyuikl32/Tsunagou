import pytest

from tsunagou.modules.cognition import Claim, CognitionService, RiskSubmission


def test_explicit_claim_difference_creates_deterministic_discrepancy_not_text_inference() -> None:
    service = CognitionService()
    service.submit_report(
        task_id="t", attempt_id="a1", actor_agent_id="a1",
        claims=[Claim("design", "literal", "value", "sqlite")],
        uncertainties=["migration behavior"],
    )
    service.submit_report(
        task_id="t", attempt_id="a2", actor_agent_id="a2",
        claims=[Claim("design", "literal", "value", "postgres")],
    )
    assert len(service.discrepancies) == 1
    assert next(iter(service.discrepancies.values())).severity == "hard"


def test_contract_requires_exact_digest_and_proxy_preserves_real_actor() -> None:
    service = CognitionService()
    proposal = service.propose_contract(
        {"objective": "ship"},
        [{"slot": "main", "agent_id": "main", "required": True}, {"slot": "worker", "agent_id": "w", "required": True}],
    )
    with pytest.raises(ValueError, match="digest"):
        service.accept_contract(proposal.proposal_id, participant_slot="main", proposal_digest="old", actor_id="main")
    service.accept_contract(proposal.proposal_id, participant_slot="main", proposal_digest=proposal.digest, actor_id="main")
    service.accept_proxy(
        proposal.proposal_id, participant_slot="worker", proposal_digest=proposal.digest,
        real_actor_id="main", represented_participant="worker", main_allowed=True,
    )
    acceptance = service.acceptances[(proposal.proposal_id, "worker")]
    assert acceptance.real_actor_id == "main"
    assert acceptance.via_proxy is True
    assert proposal.status == "accepted"


def test_risk_input_changes_invalidate_and_unknown_never_becomes_success() -> None:
    service = CognitionService()
    request = service.request_risk(
        attempt_id="a", input_snapshot={"scope": 1},
        candidates=[{"driver": "shared", "hard_constraints_met": True}], now=0,
    )
    with pytest.raises(ValueError, match="digest"):
        service.submit_risk(RiskSubmission(request.request_id, "assessor", "low", "ok", "shared", {}, (), (), "bad"))
    assert service.fallback_risk(request.request_id, now=121)["driver"] == "shared"
    with pytest.raises(PermissionError):
        service.accept_risk(
            subject_ref="attempt/a", actor_main_id="main", reason="x",
            accepted_risks=["high"], input_digest="d", ceiling_allows=lambda _: False,
        )
    accepted = service.accept_risk(
        subject_ref="attempt/a", actor_main_id="main", reason="x",
        accepted_risks=["unknown"], input_digest="d", ceiling_allows=lambda _: True,
    )
    assert accepted.effective_outcome == "risk_accepted_unknown"
