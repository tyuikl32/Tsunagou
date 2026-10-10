"""Fresh-state public command integration for explicit execution ownership."""

from __future__ import annotations

import contextlib
import json
import re
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
    second_plan = call("coordination.plan", {"objective": "second try", "assignments": [
        {"title": "new", "task_objective": "do it properly", "assigned_worker_id": worker["agent_id"],
         "acceptance": "新任务：npm test 全绿",
         "supersedes_task_id": first["task_id"]},
    ]}, main)
    second = second_plan["assignments"][0]

    state = app.state.state_runtime
    old = state.tasks.tasks[first["task_id"]]
    assert old.status == "cancelled", "被替代的旧任务应当退出领取队列"
    assert old.superseded_by == second["task_id"], "旧任务要记下是谁替代了它"
    assert state.tasks.tasks[second["task_id"]].superseded_by == "", "新任务自己不是被替代者"
    # 控制台的任务出口就是读 describe_task，所以这一条同时证明页面能看到承接关系
    assert state.tasks.describe_task(first["task_id"])["superseded_by"] == second["task_id"]
    # 调用方也要**在返回里**看到承接关系：不然它只能靠自己回忆"我替代了哪一条"
    # （2026-10-05 那次因此重复建了三批任务）。行的字段和计划级的 next 都要说到。
    assert second["superseded_task_id"] == first["task_id"]
    assert first["superseded_task_id"] is None
    assert first["task_id"] in second_plan["next"] and "替代" in second_plan["next"]

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

def test_publishing_says_it_notifies_nobody_and_keeps_the_scope_hint(runtime):
    """发布是**静默**的（2026-10-08 实测："已发布但没人开工"）。

    调用方以为 publish 等于派活；提示必须说清"要有人开工得靠 coordination.plan 或 message.send"。
    同时范围那条提示不能被顶掉 —— 两句话讲的是两件事。
    """

    app, call, main, worker = runtime
    silent = published(call, main)
    assert "不会通知任何人" in silent["next"]
    assert "coordination.plan" in silent["next"] and "task.assigned" in silent["next"]
    assert "message.send" in silent["next"]

    # 范围那条提示不能被顶掉：两句话讲的是两件事，合成一句话时都要在。（这里不建文件任务：
    # 那些用例要一个已登记的 `coordination` 根，属于既有夹具环境，与这句话无关。）
    created = call("task.create", {"title": "scope", "objective": "no paths", "execution_scope": {}}, main)
    scope_hint = created["next"]
    assert "不认领任何路径" in scope_hint
    call("task.ready", {"task_id": created["task_id"]}, main)
    combined = call("task.publish", {"task_id": created["task_id"]}, main)
    assert "不认领任何路径" in combined["next"], "范围提示必须留着"
    assert "不会通知任何人" in combined["next"], "发布提示也要在"


