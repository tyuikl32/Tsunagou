"""Private client for the initialized DSH Desktop wake plugin, not a scheduler.

Two things this client is careful about:

* **It observes before it wakes.** The plugin's status route answers what the bound
  session is doing *now*; asking it first is what lets a successful wake report the
  session's real ``state`` / ``can_queue`` instead of ``unknown``. The observation is
  taken before the submission, so it is labelled as such — it is never presented as
  proof that the wake started a turn.
* **It reports the delivery timing it actually got.** The plugin submits with the mode
  from its own managed configuration; the client reports that as the timing *used*, and
  says so explicitly when it is worse than what was declared.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from tsunagou.hostwake.timing import DEEPSEEK_WAKE_MODES, deepseek_timing_for_mode, plan_delivery
from tsunagou.platform.deepseek_wake import (
    DEEPSEEK_WAKE_DEFAULT_MODE,
    deepseek_wake_modes,
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


def _configured_mode(config: dict[str, Any]) -> str:
    """The plugin's own ``wake_mode``, as it will submit it.

    An absent field means the plugin's default; an unusable value is already refused
    by the configuration reader, and a defensive fallback here only keeps an older
    file working.
    """
    mode = config.get("wake_mode", DEEPSEEK_WAKE_DEFAULT_MODE)
    return mode if isinstance(mode, str) and mode in deepseek_wake_modes() else DEEPSEEK_WAKE_DEFAULT_MODE


def _delivery_report(*, used: str, declared: str | None = None, source: str) -> dict[str, Any]:
    """One timing statement, degraded explicitly rather than silently.

    ``coordination.wake`` accepts only ``message_id``, so there is nothing to request:
    ``requested`` is ``null`` here, and a later per-message mode can fill it in without
    changing this shape.
    """
    plan = plan_delivery(used=used, declared=declared if declared is not None else used, source=source)
    return {**plan.to_public(), "timing_vocabulary": list(DEEPSEEK_WAKE_MODES.values())}


def run_deepseek_operation(action: str, *, project_id: str, agent_id: str, conversation_id: str,
                          message_id: str) -> dict[str, Any]:
    declared_timing = deepseek_timing_for_mode(DEEPSEEK_WAKE_DEFAULT_MODE)
    result: dict[str, Any] = {
        "host": "deepseek", "version": None, "state": "unknown", "can_queue": "unknown",
        "result": "failed", "error_code": None, "evidence": [],
        "observed_at": format_timestamp(now_ms()), "turn_started": False, "request_associated": False,
        "delivery": _delivery_report(used="unknown", declared=declared_timing, source="unobserved"),
    }

    def failed(code: str, *, unknown: bool = False, used: str | None = None) -> dict[str, Any]:
        value = {**result, "result": "unknown" if unknown else "failed", "error_code": code}
        if used is not None:
            value["delivery"] = _delivery_report(used=used, declared=declared_timing, source="plugin_wake_mode")
        return value

    if action not in {"status", "wake"} or not all((project_id, agent_id, conversation_id, message_id)):
        return failed("deepseek_wake_identity_required")
    try:
        config = read_deepseek_wake_configuration()
    except (OSError, ValueError, RuntimeError):
        return failed("deepseek_wake_setup_required")
    mode = _configured_mode(config)
    declared_timing = deepseek_timing_for_mode(mode)
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

    def call(route: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]] | None:
        """One bounded loopback exchange; ``None`` means the transport failed."""
        request = Request(endpoint.rstrip("/") + route, data=json.dumps(payload).encode(),
                          headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
                          method="POST")
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
                return None
            value = json.loads(raw)
            if not isinstance(value, dict):
                return None
            return status, value
        except (OSError, URLError, ValueError):
            return None

    def observe() -> dict[str, Any] | None:
        """Ask the plugin what the bound session is doing, before any submission."""
        exchange = call("/tsunagou/wake/status", dict(ids))
        if exchange is None:
            return None
        status, value = exchange
        if value.get("ok") is not True or status != 200:
            return None
        state = value.get("state")
        if (any(value.get(k) != v for k, v in ids.items()) or type(value.get("exists")) is not bool
                or type(value.get("loaded")) is not bool or type(value.get("queueable")) is not bool
                or not isinstance(state, str) or state not in {"idle", "running", "unloaded", "unknown"}):
            return None
        return {"exists": value["exists"], "state": state, "can_queue": value["queueable"]}

    if action == "status":
        observed = observe()
        if observed is None:
            return failed("deepseek_wake_invalid_response")
        if not observed["exists"]:
            return failed("deepseek_wake_session_not_found")
        return {**result, "state": observed["state"], "can_queue": observed["can_queue"], "result": "observed",
                "evidence": ["deepseek:wake-plugin:status"],
                # A status read submits nothing, so the timing it names is the capability
                # the plugin is configured with — declared, and labelled as such.
                "delivery": _delivery_report(used=declared_timing, declared=declared_timing,
                                             source="plugin_wake_mode_declared")}

    # Observe first. This is deliberately *before* the submission and is reported as
    # what the session was doing then, never as evidence that the reminder was read.
    observed = observe()
    if observed is not None:
        result.update(state=observed["state"], can_queue=observed["can_queue"])
    exchange = call("/tsunagou/wake", {**ids, "message_id": message_id})
    if exchange is None:
        return failed("deepseek_wake_transport_failed", unknown=True, used="unknown")
    status, value = exchange

    if value.get("ok") is not True or status not in {200, 202}:
        error = value.get("error")
        known = isinstance(error, str) and error in _ERRORS
        return failed("deepseek_wake_" + str(error) if known else "deepseek_wake_invalid_response",
                      unknown=not known or error in {"submit_unknown", "internal_error"}, used="unknown")

    expected = "tsunagou-wake-v1:" + hashlib.sha256(json.dumps(
        [project_id, agent_id, conversation_id, message_id], ensure_ascii=False, separators=(",", ":"),
    ).encode()).hexdigest()
    if status != 202 or value.get("accepted") is not True or value.get("request_id") != expected:
        return failed("deepseek_wake_invalid_response", unknown=True, used="unknown")
    # The plugin reports admission only. A started turn is a fact the plugin never
    # reports, so ``turn_started`` stays false: unproven, not disproven.
    return {**result, "result": "queued", "request_associated": True,
            "evidence": ["deepseek:wake-plugin:accepted"],
            "delivery": _delivery_report(used=declared_timing, declared=declared_timing,
                                         source="plugin_wake_mode")}
