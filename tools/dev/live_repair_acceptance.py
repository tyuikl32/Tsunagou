"""Read-only live acceptance capture. Does not enroll, wake, execute or approve.

Only installed CLI queries and allowlisted public facts enter the evidence
directory. A1-A8 are operator-reviewed scenarios, never inferred from fixtures,
message ACKs or successful builds.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

CRITERIA = {
    "A1": "Independent installation and original main plus two manual Desktop workers",
    "A2": "Daemon wakes idle original conversations without developer follow-up",
    "A3": "Two real begin/work/submit/review deliveries in disjoint scopes",
    "A4": "Long turn, restart ownership and explicit recovery fencing",
    "A5": "Real disagreement resolved through a contract; terminal/cancel regression",
    "A6": "Related task waits for user; unrelated work continues; original turn resumes",
    "A7": "CLI timing/failure facts and real SDK trace; unknown usage stays unavailable",
    "A8": "Real HTTP and browser BTID positive/corrupt/truncated checks",
}
UUID = r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"
PUBLIC_REF = re.compile(rf"^(?:(?:task|attempt|result|workspace|contract|decision|project|report|reservation)/)?{UUID}$")
SPAN_NAMES = {"command.execute", "a2a.submit", "outbox.deliver", "host.wake", "onboarding.restore"}
CODE = re.compile(r"^[a-z][a-z0-9_.-]{0,79}$")
VERSION = re.compile(r"(?:Python )?[0-9][0-9.a-z+-]{0,50}")


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def timestamp(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        instant = datetime.fromisoformat(value)
        if instant.tzinfo is None:
            return None
        return instant.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    except (ValueError, OverflowError):
        return None


def identity(value: Any) -> str | None:
    if isinstance(value, str) and (PUBLIC_REF.fullmatch(value) or re.fullmatch(rf"(?:wake|diagnostic):{UUID}", value)):
        return value
    return None


def code(value: Any) -> str | None:
    return value if isinstance(value, str) and CODE.fullmatch(value) else None


def version(value: Any) -> str | None:
    return value if isinstance(value, str) and VERSION.fullmatch(value) else None


def duration(value: Any) -> int | float | None:
    return value if type(value) in {int, float} and math.isfinite(value) and value >= 0 else None


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("object_required")
    return value


def public_event(item: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {key: timestamp(item.get(key)) for key in ("occurred_at", "recorded_at")}
    result.update({key: identity(item.get(key)) for key in ("event_id", "subject_ref", "caused_by_command_id")})
    result.update(
        action=code(item.get("action")),
        outcome=code(item.get("outcome")),
        actor_ref="user_control" if item.get("actor_ref") == "user_control" else identity(item.get("actor_ref")),
        event_seq=item.get("event_seq") if type(item.get("event_seq")) is int else None,
    )
    changes = item.get("changes")
    result["changes"] = [
        {
            "subject_ref": identity(change.get("subject_ref")),
            "state_before": code(change.get("state_before")),
            "state_after": code(change.get("state_after")),
        }
        for change in (changes if isinstance(changes, list) else [])
        if isinstance(change, dict) and identity(change.get("subject_ref"))
    ]
    return result


def public_diagnostic(item: dict[str, Any]) -> dict[str, Any]:
    result = {key: timestamp(item.get(key)) for key in ("occurred_at", "recorded_at", "observed_at")}
    result.update(
        {
            key: identity(item.get(key))
            for key in (
                "diagnostic_id",
                "project_id",
                "actor_id",
                "agent_id",
                "command_id",
                "task_id",
                "attempt_id",
                "wake_attempt_id",
            )
        }
    )
    # U queries do not acquire the worker's private message audience. Even a
    # malformed CLI result must not place message bodies or host IDs in export.
    details = item.get("details")
    details = details if isinstance(details, dict) else {}
    trigger_source = item.get("trigger_source")
    if trigger_source not in {"daemon_delivery", "user_followup", "developer_followup"}:
        trigger_source = details.get("trigger_source")
    result.update(
        kind=code(item.get("kind")),
        error_code=code(item.get("error_code")) or code(details.get("error_code")),
        trigger_source=trigger_source
        if trigger_source
        in {
            "daemon_delivery",
            "user_followup",
            "developer_followup",
            "unknown",
        }
        else "unknown",
    )
    return result


def public_agent(item: dict[str, Any]) -> dict[str, Any]:
    tasks = item.get("current_task_ids")
    return {
        "agent_id": identity(item.get("agent_id")),
        "role": code(item.get("role")),
        "session_status": code(item.get("session_status")),
        "current_task_ids": [identity(value) for value in (tasks if isinstance(tasks, list) else []) if identity(value)],
        "created_at": timestamp(item.get("created_at")),
        "last_activity_at": timestamp(item.get("last_activity_at")),
    }


def installation(item: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {key: timestamp(item.get(key)) for key in ("installed_at", "install_started_at", "install_finished_at")}
    commit = item.get("commit")
    result.update(
        status=code(item.get("status")),
        commit=commit if re.fullmatch(r"[0-9a-f]{40}", str(commit)) else None,
        source_dirty=item.get("source_dirty") if type(item.get("source_dirty")) is bool else None,
        duration_ms=duration(item.get("duration_ms")),
    )
    for key in ("python_version", "bridge_version"):
        result[key] = version(item.get(key))
    return result


def query(cli: str, root: Path, args: list[str]) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    observed = now()
    started = time.monotonic_ns()
    try:
        completed = subprocess.run(
            [cli, "--project-root", str(root), "--json", *args], cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=60
        )
        value = json.loads(completed.stdout) if completed.returncode == 0 else None
        success = isinstance(value, dict)
        status = {
            "observed_at": observed,
            "finished_at": now(),
            "exit_code": completed.returncode,
            "status": "ok" if success else "query_failed",
        }
    except (OSError, ValueError, subprocess.TimeoutExpired):
        value = None
        status = {"observed_at": observed, "finished_at": now(), "exit_code": None, "status": "query_failed"}
    status["duration_ms"] = (time.monotonic_ns() - started) / 1_000_000
    # Raw stdout/stderr can contain arbitrary errors. Never persist or echo it.
    return value if isinstance(value, dict) else None, status


def prepare(output: Path, project_root: Path, source_root: Path, cli: str) -> dict[str, Any]:
    if any((output / name).exists() for name in ("manifest.json", "review.json", "timeline.json", "deviations.md", "summary.md")):
        raise ValueError("run_already_prepared")
    output.mkdir(parents=True, exist_ok=True)
    recorded = now()
    manifest = {
        "schema": "tsunagou.live-acceptance.v1",
        "capture_started_at": recorded,
        "finished_at": None,
        "project_root": str(project_root.resolve()),
        "source_root": str(source_root.resolve()),
        "cli": cli,
        "timezone": datetime.now().astimezone().tzname(),
        "project_id": None,
        "host_versions": {"codex_app": None, "codex_cli": None, "codex_plugin": None},
        "latest_snapshot": None,
        "project_confirmation": "unverified",
        "token_usage": "unavailable",
    }
    write_json(output / "manifest.json", manifest)
    write_json(output / "review.json", {key: {"status": "not_run", "observed_at": None, "evidence_refs": []} for key in CRITERIA})
    write_json(output / "timeline.json", {"events": [], "diagnostics": [], "attempts": []})
    (output / "deviations.md").write_text(
        "# Live acceptance deviations\n\nAppend each trigger, observation, cause, fix and retest with UTC times. "
        "Keep failed automatic wake attempts when a developer or user later follows up.\n",
        encoding="utf-8",
    )
    lines = ["# Live acceptance", "", "Prepared only; no scenarios executed.", "", "| Item | Scenario | Result |", "| --- | --- | --- |"]
    lines += [f"| {key} | {label} | not_run |" for key, label in CRITERIA.items()]
    (output / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"status": "prepared", "capture_started_at": recorded, "criteria": {key: "not_run" for key in CRITERIA}}


def elapsed(start: str | None, end: str | None) -> dict[str, Any]:
    start, end = timestamp(start), timestamp(end)
    if not start or not end:
        return {"elapsed_ms": None, "clock_status": "unknown"}
    delta = (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds() * 1000
    return {"elapsed_ms": delta if delta >= 0 else None, "clock_status": "ok" if delta >= 0 else "clock_inconsistent"}


def public_timing(item: dict[str, Any]) -> dict[str, Any]:
    """Keep the installed CLI's source-labelled public facts, not private audit data."""
    result: dict[str, Any] = {
        key: identity(item.get(key)) for key in ("attempt_id", "task_id", "owner_agent_id")
    }
    sources = {
        "started": {"task_begin_event"},
        "submitted": {"task_submit_event", "result_created_at"},
        "reviewed": {"task_review_event"},
    }
    for field, allowed in sources.items():
        source = item.get(f"{field}_source")
        value = timestamp(item.get(f"{field}_at")) if isinstance(source, str) and source in allowed else None
        result[f"{field}_at"] = value
        result[f"{field}_source"] = source if value else None
    result["state"] = code(item.get("state"))
    result["review_action"] = code(item.get("review_action"))
    for key in ("begin_events", "submit_events"):
        value = item.get(key)
        result[key] = value if type(value) is int and value >= 0 else None
    result["work_elapsed"] = elapsed(result["started_at"], result["submitted_at"])
    result["review_wait_elapsed"] = elapsed(result["submitted_at"], result["reviewed_at"])
    return result