def test_a_refused_begin_names_the_task_and_main_can_see_it_keeps_failing(runtime):
    """被拒的命令不会改变状态，但必须**可归因**：事件里带 task_id，main 每回合看得见。

    2026-10-08 实测：4 次 ``command.task.begin.denied`` 里没有 task_id，也没有任何出口汇报
    "同一条任务被拒了四次" —— 于是它一直重试，最后只能整批取消重做。
    """

    app, call, main, worker = runtime
    task = published(call, main, required_contract_ids=["library-api-v1"])
    before = events(app)
    for _ in range(2):
        with pytest.raises(HTTPException) as refused:
            begin(call, task, worker)
    assert refused.value.detail["code"] == "required_contract_not_accepted:library-api-v1"

    recorded = [event for event in events(app) if event not in before]
    denials = [event for event in recorded if event["event_type"] == "command.task.begin.denied"]
    assert len(denials) == 2, "两次被拒就是两条拒绝事件"
    for event in denials:
        payload = json.loads(event["payload_json"])
        assert payload["task_id"] == task["task_id"], "拒绝要归到具体的任务上"
        assert payload["command_kind"] == "task.begin"
        assert payload["code"] == "required_contract_not_accepted:library-api-v1"

    # 待改 18-③：第二次撞同一堵墙不再只是"又一条事件"—— 任务被标出、main 收到一条消息，
    # 并且这次回响本身也留痕（运行层事件，没有对应的命令）。
    repeats = [event for event in recorded if event["event_type"] == "coordination.refusal_repeat"]
    assert len(repeats) == 1, "越过阈值的那一次要有一条回响事件"
    escalation = json.loads(denials[1]["payload_json"])["escalation"]
    assert escalation["refusal_count"] == 2
    assert escalation["task_marked"] is True
    assert escalation["notified_agent_id"] == main["agent_id"]

    main_view = call("context.project_read", {}, main)
    (row,) = main_view["coordination"]["denied"]
    assert row["task_id"] == task["task_id"]
    assert row["count"] == 2 and "required_contract_not_accepted:library-api-v1" == row["code"]
    assert row["last_at"]
    assert task["task_id"] in main_view["next"], "反复被拒要给一句提示"
    (open_task,) = [item for item in main_view["open_tasks"] if item["task_id"] == task["task_id"]]
    assert open_task["block_reason"] == "refused:required_contract_not_accepted:library-api-v1", (
        "任务本身要带着'开不了工'的可见理由（状态不变，理由可见）"
    )
    inbox = call("inbox.claim", {"limit": 20}, main)
    (refusal,) = [item for item in inbox["messages"] if item["kind"] == "task.refused"]
    assert refusal["subject_ref"] == f"task/{task['task_id']}"
    assert refusal["sender_agent_id"] == "runtime"

    worker_view = call("context.project_read", {}, worker)
    assert "denied" not in worker_view["coordination"], "别人的卡点不该出现在 worker 的上下文里"
    assert "next" not in worker_view


def test_a_permission_refusal_is_recorded_and_never_marks_the_task(runtime):
    """待改 18：拒绝都要留痕；但"调用方没能力"不是"这条任务开不了工"。

    2026-10-08 实测的那一条是 ``task__progress`` 被 ``capability_denied`` 拒（没 begin 就想
    progress）：事件库里**一条都没有** —— 审计只记带 detail 的 ValueError 形状的拒绝。
    这样的拒绝要进审计与 main 的拒绝清单，但不该给任务盖章：任务可能好好的，只是叫错了人。
    """

    app, call, main, worker = runtime
    task = published(call, main)
    before = events(app)
    for _ in range(2):
        with pytest.raises(HTTPException) as refused:
            call("task.progress", {"task_id": task["task_id"], "attempt_id": "not-an-attempt", "summary": "x"}, worker)
    assert refused.value.detail["code"] == "capability_denied"

    recorded = [event for event in events(app) if event not in before]
    denials = [json.loads(event["payload_json"]) for event in recorded
               if event["event_type"] == "command.task.progress.denied"]
    assert [item["code"] for item in denials] == ["capability_denied"] * 2, "权限拒绝也要留痕"
    assert denials[0]["task_id"] == task["task_id"], "调用方点了任务，就归到这个任务上"
    assert not [event for event in recorded if event["event_type"] == "coordination.refusal_repeat"], (
        "调用方少能力不该触发'任务开不了工'的回响"
    )
    view = call("context.project_read", {}, main)
    (open_task,) = [item for item in view["open_tasks"] if item["task_id"] == task["task_id"]]
    assert open_task["block_reason"] is None


def test_planning_validates_the_scope_the_create_path_would_refuse(runtime):
    """计划期跑**同一套**范围校验（待改 22-①③）：悬空根引用当场拒，并列出可用的 root_id。

    没有这一步时，`unknown_root_id` 只在 `task.begin` 暴露 —— 那时任务已经建好、派出去、
    有人认领了，等于让人白跑一趟（2026-10-08 观察到的那些 `unknown_root_id` 全在 begin 期）。
    """

    app, call, main, worker = runtime
    scope = {"resources": [{"kind": "path", "root_id": "coordination",
                            "segments": ["a.py"], "mode": "exclusive_write"}]}
    with pytest.raises(HTTPException) as refusal:
        call("coordination.plan", {"objective": "file work", "assignments": [
            {"title": "server", "task_objective": "写服务", "assigned_worker_id": worker["agent_id"],
             "acceptance": "接口联调通过", "execution_scope": scope},
        ]}, main)
    assert refusal.value.status_code == 409
    assert refusal.value.detail["code"] == "unknown_root_id:coordination"
    assert refusal.value.detail["registered_root_ids"] == []
    assert "root.register" in refusal.value.detail["next"]
    assert app.state.state_runtime.tasks.tasks == {}, "整条计划不许留下一半任务"


