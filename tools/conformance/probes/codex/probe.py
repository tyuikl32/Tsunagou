"""Probe only new disposable app-server threads; never read the user's Codex home."""

from __future__ import annotations

import argparse
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from tools.conformance.probes.common import IdentityEvidence, write_evidence


class Rpc:
    def __init__(self, executable: str, root: Path) -> None:
        env = {key: value for key, value in os.environ.items()
               if not any(term in key.upper() for term in ("TOKEN", "KEY", "SECRET", "AUTH"))}
        env["CODEX_HOME"] = str(root / "codex-home")
        self.process = subprocess.Popen(
            [executable, "app-server", "--stdio"], cwd=root, env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8",
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
                return message

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)


def run(executable: str) -> dict[str, Any]:
    identity = IdentityEvidence()
    version = subprocess.run([executable, "--version"], capture_output=True, text=True, check=True).stdout.strip()
    result: dict[str, Any] = {"host": "codex", "version": version, "scope": "disposable_no_model_turn",
                              "checks": {}, "ready": False}
    with tempfile.TemporaryDirectory(
        prefix="tsunagou-codex-probe-", ignore_cleanup_errors=True
    ) as name:
        root = Path(name)
        (root / "codex-home").mkdir()
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
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.executable:
        parser.error("codex_not_installed")
    evidence = run(args.executable)
    write_evidence(args.output, evidence)
    print(json.dumps(evidence))