def page_items(
    page: dict[str, Any] | None, status: dict[str, Any], project_id: str, *, require_project: bool = False
) -> list[dict[str, Any]]:
    if page is None:
        return []
    items = page.get("items")
    returned_project_id = page.get("project_id")
    if (
        not isinstance(items, list)
        or any(not isinstance(item, dict) for item in items)
        or (require_project and returned_project_id != project_id)
        or (returned_project_id is not None and returned_project_id != project_id)
    ):
        status["status"] = "invalid_response"
        return []
    return items


def check(output: Path, cli_override: str | None = None) -> dict[str, Any]:
    manifest = load(output / "manifest.json")
    root = Path(manifest["project_root"])
    project_id = identity(load(root / ".tsunagou/project.json").get("project_id"))
    if not project_id:
        raise ValueError("project_id_unavailable")
    cli = cli_override or manifest["cli"]
    snapshot = output / "snapshots" / (datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:8])
    snapshot.mkdir(parents=True)
    statuses: dict[str, Any] = {}
    raw_install, statuses["installation"] = query(cli, root, ["installation-info", "--json"])
    raw_agents, statuses["agents"] = query(cli, root, ["agent", "list", "--json"])
    raw_doctor, statuses["doctor"] = query(cli, root, ["doctor"])
    raw_diagnostics, statuses["diagnostics"] = query(cli, root, ["project", "diagnostics", project_id, "--json"])
    raw_timings, statuses["timings"] = query(cli, root, ["project", "timings", project_id, "--json"])
    timings = [
        public_timing(item) for item in page_items(raw_timings, statuses["timings"], project_id, require_project=True)
    ]
    agents = [public_agent(item) for item in page_items(raw_agents, statuses["agents"], project_id)]
    diagnostics = [
        public_diagnostic(item) for item in page_items(raw_diagnostics, statuses["diagnostics"], project_id, require_project=True)
    ]
    events: list[dict[str, Any]] = []
    cursor = None
    seen: set[str] = set()
    statuses["history"] = []
    while True:
        args = ["project", "history", project_id, "--json", "--limit", "200"]
        if cursor:
            args += ["--cursor", cursor]
        page, status = query(cli, root, args)
        statuses["history"].append(status)
        if page is None:
            break
        page_events = [public_event(item) for item in page_items(page, status, project_id, require_project=True)]
        if status["status"] != "ok":
            break
        existing_ids = {item["event_id"] for item in events if item.get("event_id")}
        if any(item.get("event_id") in existing_ids for item in page_events if item.get("event_id")):
            status["status"] = "duplicate_history_event"
            break
        events.extend(page_events)
        cursor = page.get("next_cursor")
        if not cursor:
            break
        if not isinstance(cursor, str) or cursor in seen or len(seen) >= 1000:
            statuses["history"][-1]["status"] = "invalid_pagination"
            break
        seen.add(cursor)
    observed = now()
    history_complete = all(item["status"] == "ok" for item in statuses["history"])
    ids = [agent["agent_id"] for agent in agents if agent["agent_id"]]
    runtime = (raw_doctor or {}).get("runtime")
    health = runtime if isinstance(runtime, dict) else {}
    registered_projects = health.get("project_ids")
    facts = {
        "observed_at": observed,
        "project_id": project_id,
        "independent_agent_ids": len(ids) == len(agents) == len(set(ids)) if agents else None,
        "main_count": sum(agent["role"] == "main" for agent in agents),
        "worker_count": sum(agent["role"] == "worker" for agent in agents),
        "ready_agent_count": sum(agent["session_status"] == "ready" for agent in agents),
        "original_conversation_readiness": "requires_original_conversation_evidence",
        "daemon_status": code((raw_doctor or {}).get("daemon")),
        "daemon_runtime_id": identity(health.get("runtime_id")),
        "daemon_process_id": health.get("pid") if type(health.get("pid")) is int and health["pid"] > 0 else None,
        "daemon_project_ids": [
            identity(value) for value in (registered_projects if isinstance(registered_projects, list) else []) if identity(value)
        ],
        "daemon_contains_selected_project": project_id
        in [identity(value) for value in (registered_projects if isinstance(registered_projects, list) else []) if identity(value)],
        "runtime_version": version((raw_doctor or {}).get("version")),
        "installation": installation(raw_install or {}),
        "installation_record_matches_source": (
            str((raw_install or {}).get("source_root", "")).casefold() == str(Path(manifest["source_root"])).casefold()
        ),
        "history_complete": history_complete,
        "query_status": statuses,
        "recorded_recovery_events": sum(event["action"] in {"task.recover", "session.reconnect"} for event in events),
        "model_tool_calls": None,
        "token_usage": "unavailable",
    }
    timeline: dict[str, Any] = {
        "observed_at": observed,
        "history_complete": history_complete,
        "visibility": "authenticated_cli_projection",
        "events": events,
        "diagnostics": diagnostics,
        "attempts": timings,
    }
    for name, value in (("facts.json", facts), ("agents.json", {"items": agents}), ("timeline.json", timeline)):
        write_json(snapshot / name, value)
    manifest.update(
        project_id=project_id,
        latest_snapshot=snapshot.relative_to(output).as_posix(),
        last_checked_at=observed,
        installation=facts["installation"],
        runtime_version=facts["runtime_version"],
        agent_ids=ids,
        task_ids=sorted({item["task_id"] for item in timeline["attempts"]}),
        attempt_ids=[item["attempt_id"] for item in timeline["attempts"]],
    )
    write_json(output / "manifest.json", manifest)
    success = history_complete and all(
        statuses[name]["status"] == "ok" for name in ("installation", "agents", "doctor", "diagnostics", "timings")
    )
    return {
        "status": "captured" if success else "incomplete",
        "snapshot": snapshot.relative_to(output).as_posix(),
        "criteria": "requires_operator_review",
        "observed_at": observed,
    }


