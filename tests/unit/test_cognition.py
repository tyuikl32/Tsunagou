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


def test_literal_claims_differing_only_in_writing_are_not_discrepancies() -> None:
    """Surrounding whitespace, letter case and equivalent number spellings are
    presentation rather than disagreement: reporting them would be a false positive."""
    service = CognitionService()
    service.submit_report(
        task_id="t", attempt_id="a1", actor_agent_id="a1",
        claims=[Claim("workspace.driver", "literal", "workspace.driver", "  Shared  ")],
    )
    service.submit_report(
        task_id="t", attempt_id="a2", actor_agent_id="a2",
        claims=[
            Claim("workspace.driver", "literal", "workspace.driver", "shared"),
            Claim("api.retries", "literal", "api.retries", 1),
        ],
    )
    service.submit_report(
        task_id="t", attempt_id="a3", actor_agent_id="a3",
        claims=[Claim("api.retries", "literal", "api.retries", 1.0)],
    )
    assert service.discrepancies == {}


def test_a_type_difference_is_still_a_disagreement() -> None:
    """``"1"`` and ``1`` disagree about the wire type, so normalisation must keep it."""
    service = CognitionService()
    service.submit_report(
        task_id="t", attempt_id="a1", actor_agent_id="a1",
        claims=[Claim("api.retries", "literal", "api.retries", 1)],
    )
    service.submit_report(
        task_id="t", attempt_id="a2", actor_agent_id="a2",
        claims=[Claim("api.retries", "literal", "api.retries", "1")],
    )
    assert len(service.discrepancies) == 1


def test_nested_values_are_compared_after_normalisation() -> None:
    """Structured values are still compared as a whole, but normalised recursively."""
    service = CognitionService()
    service.submit_report(
        task_id="t", attempt_id="a1", actor_agent_id="a1",
        claims=[Claim("scope", "literal", "scope", {"mode": "Shared", "paths": ["Src/Api"]})],
    )
    service.submit_report(
        task_id="t", attempt_id="a2", actor_agent_id="a2",
        claims=[Claim("scope", "literal", "scope", {"paths": ["src/api"], "mode": "shared"})],
    )
    assert service.discrepancies == {}


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


def _propose(
    service: CognitionService, *, task_id: str = "t", supersedes_id: str | None = None
):
    return service.propose_contract(
        {"task_id": task_id},
        [{"slot": "worker", "agent_id": "worker", "required": True}],
        proposed_by="main", supersedes_id=supersedes_id,
    )


def _accept(service: CognitionService, proposal) -> None:
    service.accept_contract(
        proposal.proposal_id, participant_slot="worker",
        proposal_digest=proposal.digest, actor_id="worker",
    )


def test_a_revision_retires_its_predecessor_only_once_it_is_complete() -> None:
    """Proposing a replacement changes nothing by itself.

    Retiring the old version at proposal time would give any proposer a one-sided
    veto over a contract everyone had already agreed to, so the old version only goes
    out of force when every required slot of the new one has accepted.
    """
    service = CognitionService()
    first = _propose(service)
    _accept(service, first)

    second = _propose(service, supersedes_id=first.proposal_id)
    assert first.status == "accepted"

    _accept(service, second)
    assert second.status == "accepted"
    assert first.status == "superseded"


def test_a_pending_revision_holds_the_task_and_a_refusal_releases_it() -> None:
    """While a revision is undecided, nobody can say which version governs, so the
    start/submit boundaries are held. Refusing it settles that for free: the accepted
    version is still the one in force, and no task is frozen by a rejection."""
    service = CognitionService()
    first = _propose(service)
    _accept(service, first)
    assert service.unaligned_contracts_for_task("t") == []

    second = _propose(service, supersedes_id=first.proposal_id)
    assert service.unaligned_contracts_for_task("t") == [second]

    service.reject_contract(
        second.proposal_id, proposal_digest=second.digest, actor_id="worker", reason="no"
    )
    assert service.unaligned_contracts_for_task("t") == []
    assert first.status == "accepted"

    # A refused revision is not a dead end: it can still be replaced, and completing
    # that replacement is what takes it off the books.
    third = _propose(service, supersedes_id=first.proposal_id)
    _accept(service, third)
    assert third.status == "accepted"
    assert first.status == "superseded"
    assert service.unaligned_contracts_for_task("t") == []


def test_a_task_stays_blocked_while_no_version_is_in_force() -> None:
    """A declared dependency that nobody has agreed to is still an open demand, so
    work cannot be delivered under it — and a fresh version is the way out."""
    service = CognitionService()
    only = _propose(service)
    service.reject_contract(
        only.proposal_id, proposal_digest=only.digest, actor_id="worker", reason="no"
    )
    assert service.unaligned_contracts_for_task("t") == [only]

    replacement = _propose(service)
    _accept(service, replacement)
    assert service.unaligned_contracts_for_task("t") == []


def test_a_revision_inherits_the_dependency_without_repeating_the_task_id() -> None:
    """The task id is a convention on the payload; a revision that does not repeat it
    is still judged for the task, through the replacement chain."""
    service = CognitionService()
    first = _propose(service)
    _accept(service, first)
    second = service.propose_contract(
        {"label": "后端接口契约 v2"},
        [{"slot": "worker", "agent_id": "worker", "required": True}],
        proposed_by="main", supersedes_id=first.proposal_id,
    )

    assert service.unaligned_contracts_for_task("t") == [second]
    assert service.unaligned_contracts_for_task("other") == []


