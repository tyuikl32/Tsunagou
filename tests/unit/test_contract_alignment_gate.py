"""The contract gates on the two execution boundaries.

Two questions are asked there, and both boundaries ask them the same way so that
"settled enough to start" and "settled enough to publish" cannot drift apart:

* *is an agreement in force at all* — a task that declares a contract (a proposal whose
  payload names it) must not begin, and must not publish a result, while that agreement is
  unsettled: nothing accepted yet, or a revision still under discussion;
* *is the version you read the one that governs* — a caller that declares the contract
  versions it read (the bridge fills this in from ``context.project_read``) is refused when
  its declaration is no longer in force, so a worker that finished under a superseded
  agreement reads the new version, brings its work up to date and submits again.

This replaces ``tests/integration/test_submit_time_scope_gate.py``, which covered the
same question together with the lease-based "unreported change" refusal. The FX line
replaced timed leases with explicit reservations and moved result recording into
``task.submit``, where what gets recorded is the daemon's own filesystem observation
rather than the caller's declaration (see
``docs/decisions/2026-09-28-explicit-resource-release.md``). That half of the gate has
no subject left, so only the contract half is kept.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tsunagou.application.workflows.execution_commands import ExecutionCommands
from tsunagou.modules.authority import AuthorityService
from tsunagou.modules.cognition import CognitionService
from tsunagou.modules.coordination import CoordinationService
from tsunagou.modules.messaging import MessageStore
from tsunagou.modules.resources import ResourceService
from tsunagou.modules.tasks import TaskService
from tsunagou.modules.workspaces import WorkspaceService

TASK = "task-1"
WORKER = "agent-w"
PARTICIPANT = {"slot": "writer", "agent_id": WORKER, "required": True}


def _commands(tmp_path: Path) -> tuple[ExecutionCommands, CognitionService]:
    cognition = CognitionService()
    return (
        ExecutionCommands(
            authority=AuthorityService(tmp_path / "identity.json"),
            tasks=TaskService(), cognition=cognition, resources=ResourceService(),
            workspaces=WorkspaceService(), coordination=CoordinationService(),
            evidence=None, artifacts=None, lifecycle=None, project_id="local-project",
            state_runtime=None, messages=MessageStore(),
        ),
        cognition,
    )


def _declare(cognition: CognitionService, *, supersedes_id: str | None = None) -> Any:
    """Declare the one contract this task depends on."""

    return cognition.propose_contract(
        {"task_id": TASK}, [PARTICIPANT], proposed_by=WORKER, supersedes_id=supersedes_id,
    )


def _accept(cognition: CognitionService, proposal: Any) -> None:
    cognition.accept_contract(
        proposal.proposal_id, participant_slot="writer",
        proposal_digest=proposal.digest, actor_id=WORKER,
    )


def _context() -> dict[str, Any]:
    return {"principal_id": WORKER, "session_id": "session-1", "connection_epoch": 1, "_prepared": {}}


def test_begin_refuses_while_the_declared_contract_is_unsettled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands, cognition = _commands(tmp_path)
    monkeypatch.setattr(commands, "authorize", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        commands.workflow, "validate_begin", lambda *args, **kwargs: SimpleNamespace(task_id=TASK)
    )
    payload = {"task_id": TASK, "expected_task_revision": 1}
    proposal = _declare(cognition)

    with pytest.raises(ValueError, match="contract_not_accepted"):
        commands.check_begin(payload, _context())

    _accept(cognition, proposal)
    assert commands.check_begin(payload, _context()).task_id == TASK


def test_submit_refuses_while_the_declared_contract_is_unsettled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands, cognition = _commands(tmp_path)
    monkeypatch.setattr(commands, "authorize", lambda *args, **kwargs: None)
    monkeypatch.setattr(commands.workflow, "validate_submit", lambda *args, **kwargs: None)
    payload = {"task_id": TASK, "attempt_id": "attempt-1", "summary": "done"}
    proposal = _declare(cognition)

    with pytest.raises(ValueError, match="contract_not_accepted"):
        commands.submit(payload, _context())

    # The same declaration the start boundary reads settles this one too.
    _accept(cognition, proposal)
    assert not cognition.unaligned_contracts_for_task(TASK)


def test_a_revision_under_discussion_holds_the_boundary_until_it_settles(tmp_path: Path) -> None:
    commands, cognition = _commands(tmp_path)
    first = _declare(cognition)
    _accept(cognition, first)
    commands._require_contract_alignment(TASK)  # type: ignore[attr-defined]  # in force: allowed

    revision = _declare(cognition, supersedes_id=first.proposal_id)
    with pytest.raises(ValueError, match="contract_not_accepted"):
        commands._require_contract_alignment(TASK)  # type: ignore[attr-defined]

    _accept(cognition, revision)
    commands._require_contract_alignment(TASK)  # type: ignore[attr-defined]  # settled again
    assert cognition.current_contract_versions(TASK) == (f"{revision.proposal_id}:{revision.digest}",)


def test_a_task_without_a_declared_contract_is_not_refused(tmp_path: Path) -> None:
    commands, _ = _commands(tmp_path)

    commands._require_contract_alignment("task-with-no-contract")  # type: ignore[attr-defined]


def test_the_version_declaration_is_compared_only_when_it_is_present(tmp_path: Path) -> None:
    commands, cognition = _commands(tmp_path)
    first = _declare(cognition)
    _accept(cognition, first)
    in_force = list(cognition.current_contract_versions(TASK))

    # No declaration: the comparison is what the declaration makes possible, so an
    # in-process caller and the A2A face keep working.
    commands._require_declared_contract_versions(TASK, {})  # type: ignore[attr-defined]
    commands._require_declared_contract_versions(  # type: ignore[attr-defined]
        TASK, {"expected_revisions": {"task": 3}}
    )

    commands._require_declared_contract_versions(  # type: ignore[attr-defined]
        TASK, {"expected_revisions": {"contract": in_force}}
    )

    with pytest.raises(ValueError, match="contract_revision_conflict"):
        commands._require_declared_contract_versions(  # type: ignore[attr-defined]
            TASK, {"expected_revisions": {"contract": "not-a-list"}}
        )
    with pytest.raises(ValueError, match="contract_revision_conflict"):
        commands._require_declared_contract_versions(  # type: ignore[attr-defined]
            TASK, {"expected_revisions": {"contract": []}}
        )
