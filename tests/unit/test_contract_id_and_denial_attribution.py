"""三件在 2026-10-08 真机实测里付过代价的事，各自钉住。

1. **`contract.propose` 的 `contract_id` 是真的**：给了它，它就是这个提案的 `proposal_id`，
   任务就能用它填 `required_contract_ids`（那 4 次 `required_contract_not_accepted` 的根因是
   调用方按自己起的标签引用、系统按 UUID 查）；重名拒绝，省略则系统发 UUID。
2. **被拒时要说清本项目有哪些契约**：只回"请核对"时调用方手上没有清单可比。
3. **拒绝是可归因、且主 Agent 看得见的**：`task.begin` 的拒绝带上 `task_id`，
   主 Agent 每回合的 `context.project_read` 回一份按任务聚合的拒绝清单 —— worker 看不到。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException, Response

from tsunagou.api.app import CommandRequest, create_app
from tsunagou.api.auth import LocalCommandAuthenticator
from tsunagou.application.handlers import DENIAL_EVENT_WINDOW, DENIAL_ROW_LIMIT, build_handlers
from tsunagou.interfaces.runtime import CommandDispatcher
from tsunagou.modules.authority import AuthorityService
from tsunagou.modules.cognition import CognitionService
from tsunagou.modules.messaging import MessageStore
from tsunagou.modules.tasks import TaskService
from tsunagou.shared_kernel.baseline import ADMISSION_CAPABILITIES

ROOT = Path(__file__).parents[2]
COMMANDS = ROOT / "protocol" / "registry" / "commands.json"


class _FakeEventStore:
    """只实现 ``context.project_read`` 用到的那一个读口：一次定长查询。"""

    def __init__(self, events: list[dict[str, Any]]) -> None:
        self.events = events
        self.calls: list[dict[str, Any]] = []

    def list_events(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(kwargs)
        return list(self.events)


def _denial(task_id: str | None, code: str, *, at: int = 1_700_000_000_000, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"command_kind": "task.begin", "code": code, **extra}
    if task_id is not None:
        payload["task_id"] = task_id
    return {"event_type": "command.task.begin.denied", "payload": payload,
            "occurred_at": at, "recorded_at": at, "reason_code": None}


def _baseline() -> dict[str, Any]:
    return {"baseline": {
        name: {"status": "supported", "evidence_refs": [f"fixture:{name}"]}
        for name in ADMISSION_CAPABILITIES
    }}


class _Runtime:
    def __init__(self, tmp_path: Path, *, database: Any = None) -> None:
        dispatcher = CommandDispatcher(COMMANDS)
        self.authority = AuthorityService(tmp_path / "identity.json")
        self.tasks = TaskService()
        self.cognition = CognitionService()
        self.database = database
        preparers: dict[str, Any] = {}
        for kind, handler in build_handlers(
            authority=self.authority, tasks=self.tasks, cognition=self.cognition,
            messages=MessageStore(), database=database, preparers=preparers,
        ).items():
            dispatcher.register(kind, handler)
        for kind, prepare in preparers.items():
            dispatcher.register_preparer(kind, prepare)
        app = create_app(dispatcher, authenticator=LocalCommandAuthenticator(
            authority=self.authority, control_token="control"))
        self.endpoint = next(
            route.endpoint for route in app.routes
            if getattr(route, "path", "") == "/api/v1/commands/{command_kind}"
        )
        self._counter = 0

    def enroll(self, name: str) -> Any:
        ticket = self.authority.issue_ticket(name, name)
        return self.authority.redeem_ticket(ticket, name, name, baseline=_baseline())

    def call(self, kind: str, payload: dict[str, Any], who: Any = None) -> dict[str, Any]:
        self._counter += 1
        return self.endpoint(
            kind,
            CommandRequest(command_id=f"c{self._counter}", protocol_version="1",
                           schema_bundle_digest="sha256:x", payload=payload),
            Response(),
            "Bearer " + (who.secret_token if who is not None else "control"),
            who.session_id if who is not None else None,
            who.connection_epoch if who is not None else None,
        )["result"]


@pytest.fixture(name="runtime")
def _runtime(tmp_path: Path) -> _Runtime:
    runtime = _Runtime(tmp_path)
    runtime.main = runtime.enroll("main")
    runtime.worker = runtime.enroll("worker")
    runtime.call("authority.appoint", {"agent_id": runtime.main.agent_id})
    return runtime


def _propose(runtime: _Runtime, who: Any, **extra: Any) -> dict[str, Any]:
    return runtime.call("contract.propose", {
        "contract_kind": "interface", "payload": {"x": 1},
        "participants_required": [{"slot": "self", "agent_id": who.agent_id}],
        "participants_optional": [], "subject_ref": "s", "input_refs": [],
        **extra,
    }, who)


def _published(runtime: _Runtime, *, required_contract_ids: list[str]) -> dict[str, Any]:
    task = runtime.call("task.create", {
        "title": "write", "objective": "produce output", "execution_scope": {},
        "required_contract_ids": required_contract_ids,
    }, runtime.main)
    runtime.call("task.ready", {"task_id": task["task_id"]}, runtime.main)
    return runtime.call("task.publish", {"task_id": task["task_id"]}, runtime.main)


def _begin(runtime: _Runtime, task: dict[str, Any], who: Any) -> dict[str, Any]:
    return runtime.call("task.begin", {
        "task_id": task["task_id"], "expected_task_revision": task["revision"],
    }, who)


# --- A. contract_id 是真的 ---------------------------------------------------------------


def test_a_caller_supplied_contract_id_becomes_the_proposal_id_and_gates_begin(
    runtime: _Runtime,
) -> None:
    """调用方起的 id 就是提案 id —— 于是任务填它就能开工（这正是实测里断掉的那一环）。"""

    proposed = _propose(runtime, runtime.main, contract_id="library-api-v1")

    assert proposed["proposal_id"] == "library-api-v1"
    assert proposed["contract_id"] == "library-api-v1", "返回值要回显调用方能用哪个 id"
    assert "library-api-v1" in runtime.cognition.proposals

    task = _published(runtime, required_contract_ids=["library-api-v1"])
    with pytest.raises(HTTPException) as refused:
        _begin(runtime, task, runtime.main)
    assert refused.value.detail["code"] == "required_contract_not_accepted:library-api-v1"

    runtime.call("contract.accept", {
        "proposal_id": "library-api-v1", "participant_slot": "self",
        "proposal_digest": proposed["digest"],
    }, runtime.main)
    assert _begin(runtime, task, runtime.main)["status"] == "running"


def test_a_taken_contract_id_is_refused_instead_of_silently_replaced(runtime: _Runtime) -> None:
    first = _propose(runtime, runtime.main, contract_id="library-api-v1")

    with pytest.raises(HTTPException) as refused:
        _propose(runtime, runtime.main, contract_id="library-api-v1")

    assert refused.value.detail["code"] == "contract_id_taken"
    # 第一次那份没被顶掉：调用方引用过的 id 必须还指向原来那一份。
    assert runtime.cognition.proposals["library-api-v1"].digest == first["digest"]
    assert len(runtime.cognition.proposals) == 1


@pytest.mark.parametrize("bad", ["  ", "has\nnewline", "trailing ", "x" * 129])
def test_an_unusable_contract_id_is_refused(runtime: _Runtime, bad: str) -> None:
    with pytest.raises(HTTPException) as refused:
        _propose(runtime, runtime.main, contract_id=bad)
    assert refused.value.detail["code"] in {"invalid_contract_id", "contract_id_too_long"}


def test_an_empty_contract_id_means_the_same_as_omitting_it(runtime: _Runtime) -> None:
    """线上约定：空串就是"没有"（与 ``supersedes_id`` 同一个约定），不是格式错误。"""

    proposed = _propose(runtime, runtime.main, contract_id="")

    assert proposed["proposal_id"] == proposed["contract_id"]
    assert len(proposed["proposal_id"]) == 36


def test_without_a_contract_id_the_daemon_still_mints_a_uuid(runtime: _Runtime) -> None:
    proposed = _propose(runtime, runtime.main)

    assert proposed["proposal_id"] == proposed["contract_id"]
    assert len(proposed["proposal_id"]) == 36, "省略 contract_id 时行为不变：系统发 UUID"
    assert proposed["proposal_id"] in runtime.cognition.proposals


def test_a_revision_cannot_reuse_the_id_of_the_proposal_it_replaces(runtime: _Runtime) -> None:
    """两份提案都留在库里、还互相引用时，任务该引用哪一个谁也说不清 —— 拒绝并说清做法。"""

    first = _propose(runtime, runtime.main, contract_id="library-api-v1")

    with pytest.raises(HTTPException) as refused:
        _propose(runtime, runtime.main, contract_id="library-api-v1",
                 supersedes_id=first["proposal_id"])
    assert refused.value.detail["code"] == "contract_id_taken_by_superseded_contract"

    revision = _propose(runtime, runtime.main, supersedes_id=first["proposal_id"])
    assert revision["supersedes_id"] == first["proposal_id"]
    assert revision["proposal_id"] != first["proposal_id"]


# --- B. 拒绝里列出本项目已有的契约 ---------------------------------------------------------


def test_a_missing_contract_refusal_lists_the_contract_ids_that_do_exist(runtime: _Runtime) -> None:
    _propose(runtime, runtime.main, contract_id="library-api-v1")
    task = _published(runtime, required_contract_ids=["library-api-v1-typo"])

    with pytest.raises(HTTPException) as refused:
        _begin(runtime, task, runtime.main)

    detail = refused.value.detail
    assert detail["code"] == "required_contract_not_accepted:library-api-v1-typo"
    assert detail["status"] == "missing", "既有键保持原形，控制台/测试照旧匹配"
    assert detail["proposal_id"] == "library-api-v1-typo"
    assert detail["existing_contract_ids"] == ["library-api-v1"], "要给出能直接照抄的清单"
    assert "library-api-v1" in detail["next"], "next 里也要说到它"


def test_a_refusal_with_no_contracts_at_all_says_so(runtime: _Runtime) -> None:
    task = _published(runtime, required_contract_ids=["anything"])

    with pytest.raises(HTTPException) as refused:
        _begin(runtime, task, runtime.main)

    detail = refused.value.detail
    assert detail["existing_contract_ids"] == []
    assert "一个都没有" in detail["next"], "空清单也要说出来，别让人以为是没查"


# --- C. 拒绝可归因；主 Agent 看得见，worker 看不见 -------------------------------------------


class _ContextRuntime(_Runtime):
    """`context.project_read` 那两条断言不需要真 SQLite：拒绝清单只经 `list_events`。"""


@pytest.fixture(name="ledger_runtime")
def _ledger_runtime(tmp_path: Path) -> _ContextRuntime:
    store = _FakeEventStore([
        _denial(None, "root_binding_required", at=1),
        _denial("task-a", "required_contract_not_accepted:gone", at=100),
        _denial("task-a", "required_contract_not_accepted:gone", at=200),
        _denial("task-b", "task_dependency_pending:dep", at=300),
    ])
    runtime = _ContextRuntime(tmp_path, database=store)
    runtime.store = store
    runtime.main = runtime.enroll("main")
    runtime.worker = runtime.enroll("worker")
    runtime.call("authority.appoint", {"agent_id": runtime.main.agent_id})
    return runtime


def test_main_sees_repeated_denials_aggregated_per_task(ledger_runtime: _ContextRuntime) -> None:
    view = ledger_runtime.call("context.project_read", {}, ledger_runtime.main)

    denied = view["coordination"]["denied"]
    assert {row["task_id"] for row in denied} == {"task-a", "task-b"}
    latest_first = [row["task_id"] for row in denied]
    assert latest_first == ["task-b", "task-a"], "按最后一次出现排序"
    task_a = next(row for row in denied if row["task_id"] == "task-a")
    assert (task_a["count"], task_a["code"], task_a["last_at"]) == (
        2, "required_contract_not_accepted:gone", 200,
    )
    assert view["next"], "有任务被拒 ≥2 次就要给一句提示"
    assert "task-a" in view["next"] and "2 次" in view["next"]


def test_a_worker_never_sees_the_denial_ledger(ledger_runtime: _ContextRuntime) -> None:
    worker_view = ledger_runtime.call("context.project_read", {}, ledger_runtime.worker)

    assert "denied" not in worker_view["coordination"]
    assert "next" not in worker_view
    # worker 的读取**根本不查**这些事件：这份清单只服务协调者，不能给每个 worker 每回合加一次读。
    assert ledger_runtime.store.calls == []

    # 而 main 的那一次是定长查询（一次、有上限），不会把每回合的读取拖长。
    ledger_runtime.call("context.project_read", {}, ledger_runtime.main)
    assert len(ledger_runtime.store.calls) == 1
    assert ledger_runtime.store.calls[0]["limit"] == DENIAL_EVENT_WINDOW + 4
    assert ledger_runtime.store.calls[0]["event_type_like"] == "%.denied"


def test_a_single_denial_is_listed_without_a_hint(ledger_runtime: _ContextRuntime) -> None:
    ledger_runtime.store.events = [_denial("task-c", "attempt_still_active", at=77)]

    view = ledger_runtime.call("context.project_read", {}, ledger_runtime.main)

    assert [row["task_id"] for row in view["coordination"]["denied"]] == ["task-c"]
    assert "next" not in view, "只被拒一次是正常拒绝，不必每回合提醒"


def test_the_ledger_is_capped_and_ignores_unattributable_denials(ledger_runtime: _ContextRuntime) -> None:
    ledger_runtime.store.events = [
        _denial(None, "resource_conflict", at=at) for at in range(1, 20)
    ] + [
        _denial(f"task-{index:02d}", "task_not_beginable", at=100 + index) for index in range(20)
    ]

    view = ledger_runtime.call("context.project_read", {}, ledger_runtime.main)

    denied = view["coordination"]["denied"]
    assert len(denied) == DENIAL_ROW_LIMIT, "行数封顶，这份清单不是台账"
    assert [row["task_id"] for row in denied] == [f"task-{index:02d}" for index in reversed(range(10, 20))]
    assert all(row["count"] == 1 for row in denied)


def test_an_unreachable_event_store_does_not_break_the_read(tmp_path: Path) -> None:
    class _Broken(_FakeEventStore):
        def list_events(self, **kwargs: Any) -> list[dict[str, Any]]:
            raise RuntimeError("event store down")

    runtime = _Runtime(tmp_path, database=_Broken([]))
    main = runtime.enroll("main")
    runtime.enroll("worker")
    runtime.call("authority.appoint", {"agent_id": main.agent_id})

    view = runtime.call("context.project_read", {}, main)

    assert "denied" not in view["coordination"]
    assert view["role"] == "main"
