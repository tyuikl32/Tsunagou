"""Fresh-state public command integration for explicit execution ownership."""

from __future__ import annotations

import contextlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi import HTTPException, Response
from tests.integration.test_m1_runtime_flow import _endpoint
from tests.integration.test_state_integrity import events
from tests.integration.test_state_integrity import runtime as _runtime_fixture

from tsunagou.api.app import CommandRequest
from tsunagou.bootstrap.container import build_application
from tsunagou.shared_kernel.ids import new_id


@pytest.fixture(name="runtime")
def execution_runtime(tmp_path, monkeypatch):
    yield from _runtime_fixture.__wrapped__(tmp_path, monkeypatch)


def published(call, main, *, files=False, **extra):
    scope = (
        {"resources": [{"kind": "path", "root_id": "coordination", "segments": ["demo.txt"], "mode": "exclusive_write"}]} if files else {}
    )
    task = call("task.create", {"title": "write", "objective": "produce output", "execution_scope": scope, **extra}, main)
    if files:
        call("workspace.select", {"task_id": task["task_id"], "driver_kind": "shared"}, main)
    call("task.ready", {"task_id": task["task_id"]}, main)
    return call("task.publish", {"task_id": task["task_id"]}, main)


def begin(call, task, worker, **kwargs):
    return call("task.begin", {"task_id": task["task_id"], "expected_task_revision": task["revision"]}, worker, **kwargs)


def test_nonfile_begin_submit_needs_no_workspace_resource_or_ready(runtime):
    app, call, main, worker = runtime
    task = published(call, main)
    started = begin(call, task, worker)
    assert started["status"] == "running"
    assert started["workspace_id"] is None and started["reservation_id"] is None
    assert not app.state.state_runtime.resources.reservations
    result = call("task.submit", {"task_id": task["task_id"], "attempt_id": started["attempt_id"], "summary": "done"}, worker)
    assert result["status"] == "submitted"
    assert not [
        g for g in app.state.state_runtime.authority.grants.values() if g.attempt_id == started["attempt_id"] and g.status == "active"
    ]


def test_worker_can_discover_begin_inputs_without_main_credentials(runtime):
    app, call, main, worker = runtime
    task = published(call, main, files=True)
    context = call("context.project_read", {}, worker)
    available = next(row for row in context["open_tasks"] if row["task_id"] == task["task_id"])
    assert available["revision"] == task["revision"]
    assert available["execution_scope"]["resources"][0]["root_id"] == "coordination"
    assert available["required_contract_ids"] == available["blocks"] == []
    assert available["owner_agent_id"] is None
    started = begin(call, available, worker)
    context = call("context.project_read", {}, worker)
    assert task["task_id"] not in {row["task_id"] for row in context["open_tasks"]}
    owned = next(row for row in context["tasks"] if row["task_id"] == task["task_id"])
    assert owned["revision"] == started["revision"] and owned["owner_agent_id"] == worker["agent_id"]
    assert begin(call, owned, worker)["attempt_id"] == started["attempt_id"]


def test_begin_conflict_is_atomic_and_submit_releases(runtime, monkeypatch):
    app, call, main, worker = runtime
    first, second = published(call, main, files=True), published(call, main, files=True)
    started = begin(call, first, worker)
    state = app.state.state_runtime
    reservation = state.resources.reservations[started["reservation_id"]]
    before = state.capture()
    event_before = events(app)
    with pytest.raises(HTTPException) as exc:
        begin(call, second, main)
    assert "resource_conflict" in str(exc.value.detail)
    assert exc.value.status_code == 409
    assert exc.value.detail["blockers"][0]["owner_agent_id"] == worker["agent_id"]
    # The refusal rolls the whole command back. The one durable trace it leaves is the
    # recorded denial itself: ``command.<kind>.denied`` is appended outside the command's
    # own transaction (api/app.py) precisely so a refusal survives its own rollback, and
    # the console's conflict ledger reads exactly those rows. Nothing else may move.
    assert state.capture() == before
    recorded = [event for event in events(app) if event not in event_before]
    assert [event["event_type"] for event in recorded] == ["command.task.begin.denied"]
    # No clock advancement invalidates the execution reservation.
    monkeypatch.setattr("tsunagou.modules.resources.now_ms", lambda: reservation.created_at + 365 * 24 * 3600 * 1000)
    root = state.project_registry.repository
    (root / "demo.txt").write_text("result", encoding="utf-8")
    result = call("task.submit", {"task_id": first["task_id"], "attempt_id": started["attempt_id"], "summary": "done"}, worker)
    assert result["workspace_result_ref"] is not None
    reservation = state.resources.reservations[started["reservation_id"]]
    assert reservation.status == "released" and reservation.released_at > reservation.created_at
    assert reservation.release_reason == "attempt_submitted"
    assert begin(call, second, main)["status"] == "running"


