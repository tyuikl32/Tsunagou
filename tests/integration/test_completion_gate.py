"""完工门（待改 17）：没有确认过的目标不许完工，没有锚点必须说出来。

2026-10-08 在真机项目 `4816f3fa…` 上量到的事实：项目 `lifecycle=completed`，而
`objective` 仍是占位符 `'待主 Agent 与用户确认'`、完工决策的 `objective_ref` 是空的，
交付根不是 git 仓库、`repositories = {}`、也没有任何存档点。也就是说——
一个从未与用户商定过目标的协作可以走到"已完成"，而被验收的那一版内容不在任何版本控制之下。

这两件事都不是"用户不能接受"：这是**用户**的决定。要修的是它们**不被告知**：
完工门现在要求目标已确认（拒绝时说出该用哪个引用），并把锚点事实写进提案、
写进确认的返回，让用户在点确认之前就能看见。
"""

from __future__ import annotations

import json
import subprocess
from importlib.resources import files
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Response

from tsunagou.api.app import CommandRequest
from tsunagou.bootstrap.container import build_application
from tsunagou.modules.projects import ProjectRegistry
from tsunagou.shared_kernel.baseline import ADMISSION_CAPABILITIES
from tsunagou.shared_kernel.ids import new_id

GOAL_REFERENCE = "objective/borrow-a-book-site"


def _decisions(app: Any) -> list[dict[str, Any]]:
    """The console's own exit: what a pending decision card is drawn from."""

    endpoint = next(route.endpoint for route in app.routes if getattr(route, "path", "") == "/api/v1/decisions")
    return endpoint(authorization="Bearer control", session_id=None, connection_epoch=None)["items"]


def _caller(app: Any) -> Any:
    endpoint = next(route.endpoint for route in app.routes if getattr(route, "path", "") == "/api/v1/commands/{command_kind}")
    command_registry = json.loads(files("tsunagou.protocol_data").joinpath("registry", "commands.json").read_text(encoding="utf-8"))

    def call(kind: str, payload: dict[str, Any], authorization: str, receipt: dict[str, Any] | None = None) -> dict[str, Any]:
        request = CommandRequest(
            command_id=new_id(), protocol_version="1.0",
            schema_bundle_digest=command_registry["schema_bundle_digest"], payload=payload,
        )
        return endpoint(
            kind, request, Response(), f"Bearer {authorization}",
            receipt.get("session_id") if receipt else None,
            receipt.get("connection_epoch") if receipt else None,
        )["result"]

    return call


def _refusal(call: Any, kind: str, payload: dict[str, Any], authorization: str,
             receipt: dict[str, Any] | None = None) -> dict[str, Any]:
    """The daemon's refusal body, which is what a caller (and the bridge) actually gets."""

    try:
        call(kind, payload, authorization, receipt)
    except HTTPException as exc:
        detail = exc.detail
        assert isinstance(detail, dict), detail
        return detail
    raise AssertionError(f"{kind} was accepted, expected a refusal")


def _main_agent(app: Any, call: Any, identity: str) -> dict[str, Any]:
    conversation = {"installation_id": identity, "conversation_evidence": {"conversation_id": identity}}
    ticket = call("agent.ticket.create.user", conversation, "control")
    main = call("agent.enroll", {
        **conversation,
        "probe_payload": {"baseline": {
            name: {"status": "supported", "evidence_refs": [f"fixture:{name}"]}
            for name in ADMISSION_CAPABILITIES
        }},
    }, ticket["secret"])
    call("authority.appoint", {"agent_id": main["agent_id"]}, "control")
    return main


