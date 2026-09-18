from tsunagou.modules.evaluation import (
    AuditProjector,
    EvaluationLedger,
    ExperimentDefinition,
    new_result,
    new_run,
    redact_for_export,
    token_sample,
)


def definition() -> ExperimentDefinition:
    return ExperimentDefinition(
        name="coordination", version="1", task_set_digest="sha256:tasks", arms=("A", "C"),
        budget_policy={"max": 10}, host_model_matrix=({"host": "simulator", "model": "test"},),
        random_seed=7, metrics=("correctness", "latency", "tokens"), success_criteria={"correctness": 1},
    )


def test_audit_is_read_only_and_filters_private_subject() -> None:
    event = {
        "event_id": "e", "event_seq": 1, "actor_ref": "agent",
        "action": "message.send", "subject_ref": "private", "body": "secret-sentinel",
    }
    view = AuditProjector().project(event, can_read_subject=False)
    assert view.subject_ref == "[REDACTED]"
    assert event["body"] == "secret-sentinel"


def test_experiment_digest_and_unavailable_usage_are_deterministic() -> None:
    first = definition()
    second = definition()
    assert first.digest == second.digest
    ledger = EvaluationLedger()
    run = new_run(
        first, arm="C", replicate=0, host_version="sim", adapter_version="a",
        model_version="m", protocol_digest="p", config_digest="c",
    )
    ledger.record_run(run)
    result = new_result(run, correctness=1, interventions=2, rework=0, wall_time=3, token_metrics=(token_sample(None),))
    ledger.record_result(result)
    report = ledger.report(first)
    assert report.sample_count == 1
    assert "token_usage_unavailable_for_some_samples" in report.limitations
    assert token_sample(None).value is None


def test_secret_redaction_applies_to_exports() -> None:
    exported = redact_for_export({"api_key": "secret-sentinel", "body": "secret-sentinel"})
    assert exported == {"api_key": "[REDACTED]", "body": "[REDACTED]"}