def test_scan_failure_rolls_back_and_duplicate_begin_does_not_rescan(runtime, monkeypatch):
    app, call, main, worker = runtime
    task = published(call, main, files=True)
    state = app.state.state_runtime
    before = state.capture()
    original = state.workspaces.scan_root

    def failed(*args, **kwargs):
        raise ValueError("fixture_scan_failed")

    monkeypatch.setattr(state.workspaces, "scan_root", failed)
    with pytest.raises(HTTPException) as exc:
        begin(call, task, worker)
    assert "fixture_scan_failed" in str(exc.value.detail)
    assert state.capture() == before
    monkeypatch.setattr(state.workspaces, "scan_root", original)
    command_id = new_id()
    started = begin(call, task, worker, command_id=command_id)
    monkeypatch.setattr(state.workspaces, "scan_root", failed)
    before = events(app)
    assert begin(call, task, worker, command_id=command_id) == started
    assert events(app) == before
    again = begin(call, started, worker)
    assert again["attempt_id"] == started["attempt_id"]
    assert len(state.tasks.attempts) == len(state.resources.reservations) == 1


def test_competing_workers_and_explicit_main_reclaim(runtime):
    app, call, main, worker = runtime
    task = published(call, main)

    def contender(actor):
        try:
            return begin(call, task, actor)
        except HTTPException:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(contender, [worker, main]))
    assert sum(value is not None for value in results) == 1
    winner = next(value for value in results if value is not None)
    old_actor = worker if winner["owner_agent_id"] == worker["agent_id"] else main
    reopened = call(
        "task.recover",
        {"task_id": task["task_id"], "expected_attempt_id": winner["attempt_id"], "disposition": "reopen", "reason": "reassign"},
        main,
    )
    replacement = begin(call, reopened, main if old_actor == worker else worker)
    assert replacement["attempt_id"] != winner["attempt_id"]
    with pytest.raises(HTTPException):
        call("task.submit", {"task_id": task["task_id"], "attempt_id": winner["attempt_id"], "summary": "late"}, old_actor)


def test_only_explicit_required_contracts_gate_begin(runtime):
    app, call, main, worker = runtime
    proposal = call(
        "contract.propose",
        {
            "payload": {},
            "participants_required": [
                {"slot": "implementation", "agent_id": worker["agent_id"]},
            ],
        },
        main,
    )
    task = published(call, main)
    assert begin(call, task, worker)["status"] == "running"
    required = published(call, main, required_contract_ids=[proposal["proposal_id"]])
    before = app.state.state_runtime.capture()
    with pytest.raises(HTTPException) as exc:
        begin(call, required, worker)
    assert "required_contract_not_accepted" in str(exc.value.detail)
    assert app.state.state_runtime.capture() == before
    call(
        "contract.accept",
        {"proposal_id": proposal["proposal_id"], "proposal_digest": proposal["digest"], "participant_slot": "implementation"},
        worker,
    )
    assert begin(call, required, worker)["status"] == "running"


def rebuilt_caller(app):
    registry = json.loads((Path(__file__).parents[2] / "protocol/registry/commands.json").read_text(encoding="utf-8"))

    def call(kind, payload, who=None, *, command_id=None):
        return _endpoint(app)(
            kind,
            CommandRequest(
                command_id=command_id or new_id(),
                protocol_version="1.0",
                schema_bundle_digest=registry["schema_bundle_digest"],
                payload=payload,
            ),
            Response(),
            "Bearer " + (who["secret_token"] if who else "control"),
            who["session_id"] if who else None,
            who["connection_epoch"] if who else None,
        )["result"]

    return call