def public_manifest(item: dict[str, Any]) -> dict[str, Any]:
    """Retain declared run locations, never copy arbitrary operator-added fields."""
    result: dict[str, Any] = {"schema": "tsunagou.live-acceptance.v1", "token_usage": "unavailable"}
    for key in ("capture_started_at", "finished_at", "last_checked_at"):
        result[key] = timestamp(item.get(key))
    for key in ("project_root", "source_root", "cli", "timezone", "latest_snapshot"):
        result[key] = item.get(key) if isinstance(item.get(key), str) else None
    result["project_id"] = identity(item.get("project_id"))
    for key in ("agent_ids", "task_ids", "attempt_ids"):
        values = item.get(key)
        result[key] = [identity(value) for value in (values if isinstance(values, list) else []) if identity(value)]
    installed = item.get("installation")
    result["installation"] = installation(installed if isinstance(installed, dict) else {})
    result["runtime_version"] = version(item.get("runtime_version"))
    hosts = item.get("host_versions")
    result["host_versions"] = {
        key: version(hosts.get(key)) if isinstance(hosts, dict) else None for key in ("codex_app", "codex_cli", "codex_plugin")
    }
    return result


def public_span(item: Any, expected_project_id: str | None = None) -> dict[str, Any] | None:
    """Read the actual local OTLP collector's NDJSON; do not manufacture spans."""
    if not isinstance(item, dict) or not isinstance(item.get("name"), str) or item["name"] not in SPAN_NAMES:
        return None
    span = {"name": item["name"], "token_usage": "unavailable"}
    for key, length in (("trace_id", 32), ("span_id", 16), ("parent_span_id", 16)):
        value = item.get(key)
        valid = isinstance(value, str) and re.fullmatch(rf"[0-9a-f]{{{length}}}", value) and int(value, 16)
        span[key] = value if valid else None
    for key in ("started_at", "finished_at", "recorded_at"):
        span[key] = timestamp(item.get(key))
    if not all(span[key] for key in ("trace_id", "span_id", "started_at", "finished_at")):
        return None
    span["duration_ms"] = duration(item.get("duration_ms"))
    span["status"] = item.get("status") if type(item.get("status")) is int and item["status"] in {0, 1, 2} else None
    attrs = item.get("attributes")
    raw_attrs = attrs if isinstance(attrs, dict) else {}
    if expected_project_id and identity(raw_attrs.get("tsunagou.project_id")) != expected_project_id:
        return None
    attributes = {}
    for key, value in raw_attrs.items():
        if key in {
            "tsunagou.project_id",
            "tsunagou.actor_id",
            "tsunagou.agent_id",
            "tsunagou.task_id",
            "tsunagou.attempt_id",
            "tsunagou.message_id",
            "tsunagou.wake_attempt_id",
            "tsunagou.command_id",
        } and identity(value):
            attributes[key] = identity(value)
        elif key in {"tsunagou.command_kind", "tsunagou.trigger_source", "tsunagou.outcome", "tsunagou.error_code"} and code(value):
            attributes[key] = code(value)
    span["attributes"] = attributes
    return span


