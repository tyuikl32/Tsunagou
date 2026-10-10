"""DSH's automatic wake provider: the same loopback plugin, driven by the daemon.

``packages/dsh-wake-plugin`` already serves two loopback endpoints and the explicit
``coordination.wake`` path already talks to them
(:mod:`tsunagou.application.deepseek_wake_runner`). What was missing was the
**automatic** path: ``WakeDispatcher`` looks up a binding in ``provider.store``
before it dispatches anything, and the only registered providers were the two
Codex ones, so every daemon-delivered DSH wake ended as
``failed / host_binding_not_found`` — 16 of 16 on disk before this change.

This module supplies the two pieces that were missing and nothing else:

* :class:`DeepSeekWakeBindingStore` — a *read-only view* of the bindings the
  plugin has already been configured with, cross-checked against this project's
  own private route and session credential. A binding is ``ready`` only when it
  is declared **and** verified; anything else is absent, which stays fail-closed
  because ``WakeDispatcher`` refuses an unknown binding.
* :class:`DeepSeekWakeProvider` — a ``HostWakePort`` that reuses the existing
  loopback operation instead of re-implementing HTTP.

The plugin remains the only writer of its configuration. This module never adds,
changes or removes a binding, and never sends a reminder to a session that this
project's own route does not verify.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

from tsunagou.hostwake.port import (
    BindingStatus,
    CombinedBindingStore,
    HostBindingRef,
    HostCapabilityReport,
    HostEvidence,
    HostWakeError,
    HostWakeRequest,
    ThreadHandle,
    WakeAttempt,
)
from tsunagou.hostwake.timing import deepseek_timing_for_mode
from tsunagou.platform.deepseek_wake import (
    DEEPSEEK_WAKE_DEFAULT_MODE,
    deepseek_wake_managed_path,
    deepseek_wake_modes,
    read_deepseek_wake_configuration,
)
from tsunagou.shared_kernel.digests import canonical_digest
from tsunagou.shared_kernel.time import format_timestamp, now_ms

# The provider name is a fact about the channel, not about the vendor: it is what
# ``HostBindingRef.provider`` says when a wake will be delivered through the
# installed DSH wake plugin.
DEEPSEEK_WAKE_PROVIDER = "deepseek_wake"

# ``CombinedBindingStore`` lives in ``hostwake.port`` (both this module and the Codex
# registry need it, and neither should import the other). It is re-exported here because
# this is where callers have been importing it from.
__all__ = [
    "DEEPSEEK_WAKE_PROVIDER",
    "CombinedBindingStore",
    "DeepSeekWakeBindingStore",
    "DeepSeekWakeProvider",
]


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return {}
    return value if isinstance(value, dict) else {}


class DeepSeekWakeBindingStore:
    """The plugin's declared bindings, verified locally, with a status overlay.

    Verification is the same shape the explicit path already uses, so both lanes
    judge the same Agent identically: the route file must be the hash-named record
    for its own ``conversation_id``, belong to this project **and** this project
    root, name ``deepseek`` as its adapter, and point at a session credential that
    exists. A route that fails any of those is not a verified local channel, and
    an unverified channel is reported as *no binding* rather than as ``ready``.
    """

    def __init__(
        self, *, managed_path: str | Path | None = None, routes_dir: str | Path,
        project_id: str, project_root: str | Path, overlay_path: str | Path | None = None,
    ) -> None:
        self.managed_path = Path(managed_path) if managed_path else deepseek_wake_managed_path()
        self.routes_dir = Path(routes_dir)
        self.project_id = project_id
        self.project_root = Path(project_root)
        self.overlay_path = Path(overlay_path) if overlay_path else None
        self._lock = threading.RLock()
        self._overlay: dict[str, str] = {}
        self._load_overlay()

    # -- declarations and verification -----------------------------------

    def _declared(self, agent_id: str | None = None) -> tuple[str, list[dict[str, Any]]]:
        """One snapshot of the plugin's own configuration.

        A missing or unreadable file is not a failure to report: it means the
        plugin has not been initialized here, so there is no binding to wake.
        """
        try:
            value = read_deepseek_wake_configuration()
        except (OSError, ValueError, RuntimeError):
            return DEEPSEEK_WAKE_DEFAULT_MODE, []
        mode = value.get("wake_mode", DEEPSEEK_WAKE_DEFAULT_MODE)
        if mode not in deepseek_wake_modes():
            mode = DEEPSEEK_WAKE_DEFAULT_MODE
        bindings = [item for item in value.get("bindings", [])
                    if isinstance(item, dict) and item.get("project_id") == self.project_id
                    and (agent_id is None or item.get("agent_id") == agent_id)]
        return mode, bindings

    def _verified_conversation(self, agent_id: str) -> str | None:
        """The one verified conversation for this Agent, or ``None``.

        Two verified routes are two claims about which conversation is this Agent,
        so the store refuses to choose between them (the explicit path makes the
        same judgement).
        """
        if not self.routes_dir.is_dir():
            return None
        matches: list[str] = []
        root = self.project_root
        for path in sorted(self.routes_dir.glob("*.json")):
            route = _object(path)
            conversation = route.get("conversation_id")
            if (route.get("format_version") != 1 or route.get("project_id") != self.project_id
                    or route.get("adapter", "deepseek") != "deepseek"
                    or not isinstance(conversation, str) or not conversation
                    or path.stem != hashlib.sha256(conversation.encode()).hexdigest()):
                continue
            recorded_root = route.get("project_root")
            session_file = route.get("session_file")
            if (not isinstance(recorded_root, str) or not isinstance(session_file, str)
                    or Path(recorded_root).resolve() != root):
                continue
            credential = _object(Path(session_file))
            if credential.get("agent_id") != agent_id:
                continue
            matches.append(conversation)
        return matches[0] if len(matches) == 1 else None

    def _ref(self, agent_id: str, session_id: str) -> HostBindingRef:
        overlay = self._overlay.get(agent_id)
        status: BindingStatus = "degraded" if overlay == "degraded" else "ready"
        return HostBindingRef(
            binding_id=f"deepseek-wake:{agent_id}",
            agent_id=agent_id,
            provider=DEEPSEEK_WAKE_PROVIDER,
            adapter_profile="deepseek",
            endpoint_kind="loopback_http",
            status=status,
            capabilities={"wake": "supported"},
            last_probe={"conversation_digest": canonical_digest({"conversation_id": session_id}),
                        "reason": overlay},
        )

    # -- the surface WakeDispatcher expects ------------------------------

    def get(self, agent_id: str) -> tuple[HostBindingRef, dict[str, Any]] | None:
        with self._lock:
            mode, bindings = self._declared(agent_id)
            if not bindings:
                return None
            conversation = self._verified_conversation(agent_id)
            if conversation is None:
                # Declared but not verified: no local channel exists for this Agent,
                # so there is no binding to hand the dispatcher.
                return None
            return self._ref(agent_id, conversation), {"wake_mode": mode, "session_id": conversation}

    def list_refs(self) -> list[HostBindingRef]:
        with self._lock:
            mode, bindings = self._declared()
            result = []
            for item in bindings:
                agent_id = str(item["agent_id"])
                conversation = self._verified_conversation(agent_id)
                if conversation is not None:
                    result.append(self._ref(agent_id, conversation))
            del mode
            return result

    def update_status(self, agent_id: str, status: str, *, reason: str | None = None) -> HostBindingRef:
        """Record a judgement about the *automatic* lane, never about the plugin's config.

        The plugin's configuration is the only source of bindings and this store
        never writes it. What is written here is this daemon's own observation that
        the automatic lane did not work, which keeps later deliveries off a known
        dead end. A later verified wake reports ``ready`` again.
        """
        with self._lock:
            item = self.get(agent_id)
            if item is None:
                raise KeyError("host_binding_not_found")
            if status == "ready":
                self._overlay.pop(agent_id, None)
            else:
                self._overlay[agent_id] = status
            self._save_overlay()
            return self._ref(agent_id, str(item[1]["session_id"]))

    def clear_status(self, agent_id: str) -> None:
        with self._lock:
            self._overlay.pop(agent_id, None)
            self._save_overlay()

    # -- overlay persistence ---------------------------------------------

    def _load_overlay(self) -> None:
        if self.overlay_path is None or not self.overlay_path.is_file():
            return
        value = _object(self.overlay_path)
        self._overlay = {str(key): str(status) for key, status in value.items() if isinstance(status, str)}

    def _save_overlay(self) -> None:
        path = self.overlay_path
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(self._overlay, handle, ensure_ascii=False, sort_keys=True, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)


class DeepSeekWakeProvider:
    """Wake a bound DSH session through the installed plugin's loopback endpoint.

    The transport is not re-implemented here: :func:`deepseek_wake_runner.run_deepseek_operation`
    already reads the private endpoint and key, refuses non-loopback addresses and
    never follows redirects. This provider only adapts its result to ``HostWakePort``.
    """

    provider_name = DEEPSEEK_WAKE_PROVIDER

    def __init__(self, store: DeepSeekWakeBindingStore, *, runner: Any | None = None) -> None:
        self.store = store
        self._runner = runner

    def delivery_timing(self, agent_id: str) -> tuple[str, str]:
        """What this host says it can do, and where that statement comes from.

        The value is the plugin's own ``wake_mode``, interpreted in the platform's
        vocabulary. It is a capability statement, not an observation.
        """
        item = self.store.get(agent_id)
        if item is None:
            return "none", "no_verified_binding"
        return deepseek_timing_for_mode(item[1].get("wake_mode")), "plugin_wake_mode"

    def _record(self, binding: HostBindingRef) -> tuple[HostBindingRef, dict[str, Any]]:
        item = self.store.get(binding.agent_id)
        if item is None or item[0].provider != self.provider_name:
            raise HostWakeError("host_binding_not_found", "no verified DSH wake binding for this Agent")
        if item[0].status != "ready":
            raise HostWakeError("host_binding_not_ready", "the DSH wake binding is not usable for a wake")
        return item

    def probe(self, binding: HostBindingRef) -> HostCapabilityReport:
        declared, source = self.delivery_timing(binding.agent_id)
        try:
            self._record(binding)
        except HostWakeError as exc:
            return HostCapabilityReport(self.provider_name, "degraded", None, "loopback_http",
                                        reason=exc.code, delivery_timing="none")
        return HostCapabilityReport(
            self.provider_name, "supported", None, "loopback_http",
            methods=("status", "wake"), capabilities={"wake": "supported"},
            reason=source, delivery_timing=declared,
        )

    def ensure_thread(self, binding: HostBindingRef) -> ThreadHandle:
        """A DSH wake resumes the session the plugin already has bound.

        There is no thread to create: the plugin refuses to create or fork one, so
        reporting a handle here would claim an operation that does not exist.
        """
        _ref, record = self._record(binding)
        return ThreadHandle(str(record["session_id"]), metadata={"resumed_by_host": True})

    def inspect(self, binding: HostBindingRef) -> dict[str, Any]:
        item = self.store.get(binding.agent_id)
        if item is None:
            return {"provider": self.provider_name, "agent_id": binding.agent_id, "status": "absent"}
        declared, source = self.delivery_timing(binding.agent_id)
        return {"provider": self.provider_name, "agent_id": binding.agent_id,
                "status": item[0].status, "delivery_timing": declared, "timing_source": source}

    def session_state(self, agent_id: str) -> str | None:
        """What the host says this Agent's session is doing -- ``running`` / ``idle`` /
        ``unloaded`` -- or ``None`` when it will not say.

        The idle watchdog needs this to tell "this worker stopped in the middle of its
        attempt" from "this worker is busy" (2026-10-10: an Agent finished part of its work,
        wrote a summary, and its turn ended there -- a text-only reply *is* the end of a turn
        in the host, so the session goes idle and nobody calls it again). Only the plugin can
        answer, so a lane that cannot (Codex today) returns ``None`` and the caller falls back
        to its own activity evidence. Never raises: a host that cannot be reached is "won't
        say", not "is idle".
        """

        item = self.store.get(agent_id)
        if item is None:
            return None
        session_id = str(item[1].get("session_id") or "").strip()
        if not session_id:
            return None
        try:
            from tsunagou.application.deepseek_wake_runner import run_deepseek_operation

            result = dict(run_deepseek_operation(
                "status", project_id=self.store.project_id, agent_id=agent_id,
                conversation_id=session_id, message_id="idle-watchdog-session-state",
            ))
        except Exception:
            return None
        state = str(result.get("state") or "").strip()
        return state or None

    def close(self, binding: HostBindingRef, reason: str) -> None:
        """Nothing to close: this provider holds no process, socket or thread."""
        del binding, reason

    def wake(self, request: HostWakeRequest) -> WakeAttempt:
        request.validate()
        _ref, record = self._record(request.binding)
        declared, source = self.delivery_timing(request.agent_id)
        runner = self._runner
        if runner is None:
            from tsunagou.application.deepseek_wake_runner import run_deepseek_operation

            runner = run_deepseek_operation
        try:
            result = dict(runner(
                "wake", project_id=str(request.project_id or ""), agent_id=request.agent_id,
                conversation_id=str(record["session_id"]), message_id=request.message_id,
            ))
        except Exception as exc:  # pragma: no cover - a runner raises only on a defect
            return self._attempt(request, "unknown", "deepseek_wake_operation_failed",
                                 declared=declared, source=source, detail=str(exc))

        delivery = dict(result.get("delivery") or {})
        if not delivery:
            delivery = {"declared": declared, "used": "unknown", "source": source}
        # 这条通道只报"受理"：宿主不会回来说"回合开始了"。把这件事写进投递报告，读者才知道
        # 为什么一次成功的投递永远不会变成 ``completed``（2026-10-10：这种"等不到终态"原来
        # 被记成 ``failed / host_wake_unknown_expired``，看着像唤醒失败）。
        delivery.setdefault("confirmation", "admission_only")
        evidence = self._evidence(request, result)
        if result.get("result") == "queued":
            return self._attempt(request, "queued", None, declared=declared, source=source,
                                 delivery=delivery, evidence=evidence)
        error_code = result.get("error_code") or "deepseek_wake_failed"
        if result.get("result") == "unknown":
            return self._attempt(request, "unknown", str(error_code), declared=declared,
                                 source=source, delivery=delivery, evidence=evidence)
        return self._attempt(request, "failed", str(error_code), declared=declared,
                             source=source, delivery=delivery, evidence=evidence)

    @staticmethod
    def _evidence(request: HostWakeRequest, result: dict[str, Any]) -> tuple[HostEvidence, ...]:
        """Turn the runner's fixed evidence labels into host evidence records.

        The labels are this project's own vocabulary (``deepseek:wake-plugin:accepted``),
        so they are safe to record; they carry no endpoint, session or message content.
        """
        observed = result.get("observed_at")
        occurred = observed if isinstance(observed, str) else format_timestamp(now_ms())
        return tuple(
            HostEvidence(
                kind=str(label).rsplit(":", 1)[-1] or "observed",
                wake_attempt_id=request.wake_attempt_id, agent_id=request.agent_id,
                message_id=request.message_id, status="observed",
                evidence_digest=canonical_digest({"attempt": request.wake_attempt_id, "label": str(label)}),
                observed_at=occurred, details={},
            )
            for label in (result.get("evidence") or ())
            if isinstance(label, str)
        )

    def poll(self, wake_attempt_id: str) -> WakeAttempt | None:
        """DSH cannot be inspected for "did our reminder start a turn".

        The plugin reports admission only, and it answers nothing about turns. An
        attempt left in ``queued`` would therefore be polled forever by a watcher
        that can never learn anything, so this provider offers no observation and
        the dispatcher follows its documented ``host_wake_state_lost`` path.
        """
        del wake_attempt_id
        return None

    @staticmethod
    def _attempt(
        request: HostWakeRequest, state: str, error_code: str | None, *,
        declared: str, source: str, delivery: dict[str, Any] | None = None,
        evidence: tuple[Any, ...] = (), detail: str | None = None,
    ) -> WakeAttempt:
        report = dict(delivery or {})
        report.setdefault("declared", declared)
        report.setdefault("source", source)
        report.setdefault("used", report.get("declared", "unknown"))
        return WakeAttempt(
            request.wake_attempt_id, request.agent_id, request.message_id, state,  # type: ignore[arg-type]
            evidence=evidence,
            error_code=error_code,
            error_message=detail or ("the DSH wake plugin did not accept the reminder" if error_code else None),
            updated_at=format_timestamp(now_ms()),
            delivery=report,
        )

    def capability(self, agent_id: str) -> dict[str, Any]:
        """A secret-free description for a caller-facing surface."""
        declared, source = self.delivery_timing(agent_id)
        return {"provider": self.provider_name, "delivery_timing": declared, "timing_source": source}