def test_restart_preserves_ownership_and_original_begin_reissues_only_the_grant(runtime):
    app, call, main, worker = runtime
    task = published(call, main, files=True)
    started = begin(call, task, worker)
    old_grants = {
        g.grant_id
        for g in app.state.state_runtime.authority.grants.values()
        if g.attempt_id == started["attempt_id"] and g.status == "active"
    }
    aliases = dict(app.state.state_runtime.resources.root_aliases)
    app.state.project_database.release_process_lock()
    rebuilt = build_application()
    try:
        call = rebuilt_caller(rebuilt)
        state = rebuilt.state.state_runtime
        assert state.resources.root_aliases == aliases
        assert state.resources.reservations[started["reservation_id"]].status == "active"
        assert state.tasks.attempts[started["attempt_id"]].owner_agent_id == worker["agent_id"]
        assert all(state.authority.grants[key].status == "revoked" for key in old_grants)
        with pytest.raises(HTTPException) as exc:
            call("task.submit", {"task_id": task["task_id"], "attempt_id": started["attempt_id"], "summary": "before resume"}, worker)
        assert exc.value.status_code == 403
        with pytest.raises(HTTPException):
            begin(call, started, main)
        resumed = begin(call, started, worker)
        assert resumed == started
        assert len(state.tasks.attempts) == len(state.resources.reservations) == len(state.workspaces.baselines) == 1
        new_grants = {g.grant_id for g in state.authority.grants.values() if g.attempt_id == started["attempt_id"] and g.status == "active"}
        assert len(new_grants) == 1 and not (old_grants & new_grants)
        assert (
            call("task.submit", {"task_id": task["task_id"], "attempt_id": started["attempt_id"], "summary": "done"}, worker)["status"]
            == "submitted"
        )
    finally:
        rebuilt.state.project_database.release_process_lock()


@pytest.mark.parametrize("action", ["task.block", "task.fail", "task.cancel_ack", "task.recover"])
def test_every_explicit_exit_releases_resources_revokes_grants_and_replays_once(runtime, action):
    app, call, main, worker = runtime
    task = published(call, main, files=True)
    started = begin(call, task, worker)
    state = app.state.state_runtime
    if action == "task.cancel_ack":
        call("task.cancel_request", {"task_id": task["task_id"], "reason": "stop"}, main)
        assert state.resources.reservations[started["reservation_id"]].status == "active"
    payload = {"task_id": task["task_id"], "attempt_id": started["attempt_id"], "reason": "stop"}
    actor = worker
    if action == "task.recover":
        payload = {"task_id": task["task_id"], "expected_attempt_id": started["attempt_id"], "disposition": "reopen", "reason": "stop"}
        actor = main
    command_id = new_id()
    result = call(action, payload, actor, command_id=command_id)
    after = state.capture()
    event_after = events(app)
    assert call(action, payload, actor, command_id=command_id) == result
    assert state.capture() == after and events(app) == event_after
    reservation = state.resources.reservations[started["reservation_id"]]
    assert reservation.status == "released" and reservation.released_at is not None and reservation.release_reason
    assert not [g for g in state.authority.grants.values() if g.attempt_id == started["attempt_id"] and g.status == "active"]


def test_workspace_policy_reused_but_rework_gets_current_baseline(runtime):
    app, call, main, worker = runtime
    task = published(call, main, files=True)
    started = begin(call, task, worker)
    state = app.state.state_runtime
    before = next(iter(state.workspaces.baselines.values())).tracked_state_digest
    (state.project_registry.repository / "demo.txt").write_text("work in progress", encoding="utf-8")
    blocked = call("task.block", {"task_id": task["task_id"], "attempt_id": started["attempt_id"], "reason": "need context"}, worker)
    restarted = begin(call, blocked, worker)
    assert restarted["attempt_id"] != started["attempt_id"]
    assert len(state.workspaces.decisions) == 1 and len(state.workspaces.baselines) == 2
    workspace = state.workspaces.workspaces[restarted["workspace_id"]]
    assert state.workspaces.baselines[workspace.baseline_manifest_id].tracked_state_digest != before
    with pytest.raises(HTTPException):
        call("workspace.select", {"task_id": task["task_id"], "driver_kind": "shared"}, main)


