from pathlib import Path

from tsunagou.application.release_gates import (
    BASELINE_CAPABILITIES,
    evaluate_host_matrix,
    evaluate_static_release,
    missing_baseline_capabilities,
)


def complete_host() -> dict[str, object]:
    baseline = {
        name: {"status": "supported", "evidence_refs": [f"e-{index}"]}
        for index, name in enumerate(BASELINE_CAPABILITIES)
    }
    return {"baseline": baseline}


def test_live_host_gate_requires_all_three_first_release_hosts() -> None:
    report = evaluate_host_matrix({"codex": complete_host()})
    assert report.passed is False
    assert "opencode:live_baseline_missing" in report.failures


def test_zcode_is_optional_for_first_release_gate() -> None:
    matrix = {host: complete_host() for host in ("codex", "opencode", "deepseek")}
    matrix["zcode"] = {}
    assert evaluate_host_matrix(matrix).passed is True


def test_static_gate_does_not_promote_current_unknown_matrix() -> None:
    report = evaluate_static_release(Path(__file__).parents[2])
    assert report.passed is False
    assert any(failure.endswith("live_baseline_missing") for failure in report.failures)


def test_missing_baseline_diagnostic_names_each_unproven_row() -> None:
    evidence = {"baseline": {"identity.session_isolation": {"status": "supported", "evidence_refs": ["e"]}}}
    missing = missing_baseline_capabilities(evidence)
    assert "identity.session_isolation" not in missing
    assert "delivery.deduplicate" in missing
    assert len(missing) == len(BASELINE_CAPABILITIES) - 1
