from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from uuid import NAMESPACE_OID, uuid5

import pytest
from tools.dev import live_repair_acceptance as capture

PROJECT = "11111111-1111-4111-8111-111111111111"
MAIN = "22222222-2222-4222-8222-222222222222"
WORKER = "33333333-3333-4333-8333-333333333333"
TASK = "44444444-4444-4444-8444-444444444444"
ATTEMPT = "55555555-5555-4555-8555-555555555555"


def event(action: str, when: str | None, *, actor: str = WORKER) -> dict:
    return {
        "event_id": str(uuid5(NAMESPACE_OID, f"{action}/{when}/{actor}")),
        "action": action,
        "occurred_at": when,
        "recorded_at": when,
        "actor_ref": actor,
        "subject_ref": f"task/{TASK}",
        "event_seq": 1,
        "changes": [{"subject_ref": f"attempt/{ATTEMPT}", "state_after": "running"}],
        "actor_session_id": "SENTINEL-SESSION",
        "prompt": "SENTINEL-PROMPT",
    }


def setup_run(tmp_path: Path) -> tuple[Path, Path]:
    root, output = tmp_path / "project", tmp_path / "evidence"
    (root / ".tsunagou").mkdir(parents=True)
    capture.write_json(root / ".tsunagou/project.json", {"project_id": PROJECT})
    output.mkdir()
    (output / "spans.ndjson").write_text("original collector file", encoding="utf-8")
    capture.prepare(output, root, tmp_path / "source", "installed-tsunagou")
    return root, output


def timing() -> dict:
    return {
        "attempt_id": ATTEMPT, "task_id": TASK, "owner_agent_id": WORKER,
        "state": "completed", "started_at": "2026-09-28T04:01:00.000Z",
        "submitted_at": "2026-09-28T04:03:00.000Z", "reviewed_at": "2026-09-28T04:04:00.000Z",
        "started_source": "task_begin_event", "submitted_source": "result_created_at",
        "reviewed_source": "task_review_event", "begin_events": 1, "submit_events": 0,
        "review_action": "task.review.accept", "private_evidence": "SENTINEL-PRIVATE",
    }


def test_prepare_preserves_existing_trace_and_rejects_overwriting_a_run(tmp_path: Path) -> None:
    root, output = setup_run(tmp_path)
    assert (output / "spans.ndjson").read_text(encoding="utf-8") == "original collector file"
    assert all(item["status"] == "not_run" for item in capture.load(output / "review.json").values())
    assert capture.load(output / "manifest.json")["finished_at"] is None
    with pytest.raises(ValueError, match="run_already_prepared"):
        capture.prepare(output, root, tmp_path, "cli")