def test_preparation_and_patch_materialization_run_outside_sqlite_transaction(runtime, monkeypatch):
    app, call, main, worker = runtime
    task = published(call, main, files=True)
    database = app.state.project_database
    state = app.state.state_runtime
    original = state.workspaces.scan_root
    scans = []

    def scan(*args, **kwargs):
        with contextlib.closing(database._connect()) as conn:
            conn.execute("PRAGMA busy_timeout=0")
            conn.execute("BEGIN IMMEDIATE")
            conn.rollback()
        scans.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(state.workspaces, "scan_root", scan)
    started = begin(call, task, worker)
    (state.project_registry.repository / "demo.txt").write_text("new patch", encoding="utf-8")
    from tsunagou.modules.artifacts import ArtifactService

    original_patch = ArtifactService.record_workspace_patch

    def materialize(self, *args, **kwargs):
        with contextlib.closing(database._connect()) as conn:
            conn.execute("PRAGMA busy_timeout=0")
            conn.execute("BEGIN IMMEDIATE")
            conn.rollback()
        return original_patch(self, *args, **kwargs)

    monkeypatch.setattr(ArtifactService, "record_workspace_patch", materialize)
    original_submit = state.tasks.submit
    before, before_events = state.capture(), events(app)

    def fail(*args, **kwargs):
        raise ValueError("fixture_late_submit_failure")

    monkeypatch.setattr(state.tasks, "submit", fail)
    with pytest.raises(HTTPException):
        call("task.submit", {"task_id": task["task_id"], "attempt_id": started["attempt_id"], "summary": "done"}, worker)
    assert state.capture() == before and events(app) == before_events
    monkeypatch.setattr(state.tasks, "submit", original_submit)
    result = call("task.submit", {"task_id": task["task_id"], "attempt_id": started["attempt_id"], "summary": "done"}, worker)
    assert result["workspace_result_ref"] and len(scans) == 3