def test_the_versions_in_force_are_what_a_task_must_declare() -> None:
    """A declaration is only checkable against a version that is in force, so what is in
    force has to be derivable: the agreed versions covering the task, and nothing else.
    A revision under discussion does not count until it is agreed."""
    service = CognitionService()
    first = _propose(service)
    _accept(service, first)
    assert service.current_contract_versions("t") == (f"{first.proposal_id}:{first.digest}",)

    second = _propose(service, supersedes_id=first.proposal_id)
    assert service.current_contract_versions("t") == (f"{first.proposal_id}:{first.digest}",)

    _accept(service, second)
    assert service.current_contract_versions("t") == (f"{second.proposal_id}:{second.digest}",)
    assert service.current_contract_versions("other") == ()


def test_a_report_declaring_a_version_that_is_no_longer_in_force_is_a_hard_disagreement() -> None:
    """Once contracts can be revised, "I am working from the old agreement" stops being
    impossible and becomes merely undetectable. The declared premises are what make it
    detectable, and the severity is hard because a wrong premise invalidates the work."""
    service = CognitionService()
    first = _propose(service)
    _accept(service, first)
    second = _propose(service, supersedes_id=first.proposal_id)
    _accept(service, second)

    service.submit_report(
        task_id="t", attempt_id="a1", actor_agent_id="a1", claims=[],
        input_revisions={"contract": [f"{first.proposal_id}:{first.digest}"]},
    )

    (discrepancy,) = service.discrepancies.values()
    assert discrepancy.rule_id == "claim.contract_digest_mismatch"
    assert discrepancy.severity == "hard"
    assert discrepancy.subject_key == "t"


def test_a_report_declaring_the_version_in_force_is_not_a_disagreement() -> None:
    service = CognitionService()
    only = _propose(service)
    _accept(service, only)

    service.submit_report(
        task_id="t", attempt_id="a1", actor_agent_id="a1", claims=[],
        input_revisions={"contract": [f"{only.proposal_id}:{only.digest}"]},
    )

    assert service.discrepancies == {}


def test_a_report_that_declares_nothing_is_not_judged_for_contract_drift() -> None:
    """Only the declaration makes a drift checkable. Judging undeclared reports would
    turn every report into noise, which is the opposite of what this rule is for -- and
    it is also why a revision landing mid-attempt cannot retroactively condemn an
    earlier, honestly undeclared report."""
    service = CognitionService()
    only = _propose(service)
    _accept(service, only)

    service.submit_report(task_id="t", attempt_id="a1", actor_agent_id="a1", claims=[])
    service.submit_report(
        task_id="t", attempt_id="a2", actor_agent_id="a2", claims=[],
        input_revisions={"task": 1},
    )

    assert service.discrepancies == {}


def test_a_closed_proposal_cannot_be_revived_by_a_proxy() -> None:
    """A proxy signs a slot of a live proposal, exactly like the participant would.

    Accepting an already refused or withdrawn proposal would undo, one-sidedly, a
    decision someone else already made: only agreement on a *new* version may take a
    proposal out of play.
    """
    service = CognitionService()
    refused = _propose(service)
    service.reject_contract(
        refused.proposal_id, proposal_digest=refused.digest, actor_id="worker", reason="no"
    )

    with pytest.raises(ValueError, match="proposal_not_open"):
        service.accept_proxy(
            refused.proposal_id, participant_slot="worker", proposal_digest=refused.digest,
            real_actor_id="main", represented_participant="worker", main_allowed=True,
        )
    assert refused.status == "rejected"
    assert service.acceptances == {}

    dropped = _propose(service)
    service.withdraw_contract(dropped.proposal_id, actor_id="main", reason="rethink")
    with pytest.raises(ValueError, match="proposal_not_open"):
        service.accept_proxy(
            dropped.proposal_id, participant_slot="worker", proposal_digest=dropped.digest,
            real_actor_id="main", represented_participant="worker", main_allowed=True,
        )
    assert dropped.status == "withdrawn"


def test_a_refusal_keeps_its_reason() -> None:
    """The audit trail stores no free text, so the owning domain has to keep why a
    proposal stopped being open — otherwise the reason is unrecoverable, and "why was
    this refused" is the entire semantic content of a refusal."""
    service = CognitionService()
    refused = _propose(service)
    service.reject_contract(
        refused.proposal_id, proposal_digest=refused.digest, actor_id="worker",
        reason="接口字段对不上",
    )
    assert refused.resolution_reason == "接口字段对不上"

    dropped = _propose(service)
    service.withdraw_contract(dropped.proposal_id, actor_id="main", reason="先不定了")
    assert dropped.resolution_reason == "先不定了"


def test_replacement_targets_are_validated() -> None:
    """The chain is what makes "which version is current" mechanical, so it is kept
    linear: one successor at a time, and only for a version not yet replaced."""
    service = CognitionService()
    first = _propose(service)
    _accept(service, first)
    second = _propose(service, supersedes_id=first.proposal_id)

    with pytest.raises(ValueError, match="supersede_already_pending"):
        _propose(service, supersedes_id=first.proposal_id)
    with pytest.raises(ValueError, match="supersede_target_not_found"):
        _propose(service, supersedes_id="missing")

    _accept(service, second)
    with pytest.raises(ValueError, match="supersede_target_not_current"):
        _propose(service, supersedes_id=first.proposal_id)