def test_a_plan_says_which_rows_cannot_start_yet_because_of_contracts(runtime):
    """契约没结清要在**计划那一刻**说出来（待改 22-①③）。

    2026-10-08 实测：main 把契约**名字**填进 `required_contract_ids`，计划照常成功，到 begin
    连拒 4 次、最后三个任务被取消重建。这里不拒绝（先计划、再让槽位接受是设计内的顺序），
    但要说清"这两条现在还领不了活"以及本项目现有的契约 id。
    """

    app, call, main, worker = runtime
    planned = call("coordination.plan", {"objective": "contract work", "assignments": [
        {"title": "server", "task_objective": "写服务", "assigned_worker_id": worker["agent_id"],
         "acceptance": "接口联调通过", "required_contract_ids": ["library-api-v1"]},
    ]}, main)
    (row,) = planned["assignments"]
    assert row["contracts_pending"] == ["library-api-v1"]
    assert "library-api-v1" in planned["next"] and "required_contract_not_accepted" in planned["next"]
    assert "一个都没有" in planned["next"], "现有契约 id 的清单（这里是空的）也要给出来"


def test_the_submit_notification_carries_what_review_already_requires(runtime):
    """`inbox.fetch` 回来的那条本身就能喂给 `task.review.accept`（待改 22-⑥ / F）。

    验收边界拿 `result_digest` 与存下来的结果比对，而"有个结果待验收"这件事**只由通知带来**：
    通知里只给 `result_id` 的话，main 看得见义务、却无法直接履行 —— 它得再问一次 results 出口，
    或者干脆猜一个 digest 然后吃 `result_digest_mismatch`。所以三者必须同行。
    """

    app, call, main, worker = runtime
    task = published(call, main)
    started = begin(call, task, worker)
    submitted = call("task.submit", {
        "task_id": task["task_id"], "attempt_id": started["attempt_id"], "summary": "done",
    }, worker)

    inbox = call("inbox.claim", {"limit": 20}, main)
    (notice,) = [item for item in inbox["messages"] if item["kind"] == "task.submitted"]
    fetched = call("inbox.fetch", {"message_id": notice["message_id"]}, main)
    payload = fetched["payload"]
    assert payload["task_id"] == task["task_id"]
    assert payload["result_id"] == submitted["result_id"]
    assert payload["result_digest"] == submitted["digest"]
    # 通知还带一份**证据摘要**（2026-10-10：只给三个 id 时，验收方只能自己重建证据 —— 那次
    # main 为此写了 5 个探针）。这条任务不碰文件，所以摘要如实说"没有工作区证据"。
    assert payload["evidence"]["present"] is False
    assert payload["evidence"]["reason"] == "no_workspace_result"

    # 照抄通知里那三个值就能验收：不需要别的出口，也不需要猜。**三个值显式取**，不要把整条
    # payload 展开 —— 摘要不是 review 的字段（review 的 schema 只收它自己那几个）。
    reviewed = call("task.review.accept", {
        "task_id": payload["task_id"], "result_id": payload["result_id"],
        "result_digest": payload["result_digest"], "reason": "looks right",
    }, main)
    assert reviewed["status"] == "completed"


