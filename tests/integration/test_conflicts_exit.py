"""The console's conflict ledger has to read back the refusals the route records.

The chain is: ``execution_scope`` -> ``ExecutionCommands.requests`` -> ``ResourceService.reserve_set``
-> ``_conflict`` -> ``ResourceConflict`` -> ``api/app.py`` records ``command.<kind>.denied`` -> this
exit reads those rows. The write side records ``ResourceConflict.code``, which is the bare
``resource_conflict`` (the colon form only ever lived in the exception *message*), so a reader that
only accepted ``resource_conflict:`` silently answered "no conflicts" for every real collision.

These tests therefore assert at the **exit** (the public query a page reads), not at the raised
exception: a refusal nobody can read back is the bug, and only this layer can show it.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi import HTTPException
from tests.integration.test_state_integrity import events
from tests.integration.test_state_integrity import runtime as _runtime_fixture

WRITE_SCOPE = {
    "resources": [
        {"kind": "path", "root_id": "coordination", "segments": ["demo.txt"], "mode": "exclusive_write"},
    ],
}


@pytest.fixture(name="runtime")
def conflicts_runtime(tmp_path, monkeypatch):
    yield from _runtime_fixture.__wrapped__(tmp_path, monkeypatch)


def conflict_ledger(app: Any) -> dict[str, Any]:
    """Read the exit the way the console does: through the public HTTP route."""
    endpoint = next(
        route.endpoint for route in app.routes
        if getattr(route, "path", "") == "/api/v1/projects/{project_id}/conflicts"
    )
    return endpoint(app.state.project_database.project_id)


def denial_codes(app: Any) -> list[str]:
    return [
        str(json.loads(str(row["payload_json"])).get("code", ""))
        for row in events(app) if str(row["event_type"]).endswith(".denied")
    ]


def published(call, main, scope: dict[str, Any]) -> dict[str, Any]:
    task = call("task.create", {"title": "write", "objective": "produce output", "execution_scope": scope}, main)
    call("workspace.select", {"task_id": task["task_id"], "driver_kind": "shared"}, main)
    call("task.ready", {"task_id": task["task_id"]}, main)
    return call("task.publish", {"task_id": task["task_id"]}, main)


def begin(call, task: dict[str, Any], actor: dict[str, Any]):
    return call("task.begin", {"task_id": task["task_id"], "expected_task_revision": task["revision"]}, actor)


def test_conflict_exit_names_the_real_holder_after_a_refused_begin(runtime) -> None:
    app, call, main, worker = runtime
    holder_task = published(call, main, WRITE_SCOPE)
    holder = begin(call, holder_task, worker)
    state = app.state.state_runtime
    reservation = state.resources.reservations[holder["reservation_id"]]
    assert reservation.status == "active" and reservation.owner_agent_id == worker["agent_id"]

    # Same root, same path, both exclusive_write, and the first reservation is still
    # active: a real collision, not a fabricated one.
    challenger_task = published(call, main, WRITE_SCOPE)
    with pytest.raises(HTTPException) as denied:
        begin(call, challenger_task, main)
    assert denied.value.status_code == 409
    assert denied.value.detail["code"] == "resource_conflict"
    assert denied.value.detail["blockers"][0]["owner_agent_id"] == worker["agent_id"]

    assert denial_codes(app) == ["resource_conflict"]

    ledger = conflict_ledger(app)
    assert ledger["items"], "the conflict exit dropped a refusal the command route recorded"
    conflict = ledger["items"][0]
    assert conflict["phase"] == "task.begin"
    assert conflict["requester"]["task_id"] == challenger_task["task_id"]
    assert conflict["requester"]["resource_keys"] == ["path:coordination:demo.txt"]
    assert [holder_row["agent_id"] for holder_row in conflict["holders"]] == [worker["agent_id"]]
    assert conflict["holders"][0]["attempt_id"] == holder["attempt_id"]
    assert conflict["holders"][0]["held_key"] == "path:coordination:demo.txt"
    # Nobody reported an outcome: the exit asks the *current* reservations what happened.
    assert reservation.status == "active"
    assert conflict["resolution"] == "open"


def test_conflict_exit_keeps_out_refusals_that_are_not_collisions(runtime) -> None:
    app, call, main, worker = runtime
    task = published(call, main, {})
    begin(call, task, worker)
    # ``agent.retire.user`` refuses while the agent still holds work. That refusal is
    # recorded in the very same ledger, so it is the cheapest proof that the reader is
    # filtered on the collision code rather than reporting every denial.
    with pytest.raises(HTTPException) as denied:
        call("agent.retire.user", {"agent_id": worker["agent_id"], "reason": "no longer needed"}, None)
    assert denied.value.status_code == 409 and denied.value.detail["code"] == "agent_has_open_work"
    assert denial_codes(app) == ["agent_has_open_work"]
    # The exit reads the same ledger rows, so it must still answer "no collisions".
    assert conflict_ledger(app)["items"] == []
