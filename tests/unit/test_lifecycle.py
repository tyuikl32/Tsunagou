from pathlib import Path

import pytest

from tsunagou.application.workflows.lifecycle import LifecycleService
from tsunagou.modules.authority import AuthorityService
from tsunagou.modules.projects import ProjectRegistry
from tsunagou.shared_kernel.baseline import BASELINE_CAPABILITIES


def make_lifecycle(tmp_path: Path) -> LifecycleService:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    registry = ProjectRegistry.initialize(repo, name="demo", objective="x")
    return LifecycleService(registry=registry, authority=AuthorityService(tmp_path / "auth.json"))


def test_user_decision_exact_digest_and_completion_survives_checkpoint_failure(tmp_path: Path) -> None:
    service = make_lifecycle(tmp_path)
    decision = service.request_decision(kind="project.complete", subject_ref="project", payload={"x": 1}, expected_revision=1)
    with pytest.raises(PermissionError):
        service.resolve_decision(decision.decision_id, actor_kind="main", decision="approved", input_digest=decision.input_digest)
    service.resolve_decision(decision.decision_id, actor_kind="user_control", decision="approved", input_digest=decision.input_digest)
    operation_id = service.complete_project(expected_revision=1, evidence_refs=[], request_checkpoint=lambda _: "op-1")
    service.checkpoint_result(operation_id, success=False, reason="disk full")
    assert service.registry.project.lifecycle == "completed"
    with pytest.raises(ValueError, match="barrier"):
        service.archive_project(checkpoint_operation_id=operation_id)


def test_reset_invalidates_old_runtime_and_unknown_resolution_is_append_only(tmp_path: Path) -> None:
    service = make_lifecycle(tmp_path)
    main = service.authority.redeem_ticket(
        service.authority.issue_ticket("i", "c"), "i", "c", baseline={"baseline": {
            name: {"status": "supported", "evidence_refs": [f"fixture:{name}"]}
            for name in BASELINE_CAPABILITIES
        }}
    )
    service.authority.appoint_main(actor_kind="user_control", agent_id=main.agent_id)
    old_lineage = service.registry.project.current_lineage_id
    reset = service.reset_lineage()
    assert reset["old_lineage_id"] == old_lineage
    assert service.authority.sessions[main.session_id].active is False
    first = service.resolve_unknown(operation_id="op", actor="main", conclusion="risk_accepted", evidence_refs=[], reason="known")
    second = service.resolve_unknown(operation_id="op", actor="user", conclusion="verified_failed", evidence_refs=[], reason="receipt")
    assert first != second and len(service.resolutions) == 2
