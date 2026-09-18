from __future__ import annotations

import json
from pathlib import Path

from tsunagou.application.release_gates import (
    evaluate_host_matrix,
    evaluate_static_release,
    load_host_evidence,
    missing_baseline_capabilities,
)


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    report = evaluate_static_release(root)
    matrix = load_host_evidence(root)
    missing = {
        host: missing_baseline_capabilities(matrix.get(host, {}))
        for host in ("codex", "opencode", "zcode", "deepseek")
        if missing_baseline_capabilities(matrix.get(host, {}))
    }
    if evaluate_host_matrix(matrix).failures != tuple(report.failures):
        raise RuntimeError("release_gate_diagnostic_drift")
    payload = {"passed": report.passed, "failures": report.failures, "missing_capabilities": missing}
    print(json.dumps(payload, ensure_ascii=True, sort_keys=True))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
