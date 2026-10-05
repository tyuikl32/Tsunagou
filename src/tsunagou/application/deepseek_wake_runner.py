"""Private client for the initialized DSH Desktop wake plugin, not a scheduler."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from tsunagou.platform.deepseek_wake import (
    deepseek_wake_runtime_path,
    read_deepseek_wake_configuration,
)
from tsunagou.shared_kernel.time import format_timestamp, now_ms

_ERRORS = {
    "unauthorized", "target_not_bound", "session_not_found", "session_subagent_owned", "session_write_locked",
    "invalid_json", "invalid_field", "method_not_allowed", "body_too_large", "unsupported_content_type",
    "submit_failed", "submit_unknown", "internal_error",
}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


def run_deepseek_operation(action: str, *, project_id: str, agent_id: str, conversation_id: str,
                          message_id: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "host": "deepseek", "version": None, "state": "unknown", "can_queue": "unknown",
        "result": "failed", "error_code": None, "evidence": [],
        "observed_at": format_timestamp(now_ms()), "turn_started": False, "request_associated": False,
    }

    def failed(code: str, *, unknown: bool = False) -> dict[str, Any]:
        return {**result, "result": "unknown" if unknown else "failed", "error_code": code}

    if action not in {"status", "wake"} or not all((project_id, agent_id, conversation_id, message_id)):
        return failed("deepseek_wake_identity_required")
    try:
        config = read_deepseek_wake_configuration()
    except (OSError, ValueError, RuntimeError):
        return failed("deepseek_wake_setup_required")
    ids = {"project_id": project_id, "agent_id": agent_id, "session_id": conversation_id}
    if ids not in config.get("bindings", []):
        return failed("deepseek_wake_binding_required")
    key = config.get("key")
    if not isinstance(key, str) or not key or "\r" in key or "\n" in key:
        return failed("deepseek_wake_setup_required")
    try:
        runtime = json.loads(deepseek_wake_runtime_path().read_text(encoding="utf-8"))
        if not isinstance(runtime, dict) or runtime.get("format_version") != 1 or runtime.get("contract_version") != 1:
            return failed("deepseek_wake_runtime_invalid")
        endpoint = runtime.get("endpoint")
        if not isinstance(endpoint, str):
            return failed("deepseek_wake_runtime_invalid")
        url = urlsplit(endpoint)
        if (url.scheme != "http" or url.hostname not in {"127.0.0.1", "::1"} or not url.port
                or url.username is not None or url.password is not None or url.query or url.fragment or url.path not in {"", "/"}):
            return failed("deepseek_wake_runtime_invalid")
    except FileNotFoundError:
        return failed("deepseek_wake_plugin_not_running")
    except (OSError, ValueError, TypeError):
        return failed("deepseek_wake_runtime_invalid")

    payload = {**ids, **({"message_id": message_id} if action == "wake" else {})}
    route = "/tsunagou/wake" + ("/status" if action == "status" else "")
    request = Request(endpoint.rstrip("/") + route, data=json.dumps(payload).encode(),
                      headers={"Content-Type": "application/json", "Authorization": "Bearer " + key}, method="POST")
    try:
        # Loopback traffic must never follow redirects or inherited HTTP proxies.
        opener = build_opener(ProxyHandler({}), _NoRedirect())
        try:
            response = opener.open(request, timeout=35)
        except HTTPError as exc:
            response = exc
        with response:
            status = response.status
            raw = response.read(16385)
        if len(raw) > 16384:
            return failed("deepseek_wake_invalid_response", unknown=action == "wake")
        value = json.loads(raw)
        if not isinstance(value, dict):
            return failed("deepseek_wake_invalid_response", unknown=action == "wake")
    except (OSError, URLError, ValueError):
        return failed("deepseek_wake_transport_failed", unknown=action == "wake")

    if value.get("ok") is not True or status not in {200, 202}:
        error = value.get("error")
        known = isinstance(error, str) and error in _ERRORS
        return failed("deepseek_wake_" + str(error) if known else "deepseek_wake_invalid_response",
                      unknown=action == "wake" and (not known or error in {"submit_unknown", "internal_error"}))
    if action == "status":
        state = value.get("state")
        if (any(value.get(k) != v for k, v in ids.items()) or type(value.get("exists")) is not bool
                or type(value.get("loaded")) is not bool or type(value.get("queueable")) is not bool
                or not isinstance(state, str) or state not in {"idle", "running", "unloaded", "unknown"}):
            return failed("deepseek_wake_invalid_response")
        if not value["exists"]:
            return failed("deepseek_wake_session_not_found")
        return {**result, "state": state, "can_queue": value["queueable"], "result": "observed",
                "evidence": ["deepseek:wake-plugin:status"]}

    expected = "tsunagou-wake-v1:" + hashlib.sha256(json.dumps(
        [project_id, agent_id, conversation_id, message_id], ensure_ascii=False, separators=(",", ":"),
    ).encode()).hexdigest()
    if status != 202 or value.get("accepted") is not True or value.get("request_id") != expected:
        return failed("deepseek_wake_invalid_response", unknown=True)
    return {**result, "result": "queued", "request_associated": True,
            "evidence": ["deepseek:wake-plugin:accepted"]}
