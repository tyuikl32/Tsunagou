"""Probe DeepSeek Harness Web RPC without touching the user's Harness home."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from tools.conformance.probes.common import BASELINE, IdentityEvidence, write_evidence


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Keep the one-time token exchange response so its cookie is observable."""

    def redirect_request(
        self,
        request: urllib.request.Request,
        response: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        return None


class DeepSeekApi:
    def __init__(self, base_url: str, token: str) -> None:
        self.base = base_url.rstrip("/")
        self.authority = urllib.parse.urlsplit(self.base).netloc
        self.token = token
        self.cookie = self._exchange_token()

    def _request(self, request: urllib.request.Request) -> tuple[int, dict[str, str], bytes]:
        opener = urllib.request.build_opener(NoRedirect())
        try:
            with opener.open(request, timeout=30) as response:
                return response.status, dict(response.headers.items()), response.read()
        except urllib.error.HTTPError as error:
            return error.code, dict(error.headers.items()), error.read()

    def _exchange_token(self) -> str:
        request = urllib.request.Request(
            f"{self.base}/?token={urllib.parse.quote(self.token, safe='-_')}"
        )
        status, headers, _ = self._request(request)
        if status != 303:
            raise RuntimeError(f"token_exchange_status_{status}")
        raw = next((value for key, value in headers.items() if key.lower() == "set-cookie"), "")
        cookie = raw.split(";", 1)[0]
        if "=" not in cookie:
            raise RuntimeError("token_exchange_cookie_missing")
        return cookie

    def rpc(self, endpoint: str, args: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "type": "client-request",
            "rpcId": f"tsunagou-probe-{uuid.uuid4().hex}",
            "method": endpoint,
            "payload": {"args": args},
        }
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base}/api/{endpoint}",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Cookie": self.cookie,
                "Host": self.authority,
                "Origin": self.base,
            },
            method="POST",
        )
        status, _, raw = self._request(request)
        if status != 200:
            raise RuntimeError(f"rpc_status_{status}")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise RuntimeError("rpc_response_not_object")
        return value


def _baseline(overrides: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {name: overrides.get(name, {"status": "unknown"}) for name in BASELINE}


def run(base_url: str, token: str, directory: Path) -> dict[str, Any]:
    identity = IdentityEvidence()
    result: dict[str, Any] = {
        "host": "deepseek",
        "version": os.environ.get("TSUNAGOU_DEEPSEEK_VERSION", "unknown"),
        "scope": "web_rpc_no_model_turn",
        "checks": {},
        "ready": False,
    }
    api = DeepSeekApi(base_url, token)
    first = api.rpc("session/create", {"request": {"cwd": str(directory)}})
    second = api.rpc("session/create", {"request": {"cwd": str(directory)}})
    first_id = first.get("result", {}).get("value", {}).get("sessionId")
    second_id = second.get("result", {}).get("value", {}).get("sessionId")
    if not isinstance(first_id, str) or not isinstance(second_id, str):
        raise RuntimeError("session_create_failed")
    distinct = first_id != second_id
    result["checks"]["same_directory_distinct"] = distinct
    result["identity_digests"] = [identity.digest(first_id), identity.digest(second_id)]
    listed = api.rpc("session/list", {"_request": {}})
    result["checks"]["session_list"] = listed.get("result", {}).get("ok") is True
    result["baseline"] = _baseline({
        "identity.session_isolation": {
            "status": "supported" if distinct else "failed",
            "evidence_refs": ["same_directory_distinct", "session_list"],
        },
    })
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--token", default=os.environ.get("DSH_WEB_TOKEN"))
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.token:
        parser.error("token_required")
    evidence = run(args.base_url, args.token, args.directory)
    write_evidence(args.output, evidence)
    print(json.dumps(evidence))