def test_a_file_task_submission_carries_replayable_evidence(runtime):
    """碰文件的任务：通知里就有可重放的证据，验收方不必自己重建。

    2026-10-10 实测：main 为了判 8 个任务写了 5 个专用探针（books 22 项 / loans 41 项 / insights
    26 项 / persistence 16 项）。清单里本来就有这些事实，缺的是"随结果一起到达"和"能单独取全文"
    （``task.result.get``）。这条钉住前者：命令、退出码、改动数、环境指纹都在通知里。
    """

    app, call, main, worker = runtime
    # 碰文件的任务要先有一个已登记的根，而且 scope 里必须用它**真实**的 root_id
    # （这 11 条既有失败的成因就是夹具里写死了 "coordination"）。
    fixture = app.state.state_runtime.project_registry.repository
    call("root.register", {"name": "coordination", "kind": "directory", "required": False,
                           "binding_request": {"absolute_path": str(fixture)}}, main)
    (root_id,) = list(app.state.project_registry.project.roots)
    created = call("task.create", {
        "title": "evidence", "objective": "写一个文件",
        "execution_scope": {"resources": [{"kind": "path", "root_id": root_id,
                                           "segments": ["demo.txt"], "mode": "exclusive_write"}]},
    }, main)
    call("workspace.select", {"task_id": created["task_id"], "driver_kind": "shared"}, main)
    call("task.ready", {"task_id": created["task_id"]}, main)
    task = call("task.publish", {"task_id": created["task_id"]}, main)
    started = begin(call, task, worker)
    repo_file = app.state.project_registry.repository / "demo.txt"
    repo_file.write_text("hello\n", encoding="utf-8")
    call("task.submit", {
        "task_id": task["task_id"], "attempt_id": started["attempt_id"], "summary": "done",
        "validation_metadata": [{"command": "python -m pytest -q", "exit_code": 0}],
    }, worker)

    inbox = call("inbox.claim", {"limit": 20}, main)
    (notice,) = [item for item in inbox["messages"] if item["kind"] == "task.submitted"]
    evidence = call("inbox.fetch", {"message_id": notice["message_id"]}, main)["payload"]["evidence"]
    assert evidence["present"] is True and evidence["manifest_id"]
    assert evidence["receipts"] == 1
    assert evidence["commands"] == [{"command": "python -m pytest -q", "exit_code": 0}]
    assert evidence["changed_paths"] >= 1
    assert evidence["environment_digest"], "环境指纹要随结果一起给出"
    assert evidence["scope_violations"] == []


def test_a_plan_reports_its_own_shape_and_says_when_it_looks_heavy(runtime):
    """计划的"形状"是机械计数，重的时候给一句建议（待改 22-⑦）。

    2026-10-08 的复盘结论是**机制成本 ∝ 需要显式化的接口决策数**：任务多、人少时每条都要各自的
    scope/验收/交接；租约分区多往往意味着工作被切成了目录。这两句只在数字大时说，而且说清它只是计数。
    """

    app, call, main, worker = runtime
    rows = [
        {"title": f"task-{index}", "task_objective": "写一段",
         "assigned_worker_id": worker["agent_id"], "acceptance": "跑得起来",
         "execution_scope": {"resources": [{"kind": "path", "root_id": "coordination",
                                            "segments": [f"area-{index}", "app.py"],
                                            "mode": "exclusive_write"}]}}
        for index in range(5)
    ]
    # 这五条都要一个已登记的根：先登记一个（用 scope 里的那个 id 名）。
    fixture = app.state.state_runtime.project_registry.repository
    call("root.register", {"name": "workspace", "kind": "directory", "required": False,
                           "binding_request": {"absolute_path": str(fixture)}}, main)
    # 登记生成的 root_id 才是 scope 里该用的值；这里直接改写 scope 用真实 id。
    (root_id,) = list(app.state.project_registry.project.roots)
    for row in rows:
        row["execution_scope"]["resources"][0]["root_id"] = root_id

    planned = call("coordination.plan", {"objective": "five slices", "assignments": rows}, main)
    shape = planned["shape"]
    assert shape["tasks"] == 5 and shape["workers"] == 1
    assert shape["lease_partitions"] == 5, "五个互不重叠的分区"
    assert shape["dependency_edges"] == 0 and shape["contracts"] == 0
    assert "5 条任务交给 1 个人" in planned["next"], "任务多、人少时要说一句"
    assert "租约分区" in planned["next"], "分区多时也要说一句"


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


