"""Record PT2 checks with observed UTC times, exit codes and source hashes."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
REPORT = Path(__file__).with_name("verification.json")


def timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def main() -> int:
    corepack = "corepack.cmd" if os.name == "nt" else "corepack"
    uv = "uv"
    checks = [
        [uv, "run", "ruff", "check", "src", "tests", "tools"],
        [uv, "run", "mypy", "src"],
        [uv, "run", "pytest", "-q", "--disable-warnings"],
        [corepack, "pnpm", "run", "check"],
        [corepack, "pnpm", "--filter", "@tsunagou/bridge-server", "run", "test:credentials"],
        [uv, "run", "python", "tools/dev/smoke_standalone.py", "--skip-build"],
        [uv, "run", "python", "tools/codegen/validate_protocol.py"],
        [uv, "run", "python", "tools/dev/check_architecture.py"],
        [uv, "run", "python", "tools/docs/validate_docs.py"],
        [uv, "run", "python", ".trellis/scripts/task.py", "validate", ".trellis/tasks/09-27-trace-secret-receipts"],
        ["git", "diff", "--check"],
    ]
    report = {
        "task": "PT2", "status": "running", "started_at": timestamp(),
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip(),
        "working_tree_uncommitted": True, "real_user_project_modified": False, "checks": [],
    }
    for command in checks:
        started = timestamp()
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
        combined = result.stdout + result.stderr
        item = {"command": command, "started_at": started, "finished_at": timestamp(),
                "exit_code": result.returncode, "output": combined,
                "output_digest": "sha256:" + hashlib.sha256(combined.encode()).hexdigest()}
        report["checks"].append(item)
        report.update(status="running" if result.returncode == 0 else "failed", updated_at=timestamp())
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"command": command, "exit_code": result.returncode, "finished_at": item["finished_at"]}), flush=True)
        if result.returncode:
            print(combined, flush=True)
            return result.returncode
    files = [
        "src/tsunagou/platform/delivery.py", "src/tsunagou/platform/private_files.py",
        "src/tsunagou/platform/credential_migration.py", "src/tsunagou/platform/db/sqlite.py",
        "src/tsunagou/api/auth.py", "src/tsunagou/api/app.py", "src/tsunagou/interfaces/runtime.py",
        "src/tsunagou/bootstrap/container.py", "src/tsunagou/cli/app.py",
        "src/tsunagou/modules/workspaces.py",
        "packages/bridge-server/src/server.ts", "packages/bridge-server/src/credential-handoff.ts",
        "packages/bridge-server/src/private-file.ts", "packages/bridge-server/src/private-file-lock.ts",
        "src/tsunagou/platform/private_file_lock.py",
        "protocol/schemas/queries/credential-delivery.schema.json",
    ]
    report.update(status="passed", finished_at=timestamp(), source_digests={
        name: "sha256:" + hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in files
    })
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
