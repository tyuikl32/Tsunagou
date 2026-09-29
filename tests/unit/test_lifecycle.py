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


def test_the_proposer_owns_the_answer_vocabulary(tmp_path: Path) -> None:
    """`choices` 是提案方给的词表，用户答的就是其中一个真实值。

    设计口径在 `docs/standalone/debugging-runbook.md`（B5）："阅读后按该决定 `choices`
    中的真实值填写；以下选择 `approved` 只用于该选项确实存在时"。所以：

    * 提案方给了选项 → 只收那些选项（`approved` 不在其中就**不**收：不能把用户没选过的
      词记成"他选的"）；
    * 提案方没给选项 → 退回 `approved`/`rejected` 这两个机械兜底（完成提案不带 `choices`）。
    """

    service = make_lifecycle(tmp_path)
    offered = service.request_decision(
        kind="design.change", subject_ref="task/t1",
        payload={"choices": ["再补一轮回归", {"label": "换方案"}], "summary": "选一条路"},
        expected_revision=1,
    )
    assert service.answerable_values(offered) == ("再补一轮回归", "换方案")

    for wrong in ("approved", "确认完成", ""):
        with pytest.raises(ValueError, match="invalid_decision"):
            service.resolve_decision(
                offered.decision_id, actor_kind="user_control", decision=wrong, input_digest=offered.input_digest,
            )

    # 选项里的第二个是 {label: …} 形状，答它一样算数，记下来的就是那个词。
    resolved = service.resolve_decision(
        offered.decision_id, actor_kind="user_control", decision="换方案", input_digest=offered.input_digest,
    )
    assert (resolved.status, resolved.decision) == ("resolved", "换方案")
    with pytest.raises(ValueError, match="conflict"):
        service.resolve_decision(
            offered.decision_id, actor_kind="user_control", decision="再补一轮回归",
            input_digest=offered.input_digest,
        )

    # 没有选项的决定（完成提案这一类）照旧收 approved/rejected。
    bare = service.request_decision(kind="project.complete", subject_ref="project", payload={}, expected_revision=1)
    assert service.answerable_values(bare) == ("approved", "rejected")
    with pytest.raises(ValueError, match="invalid_decision"):
        service.resolve_decision(
            bare.decision_id, actor_kind="user_control", decision="随便什么", input_digest=bare.input_digest,
        )
    assert service.resolve_decision(
        bare.decision_id, actor_kind="user_control", decision="approved", input_digest=bare.input_digest,
    ).decision == "approved"


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