def _strings(value):
    """Every string inside a snapshot value, however deeply nested."""

    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [item for child in value.values() for item in _strings(child)]
    if isinstance(value, (list, tuple)):
        return [item for child in value for item in _strings(child)]
    return []


def _bridge_tools() -> dict[str, str]:
    """``tool_name → command_kind`` as the bridge itself declares them.

    The read (backend) and the visible tool list (bridge) are two languages for one surface;
    a capability index that names a tool the bridge does not expose sends a session looking
    for something that does not exist. Read the bridge's own array — never a copy of it.
    """

    source = (
        Path(__file__).parents[2] / "packages" / "bridge-server" / "src" / "server.ts"
    ).read_text(encoding="utf-8")
    return {
        match.group("name"): match.group("kind")
        for match in re.finditer(
            r'name:\s*"(?P<name>[A-Za-z0-9_]+)"\s*,\s*command_kind:\s*"(?P<kind>[A-Za-z0-9_.]+)"',
            source,
        )
    }


def test_the_capability_index_names_tools_the_way_the_bridge_does(runtime):
    """索引里的工具名必须是桥真正暴露的那些名字（``task__edge_add`` 这类拼法漂移过一次）。

    ``task.edge.add`` 机械替换会得到 ``task__edge__add``，而桥的工具叫 ``task__edge_add``；
    ``project.completion.propose.main`` 同理。索引是"这个面长什么样"的唯一一处说明，名字错了
    比没有更糟 —— 所以这里拿桥自己的工具表逐条核对，另加一条"每个名字都是真的工具"。
    """

    _app, call, main, _worker = runtime
    bridge = _bridge_tools()
    assert bridge, "桥的工具表读不到：这条核对就失去意义了，必须失败"
    assert bridge["task__edge_add"] == "task.edge.add"

    lines = call("context.project_read", {}, main)["capability_index"]
    assert "\n".join(lines).isascii(), "索引要能安全穿过桥的 stdout"
    listed: list[str] = []
    for line in lines[1:]:
        area, tools, _purpose = line.split(" | ")
        assert area and _purpose
        listed.extend(part.strip() for part in tools.split(","))
    assert listed, "索引不能是空表"

    invented = sorted({name for name in listed if name not in bridge})
    assert not invented, f"索引里写了桥不存在的工具：{invented}"
    assert "task__edge_add" in listed and "task__create" in listed
    assert "project__completion_propose" in listed
    assert "project__completion__propose__main" not in listed
    assert "project__completion_confirm" not in listed, "用户确认没有 Agent 侧工具，不在这里假称有"
    assert "decision__propose" in listed, "user_decision.propose 在桥上的名字是 decision__propose"