def test_check_queries_only_read_surfaces_and_does_not_certify_llm_work(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, output = setup_run(tmp_path)
    calls = []

    def read(cli, project, args):
        calls.append(args)
        assert cli == "installed-tsunagou" and project == root
        result = {"items": []}
        if args[0] == "installation-info":
            result = {
                "status": "installed",
                "source_root": str(tmp_path / "source"),
                "commit": "a" * 40,
                "install_started_at": "2026-09-28T12:00:00+08:00",
                "install_finished_at": "2026-09-28T04:00:04Z",
                "duration_ms": 4000,
                "token": "SENTINEL-TOKEN",
            }
        if args[:2] == ["agent", "list"]:
            result = {
                "items": [
                    {"agent_id": MAIN, "role": "main", "thread_id": "SENTINEL-THREAD"},
                    {"agent_id": WORKER, "role": "worker", "session_id": "SENTINEL-SESSION"},
                ]
            }
        if args[0] == "doctor":
            result = {"daemon": "reachable", "version": "0.1.0", "runtime": {"pipe": "SENTINEL-PIPE"}}
        if args[:2] == ["project", "history"]:
            result = {
                "project_id": PROJECT,
                "items": [
                    event("task.begin", "2026-09-28T04:01:00.000Z"),
                    event("task.submit", "2026-09-28T04:03:00.000Z"),
                    event("task.review.accept", "2026-09-28T04:04:00.000Z", actor=MAIN),
                ],
                "next_cursor": None,
            }
        if args[:2] == ["project", "diagnostics"]:
            result = {
                "project_id": PROJECT,
                "items": [
                    {
                        "kind": "wake_failed",
                        "agent_id": WORKER,
                        "error_code": "desktop_connection_lost",
                        "trigger_source": "daemon_delivery",
                        "summary": "SENTINEL-BODY",
                        "details": {"pipe": "SENTINEL-PIPE"},
                    }
                ],
            }
        if args[:2] == ["project", "timings"]:
            result = {"project_id": PROJECT, "items": [timing()]}
        return result, {"status": "ok", "observed_at": capture.now()}

    monkeypatch.setattr(capture, "query", read)
    assert capture.check(output)["status"] == "captured"
    assert len(calls) == 6
    result = capture.export(output)
    assert set(result["criteria"].values()) == {"not_run"}
    assert result["project_confirmation"] == "unverified"
    timeline = capture.load(output / "timeline.json")
    assert timeline["attempts"][0]["work_elapsed"]["elapsed_ms"] == 120000
    assert timeline["attempts"][0]["review_wait_elapsed"]["elapsed_ms"] == 60000
    assert timeline["attempts"][0]["submit_events"] == 0
    assert timeline["attempts"][0]["submitted_source"] == "result_created_at"
    assert timeline["diagnostics"][0]["kind"] == "wake_failed"
    assert timeline["diagnostics"][0]["error_code"] == "desktop_connection_lost"
    assert timeline["diagnostics"][0]["trigger_source"] == "daemon_delivery"
    for path in output.rglob("*.json"):
        assert "SENTINEL" not in path.read_text(encoding="utf-8")
    assert (output / "spans.ndjson").read_text(encoding="utf-8") == "original collector file"


def test_failed_cli_output_and_bad_pagination_are_not_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _root, output = setup_run(tmp_path)
    monkeypatch.setattr(
        capture.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess([], 3, "SENTINEL-STDOUT", "SENTINEL-STDERR")
    )
    assert capture.check(output)["status"] == "incomplete"
    assert "SENTINEL" not in "".join(path.read_text(encoding="utf-8") for path in output.rglob("*.json"))

    def repeating(cli, root, args):
        return {"items": [], "next_cursor": "same"}, {"status": "ok"}

    monkeypatch.setattr(capture, "query", repeating)
    assert capture.check(output)["status"] == "incomplete"
    assert len(list((output / "snapshots").iterdir())) == 2


def test_elapsed_unknown_or_negative_is_not_fabricated() -> None:
    assert capture.elapsed(None, capture.now())["elapsed_ms"] is None
    assert capture.elapsed("2026-09-28T00:01:00Z", "2026-09-28T00:00:00Z") == {
        "elapsed_ms": None,
        "clock_status": "clock_inconsistent",
    }


def test_export_requires_review_refs_and_filters_trace_payloads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _root, output = setup_run(tmp_path)

    def empty(cli, root, args):
        page = {"items": []}
        if args[:2] in (["project", "history"], ["project", "diagnostics"], ["project", "timings"]):
            page["project_id"] = PROJECT
        return page, {"status": "ok"}

    monkeypatch.setattr(capture, "query", empty)
    capture.check(output)
    review = capture.load(output / "review.json")
    review["A1"] = {"status": "pass", "observed_at": capture.now(), "evidence_refs": []}
    review["A2"] = {"status": "fail", "observed_at": capture.now(), "evidence_refs": ["timeline.json"], "body": "SENTINEL-BODY"}
    capture.write_json(output / "review.json", review)
    trace = tmp_path / "collector.ndjson"
    trace.write_text(
        json.dumps(
            {
                "name": "host.wake",
                "trace_id": "a" * 32,
                "span_id": "b" * 16,
                "started_at": "2026-09-28T01:00:00Z",
                "finished_at": "2026-09-28T01:00:01Z",
                "prompt": "SENTINEL-PROMPT",
                "attributes": {
                    "tsunagou.project_id": PROJECT,
                    "tsunagou.agent_id": WORKER,
                    "raw_thread_id": "SENTINEL-THREAD",
                    "secret_token": "SENTINEL-TOKEN",
                },
            }
        )
        + "\npartial",
        encoding="utf-8",
    )
    result = capture.export(output, trace)
    assert result["criteria"]["A1"] == "not_run" and result["criteria"]["A2"] == "fail"
    saved = (output / "trace.json").read_text(encoding="utf-8")
    assert "SENTINEL" not in saved and capture.load(output / "trace.json")["ignored_lines"] == 1
    assert "SENTINEL" not in (output / "manifest.json").read_text(encoding="utf-8")
    assert "SENTINEL" not in (output / "summary.md").read_text(encoding="utf-8")


def test_doctor_uses_global_json_and_does_not_store_cli_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def run(args, **kwargs):
        assert args == ["installed", "--project-root", str(tmp_path), "--json", "doctor"]
        assert kwargs["cwd"] == tmp_path
        return subprocess.CompletedProcess(args, 0, '{"daemon":"reachable"}', "SENTINEL-ERROR")

    monkeypatch.setattr(capture.subprocess, "run", run)
    result, status = capture.query("installed", tmp_path, ["doctor"])
    assert result == {"daemon": "reachable"}
    assert status["status"] == "ok" and status["duration_ms"] >= 0
    assert status["observed_at"].endswith("Z") and status["finished_at"].endswith("Z")


def test_timing_capture_preserves_sources_without_fabricating_events() -> None:
    source = timing()
    source["work_elapsed"] = {"elapsed_ms": 999999, "clock_status": "ok"}
    row = capture.public_timing(source)
    assert row["submitted_source"] == "result_created_at" and row["submit_events"] == 0
    assert row["work_elapsed"]["elapsed_ms"] == 120000
    assert "SENTINEL" not in json.dumps(row)
    unknown = capture.public_timing({**source, "submitted_source": "review_guess"})
    assert unknown["submitted_at"] is None and unknown["work_elapsed"]["clock_status"] == "unknown"
    bad_source = capture.public_timing({**source, "submitted_source": {"secret": "SENTINEL"}})
    assert bad_source["submitted_at"] is None
    reversed_clock = capture.public_timing({**source, "submitted_at": "2026-09-28T04:00:00Z"})
    assert reversed_clock["work_elapsed"] == {"elapsed_ms": None, "clock_status": "clock_inconsistent"}


def test_check_follows_pages_and_rejects_wrong_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _root, output = setup_run(tmp_path)
    calls = []

    def pages(cli, root, args):
        calls.append(args)
        result = {"items": []}
        if args[:2] == ["project", "history"]:
            if "--cursor" not in args:
                result = {"project_id": PROJECT, "items": [event("task.begin", "2026-09-28T01:00:00Z")], "next_cursor": "opaque"}
            else:
                result = {"project_id": PROJECT, "items": [event("task.submit", "2026-09-28T01:01:00Z")], "next_cursor": None}
        elif args[:2] in (["project", "diagnostics"], ["project", "timings"]):
            result["project_id"] = PROJECT
        return result, {"status": "ok"}

    monkeypatch.setattr(capture, "query", pages)
    assert capture.check(output)["status"] == "captured"
    assert calls[-1][-2:] == ["--cursor", "opaque"]
    capture.export(output)
    assert len(capture.load(output / "timeline.json")["events"]) == 2
    monkeypatch.setattr(capture, "query", lambda *args: ({"project_id": MAIN, "items": []}, {"status": "ok"}))
    assert capture.check(output)["status"] == "incomplete"
    monkeypatch.setattr(capture, "query", lambda *args: ({"items": "SENTINEL"}, {"status": "ok"}))
    assert capture.check(output)["status"] == "incomplete"


def test_export_allowlists_manifest_and_requires_local_observed_review(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _root, output = setup_run(tmp_path)

    def empty(cli, root, args):
        page = {"items": []}
        if args[:2] in (["project", "history"], ["project", "diagnostics"], ["project", "timings"]):
            page["project_id"] = PROJECT
        return page, {"status": "ok"}

    monkeypatch.setattr(capture, "query", empty)
    capture.check(output)
    manifest = capture.load(output / "manifest.json")
    manifest.update(
        token="SENTINEL-TOKEN",
        installation={"private_session": "SENTINEL-SESSION"},
        host_versions={"codex_app": "1.2.3", "pipe": "SENTINEL-PIPE"},
    )
    capture.write_json(output / "manifest.json", manifest)
    (tmp_path / "outside.json").write_text("{}", encoding="utf-8")
    review = capture.load(output / "review.json")
    review["A1"] = {"status": "pass", "observed_at": "2026-09-28T03:00:00+03:00", "evidence_refs": ["timeline.json"]}
    review["A2"] = {"status": "pass", "observed_at": capture.now(), "evidence_refs": ["../outside.json", "missing.json"]}
    review["A3"] = {"status": "pass", "observed_at": "2026-09-28T03:00:00", "evidence_refs": ["timeline.json"]}
    capture.write_json(output / "review.json", review)
    exported = capture.export(output)
    assert exported["criteria"]["A1"] == "pass"
    assert exported["criteria"]["A2"] == exported["criteria"]["A3"] == "not_run"
    manifest = capture.load(output / "manifest.json")
    assert manifest["criteria"]["A1"]["source"] == "operator_review_not_script_verification"
    assert manifest["criteria"]["A1"]["observed_at"] == "2026-09-28T00:00:00.000Z"
    assert "SENTINEL" not in json.dumps(manifest)
    assert manifest["host_versions"]["codex_app"] == "1.2.3"
    with pytest.raises(ValueError, match="trace_input_overwrite"):
        capture.export(output, output / "trace.json")


@pytest.mark.parametrize(
    "actor,subject,outcome,expected",
    [
        ("user_control", f"project/{PROJECT}", "committed", "recorded_user_confirmation"),
        (MAIN, f"project/{PROJECT}", "committed", "unverified"),
        ("user_control", f"project/{MAIN}", "committed", "unverified"),
        ("user_control", f"project/{PROJECT}", "failed", "unverified"),
    ],
)
def test_user_confirmation_is_a_separate_project_fact(tmp_path, monkeypatch, actor, subject, outcome, expected) -> None:
    _root, output = setup_run(tmp_path)
    confirmation = event("project.completion.confirm", capture.now(), actor=actor)
    confirmation.update(subject_ref=subject, outcome=outcome)

    def query(cli, root, args):
        page = {"items": [confirmation] if args[:2] == ["project", "history"] else []}
        if args[:2] in (["project", "history"], ["project", "diagnostics"], ["project", "timings"]):
            page["project_id"] = PROJECT
        return page, {"status": "ok"}

    monkeypatch.setattr(capture, "query", query)
    capture.check(output)
    result = capture.export(output)
    assert result["project_confirmation"] == expected
    assert set(result["criteria"].values()) == {"not_run"}


def test_actual_otlp_collector_shape_survives_allowlist() -> None:
    from tools.dev.collect_acceptance_trace import decode_spans

    proto = pytest.importorskip("opentelemetry.proto.collector.trace.v1.trace_service_pb2")
    request = proto.ExportTraceServiceRequest()
    span = request.resource_spans.add().scope_spans.add().spans.add()
    span.name = "host.wake"
    span.trace_id, span.span_id = bytes.fromhex("a" * 32), bytes.fromhex("b" * 16)
    span.start_time_unix_nano, span.end_time_unix_nano = 1790550000000000000, 1790550000123456000
    for key, value in {
        "project_id": PROJECT,
        "agent_id": WORKER,
        "actor_id": MAIN,
        "command_kind": "message.send",
        "trigger_source": "daemon_delivery",
        "private_thread_id": "SENTINEL",
    }.items():
        attr = span.attributes.add()
        attr.key, attr.value.string_value = f"tsunagou.{key}", value
    decoded = decode_spans(request.SerializeToString())[0]
    safe = capture.public_span(decoded, PROJECT)
    assert safe["duration_ms"] == 123.456
    assert safe["attributes"]["tsunagou.trigger_source"] == "daemon_delivery"
    assert safe["attributes"]["tsunagou.actor_id"] == MAIN
    assert "SENTINEL" not in json.dumps(safe)
    assert capture.public_span({**decoded, "trace_id": "0" * 32}, PROJECT) is None
    assert capture.public_span({**decoded, "started_at": None}, PROJECT) is None
    assert capture.public_span({**decoded, "name": "unregistered.span"}, PROJECT) is None
    assert capture.public_span({**decoded, "attributes": {}}, PROJECT) is None


def test_prepare_cli_runs_without_a_daemon(tmp_path: Path) -> None:
    script = Path(capture.__file__)
    process = subprocess.run(
        [
            sys.executable,
            str(script),
            "prepare",
            "--output",
            str(tmp_path / "run"),
            "--project-root",
            str(tmp_path),
            "--source-root",
            str(script.parents[2]),
            "--cli",
            "unused",
        ],
        capture_output=True,
        text=True,
    )
    assert process.returncode == 0
    assert json.loads(process.stdout)["status"] == "prepared"
