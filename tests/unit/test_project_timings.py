"""Public timing composition keeps exact identity and evidence-source boundaries."""

from __future__ import annotations

import importlib
import json
import urllib.error
from copy import deepcopy
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from typer.testing import CliRunner

from tsunagou.application.workflows.project_timings import read_project_timings, summarize_project_timings
from tsunagou.generated.protocol.audit import AuditEventModel

cli = importlib.import_module("tsunagou.cli.app")
FIXTURE = json.loads((Path(__file__).parents[2] / "protocol/fixtures/valid/audit-page.json").read_text())
START = "2026-09-28T10:00:00.000Z"
SUBMIT = "2026-09-28T10:00:05.123Z"
REVIEW = "2026-09-28T10:00:07.123Z"


def event(action, when, attempt="attempt-1", *, number=1, state=None, refs=None):
    row = deepcopy(FIXTURE["items"][0])
    row.update(event_id=f"event-{number}", event_seq=number, source_event_id=f"event-{number}", source_event_seq=number,
               action=action, occurred_at=when, recorded_at=when)
    change = row["changes"][0]
    row["changes"] = [dict(change, subject_ref=ref, state_after=state) for ref in (refs or [f"attempt/{attempt}"])]
    return AuditEventModel.model_validate(row)


def inputs():
    return (
        {"project_id": "project-1", "items": [{"attempt_id": "attempt-1", "task_id": "task-1", "owner_agent_id": "worker-1",
                                               "status": "completed", "created_at": START, "ended_at": REVIEW}]},
        {"project_id": "project-1", "items": [{"result_id": "result-1", "attempt_id": "attempt-1", "task_id": "task-1",
                                               "created_at": SUBMIT, "payload": "PRIVATE", "evidence_refs": ["message/PRIVATE"]}]},
    )


def summary(events=(), *, attempts=None, results=None):
    base_attempts, base_results = inputs()
    return summarize_project_timings("project-1", attempts or base_attempts, results or base_results, events).items[0]


def test_public_result_time_is_separate_from_missing_submit_audit():
    attempts, results = inputs()
    before = deepcopy((attempts, results))
    row = summary([event("task.begin", START, state="running"), event("task.review.accept", REVIEW, number=3)],
                  attempts=attempts, results=results)
    assert row.submitted_at == SUBMIT and row.submitted_source == "result_created_at"
    assert row.started_source == "task_begin_event" and row.reviewed_source == "task_review_event"
    assert (row.begin_events, row.submit_events) == (1, 0)
    assert row.work_elapsed.model_dump() == {"elapsed_ms": 5123, "clock_status": "ok"}
    assert row.review_wait_elapsed.elapsed_ms == 2000
    assert "PRIVATE" not in row.model_dump_json()
    assert "evidence_refs" not in row.model_dump_json()
    assert (attempts, results) == before


def test_visible_submit_is_preferred_and_missing_times_are_not_replaced():
    row = summary([event("task.submit", SUBMIT)])
    assert row.submitted_source == "task_submit_event" and row.submit_events == 1
    assert row.started_at is None and row.started_source is None
    assert row.reviewed_at is None and row.work_elapsed.clock_status == "unknown"
    # A visible event with unknown occurred_at cannot use recorded_at as an occurrence.
    unknown = event("task.begin", None, state="running").model_copy(update={"recorded_at": START})
    assert summary([unknown]).started_at is None


def test_result_offset_is_normalized_before_comparing_submit_sources():
    _, results = inputs()
    results["items"][0]["created_at"] = "2026-09-28T18:00:05.123+08:00"
    assert summary(results=results).submitted_at == SUBMIT
    assert summary([event("task.submit", SUBMIT)], results=results).submitted_source == "task_submit_event"


