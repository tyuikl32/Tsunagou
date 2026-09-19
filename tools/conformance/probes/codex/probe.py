"""Probe only new disposable app-server threads; never read the user's Codex home."""

from __future__ import annotations

import argparse
import json
import os
import queue
import secrets
import shutil
import subprocess
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from tools.conformance.probes.common import BASELINE, IdentityEvidence, write_evidence


class Rpc:
    def __init__(self, executable: str, root: Path) -> None:
        env = {key: value for key, value in os.environ.items()
               if not any(term in key.upper() for term in ("TOKEN", "KEY", "SECRET", "AUTH"))}
        env["CODEX_HOME"] = str(root / "codex-home")
        self.process = subprocess.Popen(
            [executable, "app-server", "--stdio"], cwd=root, env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
        )
        self.lines: queue.Queue[str] = queue.Queue()
        self.sequence = 0
        self.stderr: list[str] = []
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=self._errors, daemon=True).start()

    def _read(self) -> None:
        assert self.process.stdout
        for line in self.process.stdout:
            self.lines.put(line)

    def _errors(self) -> None:
        assert self.process.stderr
        for line in self.process.stderr:
            self.stderr.append(line)

    def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.sequence += 1
        assert self.process.stdin
        self.process.stdin.write(json.dumps({"id": self.sequence, "method": method, "params": params}) + "\n")
        self.process.stdin.flush()
        while True:
            message = json.loads(self.lines.get(timeout=30))
            if message.get("id") == self.sequence:
                return cast(dict[str, Any], message)

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)


@contextmanager
def disposable_probe_root(work_root: Path | None = None) -> Iterator[Path]:
    """Create a disposable root under an explicitly writable parent on Windows."""
    parent = (work_root or Path.cwd()).resolve()
    parent.mkdir(parents=True, exist_ok=True)
    for _ in range(10):
        root = parent / f"tsunagou-codex-probe-{secrets.token_hex(8)}"
        try:
            # CPython/MinGW can translate POSIX 0o700 into a Windows ACL that
            # denies creating children. Inherit the already private parent ACL.
            root.mkdir()
            if os.name != "nt":
                root.chmod(0o700)
            break
        except FileExistsError:
            continue
    else:
        raise RuntimeError("probe_root_collision")
    try:
        (root / "codex-home").mkdir()
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _baseline(overrides: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {name: overrides.get(name, {"status": "unknown"}) for name in BASELINE}


def run(executable: str, *, work_root: Path | None = None) -> dict[str, Any]:
    identity = IdentityEvidence()
    version = subprocess.run(
        [executable, "--version"], capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=True,
    ).stdout.strip()
    result: dict[str, Any] = {
        "host": "codex", "version": version, "scope": "disposable_no_model_turn",
        "checks": {}, "baseline": _baseline({}), "ready": False,
    }
    with disposable_probe_root(work_root) as root:
        rpc = Rpc(executable, root)
        try:
            initialized = rpc.call("initialize", {"clientInfo": {"name": "tsunagou_probe", "version": "0.1.0"},
                                                   "capabilities": {"experimentalApi": True}})
            result["checks"]["initialize"] = "result" in initialized
            ids: list[str] = []
            for _ in range(2):
                reply = rpc.call("thread/start", {"cwd": str(root), "approvalPolicy": "never",
                                                   "sandbox": "read-only", "persistExtendedHistory": True})
                if "error" in reply:
                    result["checks"]["thread_start"] = {"status": "failed", "code": reply["error"]["code"]}
                    return result
                ids.append(reply["result"]["thread"]["id"])
            result["checks"]["same_directory_distinct"] = ids[0] != ids[1]
            result["identity_digests"] = [identity.digest(value) for value in ids]
            result["baseline"] = _baseline({
                "identity.session_isolation": {
                    "status": "supported" if result["checks"]["same_directory_distinct"] else "unsupported",
                    "evidence_refs": ["initialize", "same_directory_distinct"],
                },
            })
            for method, label in (("thread/resume", "resume"), ("thread/fork", "fork")):
                reply = rpc.call(method, {"threadId": ids[0], "cwd": str(root), "approvalPolicy": "never"})
                if "result" in reply:
                    returned = reply["result"]["thread"]["id"]
                    result["checks"][label] = {"status": "observed", "same_identity": returned == ids[0],
                                                "identity_digest": identity.digest(returned)}
                else:
                    result["checks"][label] = {"status": "failed", "code": reply["error"]["code"],
                                                "reason": "empty_thread_not_persisted_or_api_precondition"}
            result["checks"]["compact"] = {"status": "unknown", "reason": "requires_model_history_and_authenticated_model_call"}
            result["checks"]["clear"] = {"status": "unknown", "reason": "no_verified_native_clear_surface"}
            result["checks"]["installation_profile"] = {"status": "unknown", "reason": "adapter_installation_identity_not_implemented"}
        except (queue.Empty, KeyError, ValueError, OSError) as error:
            result["failure"] = type(error).__name__
        finally:
            rpc.close()
            result["stderr_lines_discarded"] = len(rpc.stderr)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--executable", default=shutil.which("codex"))
    parser.add_argument("--work-root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.executable:
        parser.error("codex_not_installed")
    evidence = run(args.executable, work_root=args.work_root)
    write_evidence(args.output, evidence)
    print(json.dumps(evidence))