def test_the_read_states_roots_identities_and_accepted_contracts_instead_of_making_main_guess(runtime):
    """主 Agent 不该为了这些值去读源码或先被拒一次。

    2026-10-08 两次实测：第一次 ``coordination.plan`` 之前花了 3.3 / 3.8 分钟，其中大半是猜平台
    自己知道的值 —— ``root.bind`` 失败后去读 ``modules/projects.py`` 才弄明白
    ``expected_physical_identity`` 该填什么，去读 ``coordination.plan`` 的 schema 才知道行里必填
    哪几个字段，契约 id 的形状则是被拒一次才知道。这些事实一次读取就能说清。
    """

    app, call, main, worker = runtime
    fixture = app.state.state_runtime.project_registry.repository

    # 一个已登记的根：``stable.roots`` 要给出 root_id 与那个不透明的 physical_identity。
    registered = call("root.register", {
        "name": "workspace", "kind": "directory", "required": False,
        "binding_request": {"absolute_path": str(fixture)},
    }, main)
    assert registered["status"] == "bound"
    repository = call("repository.register", {
        "name": "backend", "root_id": registered["root_id"], "required": False,
    }, main)

    # 一条**已接受**的契约：``required_contract_ids`` 只能填这种 id。
    task = call("task.create", {"title": "api", "objective": "settle the interface",
                               "execution_scope": {}}, main)
    proposal = call("contract.propose", {
        "contract_id": "api-surface", "contract_kind": "interface",
        "payload": {"task_id": task["task_id"], "subject_ref": "后端接口 v1"},
        "participants_required": [{"slot": "self", "agent_id": main["agent_id"]}],
        "participants_optional": [], "subject_ref": "后端接口 v1", "input_refs": [], "supersedes_id": "",
    }, main)
    call("contract.accept", {
        "proposal_id": proposal["proposal_id"], "participant_slot": "self",
        "proposal_digest": proposal["digest"], "evidence_refs": [],
    }, main)

    view = call("context.project_read", {}, main)
    stable = view["stable"]

    (root_row,) = stable["roots"]["items"]
    assert root_row["root_id"] == registered["root_id"]
    assert root_row["name"] == "workspace" and root_row["kind"] == "directory"
    assert root_row["status"] == "bound"
    assert root_row["physical_identity"] == registered["physical_identity"], "要能原样回填 expected_physical_identity"
    assert str(root_row["physical_identity"]).startswith("inode:"), root_row["physical_identity"]
    assert stable["roots"]["total"] == 1

    (repository_row,) = stable["repositories"]["items"]
    assert repository_row["repository_id"] == repository["repository_id"]
    assert repository_row["name"] == "backend" and repository_row["root_id"] == registered["root_id"]
    assert stable["repositories"]["exists"] is True and stable["repositories"]["total"] == 1
    assert stable["repositories"]["next"] is None, "已经有仓库了就别再劝它 register"

    (contract_row,) = stable["contracts"]["accepted"]
    assert contract_row["proposal_id"] == "api-surface" == proposal["proposal_id"]
    assert contract_row["status"] == "accepted"
    assert contract_row["subject_ref"] == "后端接口 v1", "契约的语义名要读得到（它在 payload 里）"

    # 边界：没有绝对路径、没有 token。身份是不透明串，路径不是身份 —— 所以这里按**值**核，
    # 不是按字段名核。
    strings = _strings(view)
    assert "secret_token" not in strings
    assert str(fixture) not in strings, "本机绝对路径一个都不进快照"
    assert not [item for item in strings if item.startswith(("E:\\", "C:\\", "/"))]

    # 快照现在**可以**带中文（2026-10-10 待改 21 之后）：跨进程 JSON 管道两端都显式 UTF-8，
    # 所以调用方给的原样值（``subject_ref``、根名、用户确认的目标）不必再被剥掉。
    # 原来这里有一条"机器面的文本必须 ASCII"的守卫，它是那次编码事故的产物：桥写的 UTF-8
    # 被父进程按 GBK 读，reader 线程直接炸、`stdout` 变 None。修好之后，中文留在这里就是
    # 回归证据 —— 它要穿过 `subprocess`（见 tests/integration/test_cross_process_utf8.py 与
    # test_remote_machine_end_to_end）原样到达调用方。
    assert stable["contracts"]["accepted"][0]["subject_ref"] == "后端接口 v1"
    assert json.loads(json.dumps(stable, ensure_ascii=False))["contracts"]["accepted"][0]["subject_ref"] == "后端接口 v1"

    # worker 读同一份快照：这些事实它也拿得到（它要按 root_id 填 scope），
    # 但 main 专属的东西不长出来。
    worker_view = call("context.project_read", {}, worker)
    assert worker_view["stable"]["roots"]["items"][0]["root_id"] == registered["root_id"]
    assert worker_view["stable"]["contracts"]["accepted"][0]["proposal_id"] == "api-surface"
    assert "denied" not in worker_view["coordination"]
    assert "next" not in worker_view


