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


def test_report_statistics_cover_every_metric_the_definition_promises() -> None:
    """干预与返工的中位数是 C-vs-B 门槛的原料；缺样本时只报 limitation，不填 0."""

    ledger = EvaluationLedger()
    definition_ = definition()
    run = new_run(
        definition_, arm="C", replicate=0, host_version="sim", adapter_version="a",
        model_version="m", protocol_digest="p", config_digest="c",
    )
    ledger.record_run(run)
    ledger.record_result(new_result(run, correctness=1, interventions=4, rework=1, wall_time=3, token_metrics=()))
    ledger.record_result(new_result(run, correctness=1, interventions=2, rework=3, wall_time=5, token_metrics=()))
    report = ledger.report(definition_)
    assert report.statistics["interventions_median"] == 3
    assert report.statistics["rework_median"] == 2
    assert "interventions_missing_for_some_samples" not in report.limitations

    unmeasured = new_run(
        definition_, arm="A", replicate=0, host_version="sim", adapter_version="a",
        model_version="m", protocol_digest="p", config_digest="c",
    )
    ledger.record_run(unmeasured)
    ledger.record_result(new_result(unmeasured, correctness=1, interventions=None, rework=None, wall_time=1, token_metrics=()))
    mixed = ledger.report(definition_)
    assert mixed.statistics["interventions_median"] == 3, "缺样本的那次不能拉低中位数"
    assert "interventions_missing_for_some_samples" in mixed.limitations
    assert "rework_missing_for_some_samples" in mixed.limitations


def test_report_groups_statistics_by_arm_and_rates_injected_discrepancies() -> None:
    """门槛是跨臂比较（C 对 B），所以统计量必须能按臂取；检出率只在两侧都测过的样本上算。"""

    ledger = EvaluationLedger()
    definition_ = definition()  # arms ("A", "C")
    run_a = new_run(definition_, arm="A", replicate=0, host_version="sim", adapter_version="a",
                    model_version="m", protocol_digest="p", config_digest="c")
    run_c = new_run(definition_, arm="C", replicate=0, host_version="sim", adapter_version="a",
                    model_version="m", protocol_digest="p", config_digest="c")
    ledger.record_run(run_a)
    ledger.record_run(run_c)
    # A 那一次没测干预、也没测分歧计数；C 那一次注入了 4 条、检出 3 条。
    ledger.record_result(new_result(run_a, correctness=1, interventions=None, rework=None,
                                    wall_time=1, token_metrics=()))
    ledger.record_result(new_result(run_c, correctness=1, interventions=6, rework=1, wall_time=2,
                                    token_metrics=(), hard_discrepancies_injected=4,
                                    hard_discrepancies_detected=3,
                                    blocks_recorded=20, false_blocks=1))
    report = ledger.report(definition_)

    assert report.by_arm["C"]["interventions_median"] == 6
    assert report.by_arm["A"]["interventions_median"] is None, "没测过就是 None，不能填 0"
    assert report.by_arm["C"]["hard_discrepancy_detection_rate"] == 0.75
    assert report.by_arm["A"]["hard_discrepancy_detection_rate"] is None
    assert report.by_arm["C"]["false_blocking_rate"] == 0.05
    assert report.by_arm["A"]["false_blocking_rate"] is None
    # 混合臂的整定义统计量仍在（statistics），但门槛判断要看 by_arm。
    assert set(report.by_arm) == {"A", "C"}
    assert "hard_discrepancy_counts_missing_for_some_samples" in report.limitations
    assert "false_blocking_counts_missing_for_some_samples" in report.limitations