def test_assignment_needs_no_ready_and_takeover_revokes_old_owner(runtime):
    app, call, main, worker = runtime
    # 计划里每条任务必须写清"什么算合格"。2026-10-05 那轮最贵的返工（管理员端交来错误业务域
    # 与 mock 实现）根因就是工单上根本没有这一栏 —— 验收只能事后靠人判断。
    with pytest.raises(HTTPException):
        call(
            "coordination.plan",
            {
                "objective": "one worker is sufficient",
                "assignments": [
                    {"title": "work", "task_objective": "finish", "assigned_worker_id": worker["agent_id"]},
                ],
            },
            main,
        )
    plan = call(
        "coordination.plan",
        {
            "objective": "one worker is sufficient",
            "assignments": [
                {"title": "work", "task_objective": "finish", "assigned_worker_id": worker["agent_id"],
                 "acceptance": "npm test 全绿，且重置后 12 项验收脚本逐条通过"},
            ],
        },
        main,
    )
    assignment = plan["assignments"][0]
    state = app.state.state_runtime
    assert assignment["message_id"]
    # 后端自己发的通知是给人读的：正文走中文模板（以前是 "Task available" 这种英文，
    # 控制台的「Agent 间协商」那张表原样印出来，人读不动）。
    notice = state.messages.messages[assignment["message_id"]].summary
    assert any("\u4e00" <= char <= "\u9fff" for char in notice), notice
    worker_context = call("context.project_read", {}, worker)
    main_context = call("context.project_read", {}, main)
    assert assignment["task_id"] in {row["task_id"] for row in worker_context["open_tasks"]}
    assert assignment["task_id"] not in {row["task_id"] for row in main_context["open_tasks"]}
    # 验收标准要跟着任务走到 Worker 手上，否则它只能猜"什么算做完"
    declared = next(row for row in worker_context["open_tasks"] if row["task_id"] == assignment["task_id"])
    assert declared["acceptance"] == "npm test 全绿，且重置后 12 项验收脚本逐条通过"

    def assignment_row(context, assignment_id):
        return next(item for item in context["coordination"]["assignments"]
                    if item["assignment_id"] == assignment_id)

    # 分配里直接带投递事实与当前 Attempt：主 Agent 不必为了"对方收到没有、开工没有"反复轮询
    # wake_status（2026-10-05 实测它就是这样反复查的），而 E017 那种"投递了但从未 begin"的形态
    # 当时只能靠人发现。
    row = assignment_row(worker_context, assignment["assignment_id"])
    assert set(row["delivery"]) >= {"delivered", "presented", "acked", "host_turn_started", "wake_recorded"}
    assert row["delivery"]["wake_recorded"] is False, "这条测试里还没派发过唤醒"
    assert row["attempt"] is None, "还没 begin，就不该有 Attempt"
    task = {"task_id": assignment["task_id"], "revision": state.tasks.tasks[assignment["task_id"]].revision}
    with pytest.raises(HTTPException) as exc:
        begin(call, task, main)
    assert exc.value.detail["code"] == "assignment_worker_mismatch"
    started = begin(call, task, worker)
    # 开工之后同一个视图里就能看到 Attempt —— "它已经在跑"这件事不需要额外轮询
    started_row = assignment_row(call("context.project_read", {}, worker), assignment["assignment_id"])
    assert started_row["attempt"] and started_row["attempt"]["attempt_id"] == started["attempt_id"]
    assert started_row["attempt"]["status"] in {"claimed", "running"}
    takeover = call(
        "coordination.takeover", {"assignment_id": assignment["assignment_id"], "takeover_reason": "worker requested help"}, main
    )
    # 接管必须**主动**告诉原 Worker 停手：它不会再收到任何"你还在干这活"的提示，于是会继续写
    # （2026-10-05 事件 R001：接管后原 Worker 继续写共享文件，主 Agent 的补丁验证因此失败，
    # 最后靠人工发停止消息才恢复）。
    notices = [message for message in state.messages.messages.values()
               if message.kind == "task.taken_over" and message.recipient_agent_id == worker["agent_id"]]
    assert notices, "接管后应当主动给原 Worker 发一条停止通知"
    assert notices[0].message_id in {item.message_id for item in state.messages.waiting(worker["agent_id"])}, \
        "这条通知要真的进对方的收件箱（否则它下一轮也看不到）"
    assert "接管" in notices[0].summary
    with pytest.raises(HTTPException) as turned_away:
        begin(call, takeover, worker)
    assert turned_away.value.detail["code"] == "assignment_worker_mismatch"
    # 被接管者要读到一句人话，而不是只有一个错误码
    assert "接管" in str(turned_away.value.detail.get("note", "")), turned_away.value.detail
    replacement = begin(call, takeover, main)
    assert replacement["attempt_id"] != started["attempt_id"]
    assert state.coordination.coverage({key: task.status for key, task in state.tasks.tasks.items()})["by_status"] == {"running": 1}


def test_user_wait_notifies_owner_without_releasing_running_work(runtime):
    app, call, main, worker = runtime
    task = published(call, main, files=True)
    started = begin(call, task, worker)
    state = app.state.state_runtime
    decision = call(
        "user_decision.propose",
        {"kind": "design.change", "proposal_ref": task["task_id"], "choices": ["approve", "reject"], "summary": "need direction"},
        main,
    )
    assert decision["status"] == "pending"
    assert state.tasks.tasks[task["task_id"]].status == "running"
    assert state.resources.reservations[started["reservation_id"]].status == "active"
    blocked = call("task.block", {"task_id": task["task_id"], "attempt_id": started["attempt_id"], "reason": "user decision"}, worker)
    with pytest.raises(HTTPException) as exc:
        begin(call, blocked, worker)
    assert "user_decision_pending" in str(exc.value.detail)
    independent = published(call, main)
    assert begin(call, independent, worker)["status"] == "running"

