"""Read-only audit projections and deterministic local experiment records."""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from statistics import mean, median
from typing import Any, Literal

from tsunagou.shared_kernel.digests import canonical_digest
from tsunagou.shared_kernel.ids import new_id

Availability = Literal["observed", "estimated", "unavailable"]
DEFAULT_EXPERIMENT_ARMS = ("A", "B", "C", "D")
_SECRET_KEY = re.compile(r"(?:token|secret|password|authorization|ticket|api[_-]?key)", re.IGNORECASE)
_SECRET_SENTINEL = re.compile(r"(?:sk-[A-Za-z0-9_-]{8,}|secret[_-]?sentinel|bearer\s+\S+)", re.IGNORECASE)


class SecretRedactor:
    """Redacts secret-shaped keys and values before logs, exports, or errors."""

    replacement = "[REDACTED]"

    def text(self, value: str) -> str:
        return _SECRET_SENTINEL.sub(self.replacement, value)

    def value(self, value: object) -> object:
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, Mapping):
            return {
                str(key): self.replacement if _SECRET_KEY.search(str(key)) else self.value(item)
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [self.value(item) for item in value]
        return value


@dataclass(frozen=True, slots=True)
class AuditView:
    source_event_id: str
    source_event_seq: int
    actor_ref: str
    action: str
    subject_ref: str
    outcome: str
    reason_code: str | None
    evidence_refs: tuple[str, ...]
    projection_version: str = "v1"


class AuditProjector:
    """Projects registered fields without mutating or exposing event payloads."""

    def __init__(self) -> None:
        self._redactor = SecretRedactor()

    def project(self, event: Mapping[str, Any], *, can_read_subject: bool) -> AuditView:
        subject = str(event.get("subject_ref", "unknown")) if can_read_subject else "[REDACTED]"
        evidence = event.get("evidence_refs", ())
        refs = tuple(self._redactor.text(str(item)) for item in evidence) if isinstance(evidence, (list, tuple)) else ()
        return AuditView(
            source_event_id=str(event.get("event_id", "unknown")),
            source_event_seq=int(event.get("event_seq", 0)),
            actor_ref=str(event.get("actor_ref", "unknown")),
            action=str(event.get("action", "unknown")),
            subject_ref=subject,
            outcome=str(event.get("outcome", "unknown")),
            reason_code=str(event["reason_code"]) if event.get("reason_code") is not None else None,
            evidence_refs=refs,
        )


@dataclass(frozen=True, slots=True)
class MetricSample:
    name: str
    unit: str
    value: float | None
    availability: Availability
    labels: Mapping[str, str] = field(default_factory=dict)
    source_ref: str | None = None


def token_sample(value: int | float | None, *, source_ref: str | None = None) -> MetricSample:
    if value is None:
        return MetricSample("tokens", "tokens", None, "unavailable", source_ref=source_ref)
    return MetricSample("tokens", "tokens", float(value), "observed", source_ref=source_ref)


@dataclass(frozen=True, slots=True)
class ExperimentDefinition:
    name: str
    version: str
    task_set_digest: str
    arms: tuple[str, ...]
    budget_policy: Mapping[str, Any]
    host_model_matrix: tuple[Mapping[str, str], ...]
    random_seed: int
    metrics: tuple[str, ...]
    success_criteria: Mapping[str, Any]
    digest: str = ""

    def __post_init__(self) -> None:
        if not self.arms or not self.metrics:
            raise ValueError("experiment_requires_arms_and_metrics")
        body = {
            "name": self.name, "version": self.version, "task_set_digest": self.task_set_digest,
            "arms": self.arms, "budget_policy": self.budget_policy,
            "host_model_matrix": self.host_model_matrix, "random_seed": self.random_seed,
            "metrics": self.metrics, "success_criteria": self.success_criteria,
        }
        object.__setattr__(self, "digest", canonical_digest(body))


@dataclass(frozen=True, slots=True)
class ExperimentRun:
    run_id: str
    definition_digest: str
    arm: str
    replicate: int
    host_version: str
    adapter_version: str
    model_version: str
    protocol_digest: str
    config_digest: str
    status: str = "running"
    result_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ExperimentResult:
    result_id: str
    run_id: str
    correctness: float | None
    interventions: int | None
    rework: int | None
    wall_time: float | None
    token_metrics: tuple[MetricSample, ...]
    failures: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    digest: str = ""

    def __post_init__(self) -> None:
        body = {
            "run_id": self.run_id, "correctness": self.correctness,
            "interventions": self.interventions, "rework": self.rework,
            "wall_time": self.wall_time, "token_metrics": [asdict(sample) for sample in self.token_metrics],
            "failures": self.failures, "evidence_refs": self.evidence_refs,
        }
        object.__setattr__(self, "digest", canonical_digest(body))


@dataclass(frozen=True, slots=True)
class ExperimentReport:
    report_id: str
    definition_digest: str
    sample_count: int
    failed_count: int
    statistics: Mapping[str, float | None]
    limitations: tuple[str, ...]
    result_refs: tuple[str, ...]
    digest: str


class EvaluationLedger:
    """Append-only evaluation store; it has no mutation port for business entities."""

    def __init__(self) -> None:
        self.audit_views: list[AuditView] = []
        self.metric_samples: list[MetricSample] = []
        self.runs: dict[str, ExperimentRun] = {}
        self.results: dict[str, ExperimentResult] = {}

    def record_audit(self, view: AuditView) -> AuditView:
        self.audit_views.append(view)
        return view

    def record_run(self, run: ExperimentRun) -> ExperimentRun:
        if run.run_id in self.runs:
            raise ValueError("duplicate_experiment_run")
        self.runs[run.run_id] = run
        return run

    def record_result(self, result: ExperimentResult) -> ExperimentResult:
        if result.result_id in self.results:
            raise ValueError("duplicate_experiment_result")
        if result.run_id not in self.runs:
            raise ValueError("unknown_experiment_run")
        self.results[result.result_id] = result
        self.metric_samples.extend(result.token_metrics)
        return result

    def report(self, definition: ExperimentDefinition) -> ExperimentReport:
        runs = [run for run in self.runs.values() if run.definition_digest == definition.digest]
        run_ids = {run.run_id for run in runs}
        results = [result for result in self.results.values() if result.run_id in run_ids]
        correctness = [result.correctness for result in results if result.correctness is not None]
        latencies = [result.wall_time for result in results if result.wall_time is not None]
        failed = sum(1 for result in results if result.failures or self.runs[result.run_id].status == "failed")
        limitations: list[str] = []
        if len(correctness) != len(results):
            limitations.append("correctness_missing_for_some_samples")
        if any(sample.availability == "unavailable" for result in results for sample in result.token_metrics):
            limitations.append("token_usage_unavailable_for_some_samples")
        statistics: dict[str, float | None] = {
            "correctness_mean": mean(correctness) if correctness else None,
            "latency_median": median(latencies) if latencies else None,
        }
        refs = tuple(sorted(result.result_id for result in results))
        body = {
            "definition_digest": definition.digest, "sample_count": len(results),
            "failed_count": failed, "statistics": statistics, "limitations": limitations,
            "result_refs": refs,
        }
        return ExperimentReport(
            new_id(), definition.digest, len(results), failed, statistics,
            tuple(limitations), refs, canonical_digest(body),
        )


def new_run(
    definition: ExperimentDefinition, *, arm: str, replicate: int,
    host_version: str, adapter_version: str, model_version: str,
    protocol_digest: str, config_digest: str,
) -> ExperimentRun:
    if arm not in definition.arms or replicate < 0:
        raise ValueError("invalid_experiment_run")
    return ExperimentRun(
        new_id(), definition.digest, arm, replicate, host_version,
        adapter_version, model_version, protocol_digest, config_digest,
    )


def new_result(
    run: ExperimentRun, *, correctness: float | None, interventions: int | None,
    rework: int | None, wall_time: float | None,
    token_metrics: tuple[MetricSample, ...], failures: tuple[str, ...] = (),
    evidence_refs: tuple[str, ...] = (),
) -> ExperimentResult:
    return ExperimentResult(new_id(), run.run_id, correctness, interventions, rework, wall_time, token_metrics, failures, evidence_refs)


def redact_for_export(value: object) -> object:
    return SecretRedactor().value(copy.deepcopy(value))
