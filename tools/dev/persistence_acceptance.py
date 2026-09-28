"""Run the non-destructive PT1-PT7 acceptance gates and write a trace report.

The script only uses the repository and disposable audit projects. It never
opens a user-selected state directory, revokes credentials, or confirms a
restore plan. Use the standalone audit report as the runtime evidence source.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
COREPACK = "corepack.cmd" if os.name == "nt" else "corepack"


def timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def run_gate(command: list[str]) -> dict[str, Any]:
    try:
        process = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    except OSError as exc:
        return {
            "command": " ".join(command),
            "exit_code": 127,
            "passed": False,
            "last_output": [f"unable to start command: {exc}"],
        }
    output = (process.stdout + process.stderr).strip().splitlines()
    return {
        "command": " ".join(command),
        "exit_code": process.returncode,
        "passed": process.returncode == 0,
        "last_output": output[-3:] if output else [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-report", type=Path, help="Existing tools/dev/audit_standalone.py JSON report")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--skip-node", action="store_true", help="Skip optional pnpm build/check gates")
    args = parser.parse_args()

    started_at = timestamp()
    from tsunagou import __version__

    report: dict[str, Any] = {
        "report_kind": "tsunagou.persistence-acceptance.v1",
        "started_at": started_at,
        "finished_at": None,
        "repository": str(ROOT),
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "daemon_version": __version__,
        "schema_bundle_digest": json.loads((ROOT / "protocol/registry/commands.json").read_text(encoding="utf-8"))["schema_bundle_digest"],
        "real_project_touched": False,
        "credential_migration_or_restore_confirmed": False,
        "working_tree_dirty": bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            ).stdout.strip()
        ),
        "gates": [],
        "runtime_audit": None,
    }

    audit_report = args.audit_report
    temporary_audit: tempfile.TemporaryDirectory[str] | None = None
    try:
        if audit_report is None:
            temporary_audit = tempfile.TemporaryDirectory(prefix="tsunagou-acceptance-")
            audit_report = Path(temporary_audit.name) / "audit.json"
            audit_gate = run_gate([sys.executable, "tools/dev/audit_standalone.py", "--output", str(audit_report)])
            report["gates"].append(audit_gate)
        if audit_report.is_file():
            runtime = json.loads(audit_report.read_text(encoding="utf-8"))
            report["runtime_audit"] = {
                "source": str(audit_report),
                "passed": runtime.get("failed") == 0,
                "passed_checks": runtime.get("passed"),
                "failed_checks": runtime.get("failed"),
                "a2a_passed": runtime.get("a2a_passed"),
                "a2a_failed": runtime.get("a2a_failed"),
            }
        else:
            report["runtime_audit"] = {"source": str(audit_report), "passed": False, "error": "audit_report_missing"}

        gates = [
            [sys.executable, "tools/codegen/generate_openapi.py"],
            [sys.executable, "tools/codegen/generate_audit.py"],
            [sys.executable, "tools/codegen/validate_protocol.py"],
            [sys.executable, "tools/dev/check_architecture.py"],
            [sys.executable, "-m", "ruff", "check", "src", "tests", "tools"],
            [sys.executable, "-m", "mypy", "src"],
            [sys.executable, "-m", "pytest", "-q", "--disable-warnings"],
            [sys.executable, "tools/docs/validate_docs.py"],
        ]
        if not args.skip_node:
            gates.extend(
                [
                    [COREPACK, "pnpm", "-r", "--if-present", "run", "build"],
                    [COREPACK, "pnpm", "check"],
                ]
            )
        for gate in gates:
            result = run_gate(gate)
            report["gates"].append(result)
            if not result["passed"]:
                break
    finally:
        report["finished_at"] = timestamp()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if temporary_audit is not None:
            temporary_audit.cleanup()

    passed = bool(report["runtime_audit"] and report["runtime_audit"].get("passed")) and all(gate["passed"] for gate in report["gates"])
    print(json.dumps({"passed": passed, "report": str(args.output), "gates": len(report["gates"])}, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