def test_superseding_a_task_links_the_replacement(runtime):
    """"换成新任务"要留下承接关系，而不是只把旧的取消掉。

    2026-10-05 的实际做法是"取消旧任务 + 新建替代任务"（事件 E012/E014）：旧任务在看板上永远算
    "没做完"，也没人能从记录里看出它是被谁替代的。
    """

    app, call, main, worker = runtime
    first = call("coordination.plan", {"objective": "first try", "assignments": [
        {"title": "old", "task_objective": "do it", "assigned_worker_id": worker["agent_id"],
         "acceptance": "旧任务：文件存在"},
    ]}, main)["assignments"][0]
    second = call("coordination.plan", {"objective": "second try", "assignments": [
        {"title": "new", "task_objective": "do it properly", "assigned_worker_id": worker["agent_id"],
         "acceptance": "新任务：npm test 全绿",
         "supersedes_task_id": first["task_id"]},
    ]}, main)["assignments"][0]

    state = app.state.state_runtime
    old = state.tasks.tasks[first["task_id"]]
    assert old.status == "cancelled", "被替代的旧任务应当退出领取队列"
    assert old.superseded_by == second["task_id"], "旧任务要记下是谁替代了它"
    assert state.tasks.tasks[second["task_id"]].superseded_by == "", "新任务自己不是被替代者"
    # 控制台的任务出口就是读 describe_task，所以这一条同时证明页面能看到承接关系
    assert state.tasks.describe_task(first["task_id"])["superseded_by"] == second["task_id"]

def test_context_read_can_be_asked_whether_anything_changed(runtime):
    """主 Agent 每轮都要读一遍上下文，而多数轮次其实没有任何新情况。

    快照本身带一个 token：把它原样交回来，没变化时只回一个结论，而不是再走一遍完整快照。
    不带这个参数的调用行为不变（只是多了一个 token 字段）。
    """

    app, call, main, worker = runtime
    first = call("context.project_read", {}, main)
    token = first["revision"]
    assert isinstance(token, str) and token.startswith("sha256:"), token

    same = call("context.project_read", {"since_revision": token}, main)
    # 命令结果外层还有 daemon 自己的信封字段（host_binding），所以不断言"只有两个键"，
    # 只断言真正要紧的事：没有重发快照。
    assert same["unchanged"] is True and same["revision"] == token
    assert "tasks" not in same and "contracts" not in same

    # 光建一条 draft 任务不会改变主 Agent 的快照：它没有 Attempt（不在 owned_tasks），
    # 也没发布（不在 open_tasks）。要让它出现，就得走完 ready + publish。
    fresh = call("task.create", {"title": "新情况", "objective": "变一下", "execution_scope": {}}, main)
    call("task.ready", {"task_id": fresh["task_id"]}, main)
    call("task.publish", {"task_id": fresh["task_id"]}, main)
    changed = call("context.project_read", {"since_revision": token}, main)
    assert changed["revision"] != token
    assert "tasks" in changed and "unchanged" not in changed

def test_declaring_a_cross_module_boundary_requires_a_contract(runtime):
    """声明了"跨模块交界"，就必须同时给出契约（用户 2026-10-06 的决定）。

    实测里最贵的语义冲突（读者端 /requests 对后端 /api/applications）**不重叠任何文件**，
    所以"只在文件重叠时强制契约"拦不住它。这里沿用刚验证有效的 acceptance 模式：由计划声明、
    机制强制，并且**在计划时就拒绝**，不等到集成阶段才发现。
    """

    app, call, main, worker = runtime
    with pytest.raises(HTTPException) as missing:
        call("coordination.plan", {"objective": "cross-module without a contract", "assignments": [
            {"title": "reader", "task_objective": "读接口", "assigned_worker_id": worker["agent_id"],
             "acceptance": "接口联调通过", "cross_module": True},
        ]}, main)
    assert missing.value.detail["code"] == "cross_module_contract_required", missing.value.detail

    planned = call("coordination.plan", {"objective": "cross-module declared", "assignments": [
        {"title": "reader", "task_objective": "读接口", "assigned_worker_id": worker["agent_id"],
         "acceptance": "接口联调通过", "cross_module": True, "required_contract_ids": ["contract-1"]},
    ]}, main)
    row = planned["assignments"][0]
    assert row["cross_module"] is True
    described = app.state.state_runtime.tasks.describe_task(row["task_id"])
    assert described["cross_module"] is True
    assert described["required_contract_ids"] == ["contract-1"]
