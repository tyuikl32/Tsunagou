"""Read-only composition of public Attempts, Results and authorized audit facts."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Literal, cast
from urllib.parse import quote, urlencode

from pydantic import BaseModel, ConfigDict, Field

from tsunagou.generated.protocol.audit import AuditEventModel, AuditPageModel
from tsunagou.shared_kernel.query_models import AttemptTimingModel, ProjectTimingsModel, TimingElapsedModel
from tsunagou.shared_kernel.time import format_timestamp, parse_timestamp


class _Attempt(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    attempt_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    owner_agent_id: str = Field(min_length=1)
    status: str = Field(min_length=1)


class _Result(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    result_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    attempt_id: str = Field(min_length=1)
    created_at: str | None = None


class _AttemptPage(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    project_id: str
    items: list[_Attempt]


class _ResultPage(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    project_id: str
    items: list[_Result]


def _timestamp(value: str | None) -> str | None:
    try:
        return format_timestamp(parse_timestamp(value))
    except ValueError:
        return None


def _event_time(events: Sequence[AuditEventModel]) -> str | None:
    # Multiple facts are ambiguous even if their clocks happen to agree.
    return _timestamp(events[0].occurred_at) if len(events) == 1 else None


def _elapsed(start: str | None, end: str | None) -> TimingElapsedModel:
    start_ms, end_ms = parse_timestamp(start), parse_timestamp(end)
    if start_ms is None or end_ms is None:
        return TimingElapsedModel(elapsed_ms=None, clock_status="unknown")
    if end_ms < start_ms:
        return TimingElapsedModel(elapsed_ms=None, clock_status="clock_inconsistent")
    return TimingElapsedModel(elapsed_ms=end_ms - start_ms, clock_status="ok")


def summarize_project_timings(
    project_id: str, attempts: dict[str, Any], results: dict[str, Any], events: Sequence[AuditEventModel],
    *, task_id: str | None = None,
) -> ProjectTimingsModel:
    """Join exact public identities without interpreting payloads or private evidence.

    Inputs must already be authorized. No Attempt or Task metadata is a fallback
    for begin/submit/review. Result creation is the server's recorded submit time,
    not a measurement of SQLite COMMIT/fsync completion.
    """
    attempt_page, result_page = _AttemptPage.model_validate(attempts), _ResultPage.model_validate(results)
    if attempt_page.project_id != project_id or result_page.project_id != project_id:
        raise ValueError("timing_project_mismatch")
    if any(event.project_id != project_id for event in events):
        raise ValueError("timing_project_mismatch")
    if len({item.attempt_id for item in attempt_page.items}) != len(attempt_page.items):
        raise ValueError("duplicate_timing_attempt")
    if len({event.event_id for event in events}) != len(events):
        raise ValueError("duplicate_timing_event")
    items = []
    for attempt in attempt_page.items:
        if task_id is not None and attempt.task_id != task_id:
            continue
        matches = [result for result in result_page.items if result.attempt_id == attempt.attempt_id]
        result = matches[0] if len(matches) == 1 and matches[0].task_id == attempt.task_id else None
        related = []
        for event in events:
            if event.subject_ref != f"task/{attempt.task_id}" or event.outcome != "committed":
                continue
            refs = {change.subject_ref for change in event.changes}
            # Review may name an exact Result without changing the Attempt.
            result_refs = {f"result/{result.result_id}"} if result is not None else set()
            if result is not None:
                result_refs.update(ref for ref in refs if ref.startswith(f"review/{result.result_id}::"))
            if f"attempt/{attempt.attempt_id}" in refs or refs & result_refs:
                related.append(event)
        begins = [event for event in related if event.action == "task.begin" and any(
            change.subject_ref == f"attempt/{attempt.attempt_id}" and change.state_after == "running"
            for change in event.changes
        )]
        submits = [event for event in related if event.action == "task.submit"]
        reviews = [event for event in related if event.action in {"task.review.accept", "task.review.request_changes"}]
        started, submitted, reviewed = _event_time(begins), _event_time(submits), _event_time(reviews)
        source: Literal["task_submit_event", "result_created_at"] | None = "task_submit_event" if submitted is not None else None
        result_time = _timestamp(result.created_at) if result is not None else None
        if len(matches) > 1 or (matches and result is None):
            submitted, source = None, None
        elif submitted is not None and result_time is not None and submitted != result_time:
            submitted, source = None, None
        elif not submits and result_time is not None:
            submitted, source = result_time, "result_created_at"
        items.append(AttemptTimingModel(
            attempt_id=attempt.attempt_id, task_id=attempt.task_id, owner_agent_id=attempt.owner_agent_id,
            state=attempt.status, started_at=started, submitted_at=submitted, reviewed_at=reviewed,
            started_source="task_begin_event" if started is not None else None,
            submitted_source=source, reviewed_source="task_review_event" if reviewed is not None else None,
            begin_events=len(begins), submit_events=len(submits),
            review_action=cast(Literal["task.review.accept", "task.review.request_changes"], reviews[0].action)
            if reviewed is not None else None,
            work_elapsed=_elapsed(started, submitted), review_wait_elapsed=_elapsed(submitted, reviewed),
        ))
    return ProjectTimingsModel(project_id=project_id, items=items)


def read_project_timings(
    project_id: str, read: Callable[[str], dict[str, Any]], *, task_id: str | None = None,
) -> ProjectTimingsModel:
    """Use existing authenticated GETs; fail closed on incomplete audit pagination."""
    base = f"/api/v1/projects/{quote(project_id, safe='')}"
    events: list[AuditEventModel] = []
    event_ids: set[str] = set()
    cursors: set[str] = set()
    cursor = None
    snapshot = None
    while True:
        filters = {"limit": "200", **({"cursor": cursor} if cursor is not None else {})}
        page = AuditPageModel.model_validate(read(f"{base}/history?{urlencode(filters)}"))
        if page.project_id != project_id or (snapshot is not None and page.snapshot_event_seq != snapshot):
            raise ValueError("invalid_timing_pagination")
        snapshot = page.snapshot_event_seq
        for event in page.items:
            if event.event_id in event_ids:
                raise ValueError("duplicate_timing_event")
            event_ids.add(event.event_id)
        events.extend(page.items)
        cursor = page.next_cursor
        if cursor is None:
            break
        if not cursor or cursor in cursors:
            raise ValueError("invalid_timing_pagination")
        cursors.add(cursor)
    return summarize_project_timings(project_id, read(f"{base}/attempts"), read(f"{base}/results"), events, task_id=task_id)