def _app(tmp_path: Path, monkeypatch: Any, name: str) -> Any:
    # 协作根必须是 git 仓库（``coordination_repository_must_be_git_repository``）——
    # 这不是本文件的要求，是项目自己的前提。
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    monkeypatch.setenv("TSUNAGOU_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("TSUNAGOU_STATE_DIR", str(tmp_path / ".tsunagou" / "local"))
    monkeypatch.setenv("TSUNAGOU_CONTROL_TOKEN", "control")
    registry = ProjectRegistry.initialize(tmp_path, name=name, objective="completion gate")
    assert registry.project is not None
    return build_application()


def _propose_goal(call: Any, main: dict[str, Any]) -> dict[str, Any]:
    return call("user_decision.propose", {
        "kind": "project.objective", "proposal_ref": GOAL_REFERENCE,
        "summary": "borrow-a-book site", "choices": ["approved", "rejected"],
    }, main["secret_token"], main)


def _resolve_goal(call: Any, goal: dict[str, Any]) -> dict[str, Any]:
    return call("user_decision.resolve", {
        "decision_id": goal["decision_id"], "choice": "approved",
        "proposal_digest": goal["proposal_digest"],
        "expected_revisions": {"decision": goal["revision"]},
    }, "control")


def test_completion_is_refused_until_the_user_confirms_a_goal(tmp_path: Path, monkeypatch: Any) -> None:
    """No goal agreed, or a goal the user has not answered yet: no completion proposal."""

    app = _app(tmp_path, monkeypatch, "no-goal")
    call = _caller(app)
    main = _main_agent(app, call, "completion-gate-no-goal")

    refusal = _refusal(call, "project.completion.propose.main", {
        "expected_project_revision": 1, "objective_ref": GOAL_REFERENCE,
        "outstanding_summary": "none", "evidence_refs": [],
    }, main["secret_token"], main)
    assert refusal["code"] == "project_objective_not_confirmed"
    # 拒绝要说出下一步，而不是只说"不行"：这正是 待改 1 那一族的要求。
    assert "user_decision.propose" in refusal["next"]
    assert refusal["confirmed_objective_ref"] is None
    assert _decisions(app) == []

    # 目标"提了、用户还没答"也不算确认 —— 占位符与待决都不许当成目标。
    pending = _propose_goal(call, main)
    assert pending["status"] == "pending"
    refusal = _refusal(call, "project.completion.propose.main", {
        "expected_project_revision": 1, "objective_ref": GOAL_REFERENCE,
        "outstanding_summary": "none", "evidence_refs": [],
    }, main["secret_token"], main)
    assert refusal["code"] == "project_objective_not_confirmed"


def test_completion_must_name_the_goal_the_user_confirmed(tmp_path: Path, monkeypatch: Any) -> None:
    """A confirmed goal exists, but the proposal names a different reference."""

    app = _app(tmp_path, monkeypatch, "wrong-ref")
    call = _caller(app)
    main = _main_agent(app, call, "completion-gate-wrong-ref")
    _resolve_goal(call, _propose_goal(call, main))

    refusal = _refusal(call, "project.completion.propose.main", {
        "expected_project_revision": 1, "objective_ref": "objective/something-else",
        "outstanding_summary": "none", "evidence_refs": [],
    }, main["secret_token"], main)
    assert refusal["code"] == "project_objective_ref_mismatch"
    # 撞墙的人手上要有"该填哪个"：把确认过的那一个引用原地给出。
    assert refusal["confirmed_objective_ref"] == GOAL_REFERENCE
    assert GOAL_REFERENCE in refusal["next"]

    # 上下文里也读得到同一个引用（两处必须同源，否则主 Agent 只能靠猜）。
    read = call("context.project_read", {}, main["secret_token"], main)
    assert read["stable"]["goal"]["objective_ref"] == GOAL_REFERENCE
    assert read["stable"]["goal"]["confirmed"] is True


def test_an_unanchored_delivery_is_named_before_the_user_confirms(tmp_path: Path, monkeypatch: Any) -> None:
    """The measured case: no repository, no checkpoint, not a git tree — say so, loudly."""

    app = _app(tmp_path, monkeypatch, "unanchored")
    call = _caller(app)
    main = _main_agent(app, call, "completion-gate-unanchored")
    _resolve_goal(call, _propose_goal(call, main))

    proposal = call("project.completion.propose.main", {
        "expected_project_revision": 1, "objective_ref": GOAL_REFERENCE,
        "outstanding_summary": "the site is finished",
        "evidence_refs": ["task:none"],
    }, main["secret_token"], main)
    anchoring = proposal["anchoring"]
    assert anchoring["anchored"] is False
    assert anchoring["repositories"] == []
    assert "no registered repository" in anchoring["warning"]

    # 卡片上"这一条在说什么"取的是 payload 的 title/summary（web/assets/js/behavior.js 的
    # render.overview）。所以提示必须落在用户**点确认之前**就能读到的那两个字段里。
    payload = next(item["payload"] for item in _decisions(app) if item["decision_id"] == proposal["proposal_id"])
    assert payload["title"] == "the site is finished"
    assert "没有锚点" in payload["summary"]
    assert payload["anchoring"]["anchored"] is False

    confirmed = call("project.completion.confirm", {
        "proposal_id": proposal["proposal_id"],
        "expected_project_revision": 1,
        "expected_revisions": {"decision": proposal["revision"]},
        "proposal_digest": proposal["proposal_digest"],
    }, "control")
    assert confirmed["status"] == "completed"
    assert confirmed["objective_ref"] == GOAL_REFERENCE
    # 确认这一步也要把事实留在返回里：用户接受了，但"没有锚点"不能就此消失。
    assert "no registered repository" in confirmed["anchoring_warning"]


def test_a_registered_repository_and_a_checkpoint_count_as_anchoring(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    """Anchoring is reported as facts, not as a verdict: repository + checkpoint = anchored."""

    app = _app(tmp_path, monkeypatch, "repo-and-checkpoint")
    call = _caller(app)
    main = _main_agent(app, call, "completion-gate-repo")
    _resolve_goal(call, _propose_goal(call, main))

    root = call("root.register", {
        "name": "delivery", "kind": "directory",
        "binding_request": {"absolute_path": str(tmp_path)},
        "repository_id": "unused-by-the-handler", "required": True,
        "reason": "the completion gate reports what the delivery is anchored to",
    }, main["secret_token"], main)
    branch = call("repository.register", {
        "name": "delivery", "root_id": root["root_id"], "required": True,
    }, main["secret_token"], main)

    proposal = call("project.completion.propose.main", {
        "expected_project_revision": 1, "objective_ref": GOAL_REFERENCE,
        "outstanding_summary": "none", "evidence_refs": [],
    }, main["secret_token"], main)
    anchoring = proposal["anchoring"]
    assert anchoring["repositories"] == [branch["repository_id"]]
    assert anchoring["git_roots"] == ["delivery"]
    assert anchoring["checkpoint_digest"] is not None
    assert anchoring["anchored"] is True
    assert anchoring["warning"] is None

    payload = next(item["payload"] for item in _decisions(app) if item["decision_id"] == proposal["proposal_id"])
    assert "目标已由用户确认" in payload["summary"]

    confirmed = call("project.completion.confirm", {
        "proposal_id": proposal["proposal_id"],
        "expected_project_revision": 1,
        "expected_revisions": {"decision": proposal["revision"]},
        "proposal_digest": proposal["proposal_digest"],
    }, "control")
    assert confirmed["status"] == "completed"
    assert "anchoring_warning" not in confirmed


def test_a_missing_checkpoint_is_reported_even_with_a_repository(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    """The second layer of the same fact: the repository is named, the version is not pinned."""

    app = _app(tmp_path, monkeypatch, "repo-without-checkpoint")
    call = _caller(app)
    main = _main_agent(app, call, "completion-gate-no-checkpoint")
    _resolve_goal(call, _propose_goal(call, main))
    root = call("root.register", {
        "name": "delivery", "kind": "directory",
        "binding_request": {"absolute_path": str(tmp_path)},
        "repository_id": "unused-by-the-handler", "required": True, "reason": "anchor the delivery",
    }, main["secret_token"], main)
    call("repository.register", {"name": "delivery", "root_id": root["root_id"], "required": True},
         main["secret_token"], main)
    # 没有存档点这一档：真机上存档点是随 daemon 起来的（2026-10-08 实测 `current.json` 在），
    # 但"存档点丢了/还没落成"是必须报得出来的状态，所以把指针指到一个不存在的位置。
    monkeypatch.setattr(app.state.checkpoint_store, "pointer", tmp_path / "no-such-pointer.json")

    proposal = call("project.completion.propose.main", {
        "expected_project_revision": 1, "objective_ref": GOAL_REFERENCE,
        "outstanding_summary": "none", "evidence_refs": [],
    }, main["secret_token"], main)
    anchoring = proposal["anchoring"]
    assert anchoring["repositories"]
    assert anchoring["checkpoint_digest"] is None
    assert "no checkpoint" in anchoring["warning"]