def test_the_read_states_whether_the_goal_is_confirmed(runtime):
    """目标是不是"已确认"要**说出来**，不能靠主 Agent 从占位句里猜。

    占位句（``PENDING_OBJECTIVE``）不是目标；确认走一条 ``kind=project.objective`` 的普通用户
    决定。两种状态都给一句 ``note`` + 机械的 ``confirmed``，免得它把占位句当目标复述，或者以为
    "项目没有目标"。
    """

    app, call, main, worker = runtime
    unset = call("context.project_read", {}, main)["stable"]["goal"]
    assert unset["confirmed"] is False and unset["objective_ref"] is None
    assert unset["status"] == "unset" and unset["note"]
    # 同一份快照里最长的那段提示也照旧读得到（ASCII 限制已随待改 21 一起取消，见上一条用例）。

    asked = "让两个 Agent 对齐接口并交付可运行实现"
    proposed = call("user_decision.propose", {
        "kind": "project.objective", "proposal_ref": "project/objective/v1",
        "choices": ["确认", "要改"], "summary": asked,
    }, main)
    pending = call("context.project_read", {}, main)["stable"]["goal"]
    assert pending["confirmed"] is False and pending["status"] == "pending"
    assert pending["decision_id"] == proposed["decision_id"]
    assert pending["objective_ref"] == "project/objective/v1"

    call("user_decision.resolve", {
        "decision_id": proposed["decision_id"], "choice": "确认",
        "expected_revisions": {"decision": proposed["revision"]},
        "proposal_digest": proposed["proposal_digest"], "reason": "用户确认目标",
    }, token="control")

    confirmed = call("context.project_read", {}, main)["stable"]["goal"]
    assert confirmed["confirmed"] is True and confirmed["status"] == "resolved"
    assert confirmed["objective_ref"] == "project/objective/v1"
    assert confirmed["objective"] == asked
    # 目标确认是一条用户决定 —— worker 也看得到"目标定了"（对齐目标不是秘密），
    # 但确认这件事只有用户能做（那条命令不在 worker 的工具面里）。
    assert call("context.project_read", {}, worker)["stable"]["goal"]["confirmed"] is True


def test_the_stable_block_is_part_of_the_revision_so_a_differential_read_is_cheap(runtime):
    """稳定块进 revision 摘要：没有变化时差量读只回一句 ``unchanged``。

    这份快照每轮都被读一次，所以"平台本来就知道的值"不能每轮重发。放进摘要（``stable`` 在
    ``snapshot`` 里，摘要算的是整份快照）就等于：没变化 = 不重发；真有变化 = 整份重发，
    不会出现"变了却不给"。这条同时证明后面那半句。
    """

    app, call, main, worker = runtime
    first = call("context.project_read", {}, main)
    token = first["revision"]
    stable_before = first["stable"]
    assert stable_before["roots"]["total"] == 0 and stable_before["repositories"]["exists"] is False

    # 没有变化：只回结论，稳定块与能力索引都不重发。
    unchanged = call("context.project_read", {"since_revision": token}, main)
    assert unchanged["unchanged"] is True and unchanged["revision"] == token
    assert "stable" not in unchanged and "capability_index" not in unchanged

    # 有一条新任务进了领取队列：整份快照（含稳定块）重发 —— 不会因为"它在稳定区"就被吞掉。
    task = published(call, main)
    changed = call("context.project_read", {"since_revision": token}, main)
    assert changed["revision"] != token and "unchanged" not in changed
    assert changed["stable"] == stable_before, "发布一条任务不改变稳定块里的任何事实"
    assert any(row["task_id"] == task["task_id"] for row in changed["open_tasks"])
    # 索引只在第一次读给；这一次是差量读，所以不给。
    assert "capability_index" not in changed

    # 稳定块里的东西**真的会**改动摘要：登记一个根之后，之前那个 token 就过期了。
    call("root.register", {
        "name": "workspace", "kind": "directory", "required": False,
        "binding_request": {"absolute_path": str(app.state.state_runtime.project_registry.repository)},
    }, main)
    refreshed = call("context.project_read", {"since_revision": changed["revision"]}, main)
    assert refreshed["revision"] != changed["revision"] and "unchanged" not in refreshed
    assert refreshed["stable"]["roots"]["total"] == 1

