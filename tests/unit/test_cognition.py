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
        real_actor_id="main", represented_participant="w", main_allowed=True,
    )
    acceptance = service.acceptances[(proposal.proposal_id, "worker")]
    assert acceptance.real_actor_id == "main"
    assert acceptance.represented_participant == "w"
    assert acceptance.via_proxy is True
    assert proposal.status == "accepted"


@pytest.mark.parametrize("terminal", ["withdrawn", "rejected", "superseded", "accepted"])
@pytest.mark.parametrize("proxy", [False, True])
def test_terminal_proposal_cannot_be_accepted_again(terminal: str, proxy: bool) -> None:
    service = CognitionService()
    participants = [{"slot": "writer", "agent_id": "worker", "required": True}]
    proposal = service.propose_contract({}, participants, proposed_by="main")
    if terminal == "withdrawn":
        service.withdraw_contract(proposal.proposal_id, actor_id="main", reason="changed")
    elif terminal == "rejected":
        service.reject_contract(proposal.proposal_id, proposal_digest=proposal.digest, actor_id="worker", reason="no")
    elif terminal == "superseded":
        service.supersede_contract(proposal.proposal_id, {"new": True}, participants)
    else:
        service.accept_contract(proposal.proposal_id, participant_slot="writer", proposal_digest=proposal.digest, actor_id="worker")
    before = dict(service.acceptances)
    with pytest.raises(ValueError, match="proposal_not_proposed"):
        if proxy:
            service.accept_proxy(proposal.proposal_id, participant_slot="writer", proposal_digest=proposal.digest,
                                 real_actor_id="main", represented_participant="worker", main_allowed=True)
        else:
            service.accept_contract(proposal.proposal_id, participant_slot="writer", proposal_digest=proposal.digest, actor_id="worker")
    assert proposal.status == terminal
    assert service.acceptances == before
    with pytest.raises(ValueError, match="proposal_not_proposed"):
        service._mark_proposal_accepted_if_complete(proposal)


@pytest.mark.parametrize("participants", [
    ["worker"], [{"slot": "writer", "required": True}],
    [{"slot": " ", "agent_id": "worker", "required": True}],
    [{"slot": "writer", "agent_id": "\t", "required": True}],
    [{"slot": 1, "agent_id": "worker", "required": True}],
    [{"slot": "writer", "agent_id": "worker", "required": "yes"}],
    [{"slot": "writer", "agent_id": "worker", "required": True},
     {"slot": "writer", "agent_id": "another", "required": False}],
])
def test_invalid_participants_make_no_proposal(participants) -> None:
    service = CognitionService()
    with pytest.raises(ValueError):
        service.propose_contract({}, participants)
    assert not service.proposals


def test_proxy_checks_identity_and_slots_and_preserves_partial_acceptance() -> None:
    service = CognitionService()
    proposal = service.propose_contract({}, [
        {"slot": "writer", "agent_id": "worker", "required": True},
        {"slot": "reviewer", "agent_id": "worker", "required": True},
        {"slot": "observer", "agent_id": "other", "required": False},
    ])
    for slot, represented in [("missing", "worker"), ("writer", "writer")]:
        with pytest.raises(PermissionError, match="participant_slot_denied"):
            service.accept_proxy(proposal.proposal_id, participant_slot=slot, proposal_digest=proposal.digest,
                                 real_actor_id="main", represented_participant=represented, main_allowed=True)
    with pytest.raises(PermissionError, match="proxy_not_allowed"):
        service.accept_proxy(proposal.proposal_id, participant_slot="writer", proposal_digest=proposal.digest,
                             real_actor_id="other", represented_participant="worker", main_allowed=False)
    assert not service.acceptances
    service.accept_contract(proposal.proposal_id, participant_slot="writer", proposal_digest=proposal.digest, actor_id="worker")
    assert proposal.status == "proposed"
    with pytest.raises(ValueError, match="participant_already_accepted"):
        service.accept_proxy(proposal.proposal_id, participant_slot="writer", proposal_digest=proposal.digest,
                             real_actor_id="main", represented_participant="worker", main_allowed=True)
    assert service.acceptances[(proposal.proposal_id, "writer")].real_actor_id == "worker"
    service.accept_proxy(proposal.proposal_id, participant_slot="reviewer", proposal_digest=proposal.digest,
                         real_actor_id="main", represented_participant="worker", main_allowed=True)
    assert proposal.status == "accepted"


def test_supersede_validates_before_mutation_and_preserves_owner() -> None:
    service = CognitionService()
    participants = [{"slot": "writer", "agent_id": "worker", "required": True}]
    proposal = service.propose_contract({}, participants, proposed_by="main")
    with pytest.raises(ValueError):
        service.supersede_contract(proposal.proposal_id, {}, [])
    assert proposal.status == "proposed"
    assert len(service.proposals) == 1
    replacement = service.supersede_contract(proposal.proposal_id, {}, participants)
    assert replacement.proposed_by == "main"
    assert proposal.status == "superseded"
    with pytest.raises(ValueError, match="proposal_not_supersedable"):
        service.supersede_contract(proposal.proposal_id, {}, participants)
    assert len(service.proposals) == 2


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
