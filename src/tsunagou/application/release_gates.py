"""Release gates that keep simulator evidence separate from live-host support."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tsunagou.shared_kernel.baseline import (
    BASELINE_CAPABILITIES as BASELINE_CAPABILITIES,
)
from tsunagou.shared_kernel.baseline import (
    missing_baseline_capabilities as missing_baseline_capabilities,
)

# ZCode remains an implemented/diagnostic adapter, but is deferred from the
# first release gate until an official host and a reproducible baseline exist.
REQUIRED_HOSTS = ("codex", "opencode", "deepseek")
OPTIONAL_HOSTS = ("zcode",)
KNOWN_HOSTS = REQUIRED_HOSTS + OPTIONAL_HOSTS


@dataclass(frozen=True, slots=True)
class GateReport:
    passed: bool
    failures: tuple[str, ...]


def require_live_baseline(evidence: Mapping[str, Any]) -> bool:
    return not missing_baseline_capabilities(evidence)


def evaluate_host_matrix(matrix: Mapping[str, Mapping[str, Any]]) -> GateReport:
    failures = tuple(
        f"{host}:live_baseline_missing"
        for host in REQUIRED_HOSTS
        if not require_live_baseline(matrix.get(host, {}))
    )
    return GateReport(not failures, failures)


def load_host_evidence(root: Path) -> dict[str, Mapping[str, Any]]:
    evidence_dir = root / "docs" / "research" / "evidence"
    result: dict[str, Mapping[str, Any]] = {}
    # Optional hosts are intentionally not loaded by the first-release gate;
    # malformed or missing post-release evidence must not block required hosts.
    for host in REQUIRED_HOSTS:
        candidates = sorted(evidence_dir.glob(f"{host}-*.json"))
        if candidates:
            value = json.loads(candidates[-1].read_text(encoding="utf-8"))
            if isinstance(value, dict):
                result[host] = value
    return result


def evaluate_static_release(root: Path) -> GateReport:
    failures: list[str] = []
    for relative in ("protocol/openapi.json", "protocol/registry/commands.json", "docs/research/host-matrix.md"):
        if not (root / relative).is_file():
            failures.append(f"missing:{relative}")
    failures.extend(evaluate_host_matrix(load_host_evidence(root)).failures)
    return GateReport(not failures, tuple(failures))