@pytest.mark.parametrize("created", [None, "invalid", "2026-09-28T10:00:00", "2026-02-30T10:00:00.000Z"])
def test_partial_result_does_not_use_updated_or_attempt_end_time(created):
    attempts, results = inputs()
    results["items"][0].update(created_at=created, updated_at=SUBMIT)
    row = summary(results=results)
    assert row.submitted_at is None and row.submitted_source is None
    assert row.work_elapsed.clock_status == "unknown"
    results["items"] = []
    assert summary(attempts=attempts, results=results).submitted_at is None


def test_multiple_results_conflicts_and_multiple_visible_submits_stay_unknown():
    attempts, results = inputs()
    results["items"].append(dict(results["items"][0], result_id="result-2"))
    assert summary([event("task.submit", SUBMIT)], results=results).submitted_at is None
    assert summary([event("task.submit", REVIEW)]).submitted_at is None
    row = summary([event("task.submit", SUBMIT), event("task.submit", SUBMIT, number=2)])
    assert row.submit_events == 2 and row.submitted_at is None and row.submitted_source is None
    results["items"] = [dict(results["items"][0], task_id="another-task")]
    assert summary(results=results).submitted_at is None


def test_new_begin_cannot_start_old_attempt_and_reviews_use_exact_refs():
    attempts, results = inputs()
    attempts["items"].append(dict(attempts["items"][0], attempt_id="attempt-2", status="running"))
    old_begin = event("task.begin", START, state="running")
    new_begin = event("task.begin", REVIEW, "attempt-2", number=4, state="running")
    new_begin.changes.append(old_begin.changes[0].model_copy(update={"state_after": "orphaned"}))
    rejected = event("task.review.request_changes", REVIEW, number=3, refs=["review/result-1::1"])
    unrelated_review = event("task.review.accept", REVIEW, number=5, refs=["task/task-1"])
    rows = summarize_project_timings("project-1", attempts, results, [old_begin, rejected, new_begin, unrelated_review]).items
    assert rows[0].started_at == START and rows[0].begin_events == 1
    assert rows[0].review_action == "task.review.request_changes"
    assert rows[1].started_at == REVIEW and rows[1].begin_events == 1
    assert rows[1].submitted_at is None and rows[1].reviewed_at is None
    assert not summarize_project_timings("project-1", attempts, results, [], task_id="other").items


def test_clock_reversal_retains_facts_without_a_successful_duration():
    row = summary([event("task.begin", REVIEW, state="running"), event("task.review.accept", START, number=2)])
    assert row.started_at == REVIEW and row.submitted_at == SUBMIT and row.reviewed_at == START
    assert row.work_elapsed.model_dump() == {"elapsed_ms": None, "clock_status": "clock_inconsistent"}
    assert row.review_wait_elapsed.clock_status == "clock_inconsistent"


def test_complete_pagination_and_cli_authentication_privacy(monkeypatch):
    attempts, results = inputs()
    calls = []
    pages = [dict(FIXTURE, items=[event("task.begin", START, state="running").model_dump()], next_cursor="next"),
             dict(FIXTURE, items=[event("task.review.accept", REVIEW, number=2).model_dump()], next_cursor=None)]

    def request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        if "/history?" in path:
            return pages[int("cursor" in parse_qs(urlparse(path).query))]
        return results if path.endswith("/results") else attempts

    monkeypatch.setattr(cli, "_control_token", lambda: "CONTROL-SENTINEL")
    monkeypatch.setattr(cli, "_daemon_request", request)
    result = CliRunner().invoke(cli.app, ["--json", "project", "timings", "project-1", "--task-id", "task-1"])
    assert result.exit_code == 0, result.output
    row = json.loads(result.output)["items"][0]
    assert row["submitted_source"] == "result_created_at" and row["submit_events"] == 0
    assert row["reviewed_at"] == REVIEW
    assert len(calls) == 4 and all(method == "GET" for method, _, _ in calls)
    assert all(headers == {"authorization": "Bearer CONTROL-SENTINEL"} for _, _, headers in calls)
    assert "PRIVATE" not in result.output and "CONTROL-SENTINEL" not in result.output
    human = CliRunner().invoke(cli.app, ["project", "timings", "project-1"])
    assert human.exit_code == 0 and "result_created_at" in human.output and "5123 ms" in human.output