def export(output: Path, trace_file: Path | None = None) -> dict[str, Any]:
    manifest = public_manifest(load(output / "manifest.json"))
    if not manifest.get("latest_snapshot"):
        raise ValueError("check_required")
    snapshot = (output / manifest["latest_snapshot"]).resolve()
    if not snapshot.is_relative_to(output.resolve()):
        raise ValueError("snapshot_outside_run")
    timeline = load(snapshot / "timeline.json")
    timeline = {
        "observed_at": timestamp(timeline.get("observed_at")),
        "history_complete": timeline.get("history_complete") is True,
        "visibility": "authenticated_cli_projection",
        "events": [public_event(item) for item in timeline.get("events", [])],
        "diagnostics": [public_diagnostic(item) for item in timeline.get("diagnostics", [])],
        "attempts": [public_timing(item) for item in timeline.get("attempts", [])],
    }
    # Project completion is only observable from its U-owned domain event.
    confirmed = any(
        event.get("action") == "project.completion.confirm"
        and event.get("actor_ref") == "user_control"
        and event.get("subject_ref") == f"project/{manifest['project_id']}"
        and event.get("outcome") == "committed"
        for event in timeline["events"]
    )
    review = load(output / "review.json")
    criteria: dict[str, Any] = {}
    for key in CRITERIA:
        item = review.get(key, {})
        if not isinstance(item, dict):
            item = {}
        refs = []
        evidence_refs = item.get("evidence_refs")
        for ref in evidence_refs if isinstance(evidence_refs, list) else []:
            if not isinstance(ref, str) or not re.fullmatch(r"[a-zA-Z0-9_./-]{1,240}", ref):
                continue
            path = (output / ref).resolve()
            if (
                path.is_relative_to(output.resolve())
                and path.is_file()
                and ".tsunagou" not in path.parts
                and path.name not in {"manifest.json", "review.json", "summary.md"}
            ):
                refs.append(ref)
        status_value = item.get("status")
        status = status_value if isinstance(status_value, str) and status_value in {"pass", "fail", "not_run"} else "not_run"
        observed = timestamp(item.get("observed_at"))
        if status == "pass" and (not refs or observed is None):
            status = "not_run"
        criteria[key] = {
            "status": status,
            "observed_at": observed,
            "evidence_refs": refs,
            "source": "operator_review_not_script_verification",
        }
    spans = []
    invalid_lines = 0
    if trace_file:
        if trace_file.resolve() in {(output / name).resolve() for name in ("manifest.json", "trace.json", "timeline.json", "summary.md")}:
            raise ValueError("trace_input_overwrite")
        with trace_file.open(encoding="utf-8") as source:
            for line in source:
                try:
                    span = public_span(json.loads(line), manifest["project_id"])
                except ValueError:
                    span = None
                if span is None:
                    invalid_lines += 1
                else:
                    spans.append(span)
    write_json(output / "trace.json", {"spans": spans, "ignored_lines": invalid_lines, "exported_at": now()})
    write_json(output / "timeline.json", timeline)
    exported_at = now()
    manifest.update(
        criteria=criteria,
        project_confirmation="recorded_user_confirmation" if confirmed else "unverified",
        finished_at=exported_at,
        exported_at=exported_at,
        token_usage="unavailable",
    )
    write_json(output / "manifest.json", manifest)
    lines = [
        "# Live acceptance",
        "",
        f"Snapshot observed: {timeline['observed_at']}",
        "",
        "A1–A8 below are operator review records; the capture script does not certify LLM work.",
        "",
        "| Item | Result | Evidence |",
        "| --- | --- | --- |",
    ]
    lines += [f"| {key} | {item['status']} | {', '.join(item['evidence_refs']) or 'missing'} |" for key, item in criteria.items()]
    lines += [
        "",
        f"User project confirmation: {manifest['project_confirmation']}",
        "",
        "Timing is elapsed workflow time, not pure coding time. Parallel worker times are not summed.",
        "",
        "Tool count: unavailable. Token usage: unavailable. Earlier failed attempts remain in the timeline.",
    ]
    (output / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "status": "exported",
        "criteria": {key: item["status"] for key, item in criteria.items()},
        "project_confirmation": manifest["project_confirmation"],
        "trace_spans": len(spans),
        "manifest_sha256": hashlib.sha256((output / "manifest.json").read_bytes()).hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "check", "export"):
        sub = commands.add_parser(name)
        sub.add_argument("--output", type=Path, required=True)
        if name == "prepare":
            sub.add_argument("--project-root", type=Path, required=True)
            sub.add_argument("--source-root", type=Path, required=True)
            sub.add_argument("--cli", default=shutil.which("tsunagou") or "tsunagou")
        elif name == "check":
            sub.add_argument("--cli")
        else:
            sub.add_argument("--trace-file", type=Path)
    args = parser.parse_args()
    try:
        result = (
            prepare(args.output, args.project_root, args.source_root, args.cli)
            if args.command == "prepare"
            else check(args.output, args.cli)
            if args.command == "check"
            else export(args.output, args.trace_file)
        )
    except (OSError, ValueError, KeyError, TypeError):
        print(json.dumps({"status": "capture_error", "action": args.command}))
        raise SystemExit(2) from None
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if result["status"] == "incomplete":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
