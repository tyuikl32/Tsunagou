"""Probe a running OpenCode headless server without sending a model prompt."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from tools.conformance.probes.common import BASELINE, IdentityEvidence, write_evidence


class OpenCodeApi:
    def __init__(self, base_url: str, *, timeout: float = 5.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        payload = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}{path}", data=payload, method=method,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            raw = response.read()
        return json.loads(raw) if raw else None


def _baseline(statuses: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {name: statuses.get(name, {"status": "unknown"}) for name in BASELINE}


def run(base_url: str, *, directory: str | None = None) -> dict[str, Any]:
    api = OpenCodeApi(base_url)
    identity = IdentityEvidence()
    result: dict[str, Any] = {
        "host": "opencode", "version": "unknown",
        "scope": "headless_no_model_turn", "checks": {},
        "baseline": {}, "ready": False,
    }
    sessions: list[str] = []
    try:
        health = api.request("GET", "/global/health")
        result["version"] = str(health.get("version", "unknown")) if isinstance(health, dict) else "unknown"
        result["checks"]["health"] = bool(isinstance(health, dict) and health.get("healthy") is True)
        projects = api.request("GET", "/project")
        result["checks"]["project_endpoint"] = isinstance(projects, list)
        query = "" if directory is None else f"?{urllib.parse.urlencode({'directory': directory})}"
        for _ in range(2):
            session = api.request("POST", f"/session{query}", {})
            session_id = session.get("id") if isinstance(session, dict) else None
            if not isinstance(session_id, str):
                raise RuntimeError("session_id_missing")
            sessions.append(session_id)
        result["checks"]["same_directory_distinct"] = sessions[0] != sessions[1]
        result["identity_digests"] = [identity.digest(session_id) for session_id in sessions]
        details = [api.request("GET", f"/session/{session_id}{query}") for session_id in sessions]
        result["checks"]["session_details"] = all(isinstance(item, dict) for item in details)
        forked = api.request("POST", f"/session/{sessions[0]}/fork{query}", {})
        fork_id = forked.get("id") if isinstance(forked, dict) else None
        if isinstance(fork_id, str):
            result["checks"]["fork_new_identity"] = fork_id not in sessions
            result["fork_identity_digest"] = identity.digest(fork_id)
            sessions.append(fork_id)
        else:
            result["checks"]["fork_new_identity"] = False
        histories = [api.request("GET", f"/session/{session_id}/message{query}") for session_id in sessions[:2]]
        result["checks"]["message_history_endpoint"] = all(isinstance(item, list) for item in histories)
        doc = api.request("GET", "/doc")
        paths = doc.get("paths", {}) if isinstance(doc, dict) else {}
        result["checks"]["typed_session_api"] = all(
            path in paths for path in ("/session", "/session/{sessionID}", "/session/{sessionID}/fork")
        )
        result["baseline"] = _baseline({
            "identity.session_isolation": {
                "status": "supported" if result["checks"].get("same_directory_distinct") else "unsupported",
                "evidence_refs": ["health", "same_directory_distinct", "session_details"],
            },
        })
    except (OSError, ValueError, KeyError, RuntimeError, urllib.error.URLError, json.JSONDecodeError) as error:
        result["failure"] = type(error).__name__
        result["baseline"] = _baseline({})
    finally:
        for session_id in sessions:
            try:
                api.request("DELETE", f"/session/{session_id}")
            except (OSError, urllib.error.URLError, ValueError, json.JSONDecodeError):
                pass
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:4096")
    parser.add_argument("--directory")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--executable", default=shutil.which("opencode"))
    args = parser.parse_args()
    evidence = run(args.base_url, directory=args.directory)
    write_evidence(args.output, evidence)
    print(json.dumps(evidence, ensure_ascii=True))