@pytest.mark.parametrize("failure", ["duplicate_event", "cursor_cycle", "wrong_project", "changed_snapshot", "bad_response"])
def test_invalid_or_incomplete_history_fails_closed(monkeypatch, failure):
    calls = 0

    def read(path):
        nonlocal calls
        calls += 1
        assert "/history?" in path
        page = dict(FIXTURE, items=[event("task.begin", START, state="running").model_dump()], next_cursor="next")
        if failure == "bad_response":
            return {"private": "DO-NOT-ECHO"}
        if failure == "wrong_project":
            page["project_id"] = "other"
        if calls == 2:
            page.update(next_cursor=None if failure == "duplicate_event" else "next",
                        snapshot_event_seq=999 if failure == "changed_snapshot" else page["snapshot_event_seq"])
            if failure == "cursor_cycle":
                page["items"] = [event("task.submit", SUBMIT, number=2).model_dump()]
        return page

    monkeypatch.setattr(cli, "_control_token", lambda: "control")
    monkeypatch.setattr(cli, "_daemon_request", lambda method, path, **kwargs: read(path))
    result = CliRunner().invoke(cli.app, ["project", "timings", "project-1", "--json"])
    assert result.exit_code == 5
    assert json.loads(result.output)["error"] == "invalid_timing_response"
    assert "DO-NOT-ECHO" not in result.output


@pytest.mark.parametrize("status", [401, 403])
def test_failed_auth_never_reads_entity_pages(monkeypatch, status):
    def request(method, path, **kwargs):
        assert "/history?" in path
        raise RuntimeError("http_error") from urllib.error.HTTPError("http://localhost", status, "", {}, None)

    monkeypatch.setattr(cli, "_daemon_request", request)
    monkeypatch.setattr(cli, "_control_token", lambda: "control")
    assert CliRunner().invoke(cli.app, ["project", "timings", "project-1"]).exit_code == 3
    monkeypatch.setattr(cli, "_control_token", lambda: None)
    assert CliRunner().invoke(cli.app, ["project", "timings", "project-1"]).exit_code == 3


@pytest.mark.parametrize("status,exit_code", [(400, 2), (403, 3), (500, 5), (None, 5)])
def test_cli_failure_does_not_echo_arbitrary_daemon_errors(monkeypatch, status, exit_code):
    def request(method, path, **kwargs):
        cause = urllib.error.HTTPError("http://localhost", status, "", {}, None) if status else None
        raise RuntimeError("SENTINEL-PRIVATE-ERROR message/private-reference") from cause

    monkeypatch.setattr(cli, "_daemon_request", request)
    monkeypatch.setattr(cli, "_control_token", lambda: "control")
    output = CliRunner().invoke(cli.app, ["project", "timings", "project-1", "--json"])
    assert output.exit_code == exit_code
    assert "SENTINEL" not in output.output and "private-reference" not in output.output
    assert json.loads(output.output)["error"] == (f"http_{status}" if status else "timing_query_failed")


def test_wrong_entity_project_is_rejected():
    attempts, results = inputs()
    results["project_id"] = "other"
    with pytest.raises(ValueError, match="timing_project_mismatch"):
        summarize_project_timings("project-1", attempts, results, [])


def test_reader_rejects_duplicate_history_before_loading_entities():
    # The direct composition API also rejects duplicates instead of counting replays.
    with pytest.raises(ValueError, match="duplicate_timing_event"):
        summary([event("task.begin", START), event("task.begin", START)])
    with pytest.raises(ValueError):
        read_project_timings("project-1", lambda path: {"private": "invalid"})
