"""Prepare a reproducible A/B/C/D experiment plan without fabricating results."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tsunagou.modules.evaluation import DEFAULT_EXPERIMENT_ARMS, ExperimentDefinition, new_run


def build_plan(*, replicates: int = 5) -> dict[str, object]:
    if replicates < 1:
        raise ValueError("replicates_must_be_positive")
    definition = ExperimentDefinition(
        name="tsunagou-coordination-effect",
        version="1",
        task_set_digest="sha256:REPLACE_WITH_LOCKED_TASK_SET",
        arms=DEFAULT_EXPERIMENT_ARMS,
        budget_policy={"replicates_per_arm": replicates, "same_budget": True},
        host_model_matrix=({"host": "LOCK_BEFORE_RUN", "model": "LOCK_BEFORE_RUN"},),
        random_seed=20260918,
        metrics=("correctness", "hard_discrepancy_detection", "false_blocking", "interventions", "rework", "wall_time", "tokens"),
        success_criteria={
            "correctness": 1.0, "hard_discrepancy_detection": 0.95,
            "false_blocking_max": 0.05, "c_vs_b_intervention_reduction": 0.30,
            "c_vs_b_wall_time_increase_max": 0.10,
            "c_vs_b_comparable_token_increase_max": 0.25,
        },
    )
    runs = []
    for arm in definition.arms:
        for replicate in range(replicates):
            run = new_run(
                definition, arm=arm, replicate=replicate,
                host_version="LOCK_BEFORE_RUN", adapter_version="LOCK_BEFORE_RUN",
                model_version="LOCK_BEFORE_RUN", protocol_digest="LOCK_BEFORE_RUN",
                config_digest="LOCK_BEFORE_RUN",
            )
            runs.append({"run_id": run.run_id, "arm": run.arm, "replicate": run.replicate, "status": "planned"})
    return {
        "status": "planned_no_results",
        "definition": {
            "digest": definition.digest, "name": definition.name,
            "version": definition.version, "arms": definition.arms,
            "random_seed": definition.random_seed, "metrics": definition.metrics,
            "success_criteria": definition.success_criteria,
        },
        "runs": runs,
        "limitations": ["no host/model versions locked", "no measured results", "no effect claim"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replicates", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(build_plan(replicates=args.replicates), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
