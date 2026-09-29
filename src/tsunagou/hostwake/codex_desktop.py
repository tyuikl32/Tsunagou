"""Codex Desktop's local application tools transport.

This is deliberately separate from the public app-server transport: opening a
second app-server cannot acquire the writer of an existing Desktop thread.
"""

from __future__ import annotations

import asyncio
import json
import os
import struct
import sys
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Any, cast
from uuid import uuid4
from xml.etree import ElementTree

from tsunagou.hostwake.binding import PrivateBindingStore
from tsunagou.hostwake.port import (
    HostBindingRef,
    HostCapabilityReport,
    HostEvidence,
    HostWakeError,
    HostWakeRequest,
    ThreadHandle,
    WakeAttempt,
    WakeState,
)
from tsunagou.shared_kernel.digests import canonical_digest
from tsunagou.shared_kernel.time import format_timestamp, now_ms

MAX_FRAME_BYTES = 8 * 1024 * 1024


class NativeAppToolsClient:
    """One bounded IPC exchange per request, also callable from an ASGI loop.

    The application plugin uses little-endian length-prefixed JSON-RPC over a
    Windows named pipe or Unix socket. No endpoint discovery or second host
    process is needed. The caller thread is the real enrolling host identity;
    mcp-turn/call IDs use the plugin's documented-in-code metadata fallbacks,
    and do not purport to identify an active model turn.
    """

    def __init__(self, endpoint: str, caller_thread_id: str, *, timeout: float = 15.0) -> None:
        if not endpoint or not caller_thread_id:
            raise HostWakeError("host_context_missing", "Desktop endpoint and caller context are required")
        self.endpoint = endpoint
        self.caller_thread_id = caller_thread_id
        self.timeout = timeout
        self._closed = False
        self._lock = threading.Lock()
        self._next_id = 0

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            if self._closed:
                raise HostWakeError("desktop_connection_closed", "Desktop client has been closed")
            self._next_id += 1
            request_id = self._next_id
        body = json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}).encode()
        if len(body) > MAX_FRAME_BYTES:
            raise HostWakeError("desktop_request_too_large", "Desktop request exceeds frame limit")
        # Proactor named-pipe I/O is cancellable. A per-request loop also avoids
        # binding a client to whichever HTTP/background thread called it first.
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="tsunagou-app-ipc") as executor:
            return executor.submit(self._run, body, request_id).result()

    def _run(self, body: bytes, request_id: int) -> dict[str, Any]:
        try:
            with asyncio.Runner() as runner:
                return runner.run(asyncio.wait_for(self._exchange(body, request_id), self.timeout))
        except TimeoutError as exc:
            raise HostWakeError("desktop_request_timeout", "Desktop response timed out; outcome may be unknown") from exc
        except (OSError, EOFError, asyncio.IncompleteReadError) as exc:
            raise HostWakeError("desktop_connection_lost", "Desktop connection was unavailable or closed") from exc
        except (ValueError, UnicodeError) as exc:
            raise HostWakeError("desktop_response_invalid", "Desktop returned an invalid response") from exc

    async def _exchange(self, body: bytes, request_id: int) -> dict[str, Any]:
        if sys.platform == "win32":
            loop = asyncio.get_running_loop()
            reader = asyncio.StreamReader()
            protocol = asyncio.StreamReaderProtocol(reader)
            transport, _ = await loop.create_pipe_connection(lambda: protocol, self.endpoint)  # type: ignore[attr-defined]
            writer = asyncio.StreamWriter(transport, protocol, reader, loop)
        else:
            reader, writer = await asyncio.open_unix_connection(self.endpoint)
        try:
            writer.write(struct.pack("<I", len(body)) + body)
            await writer.drain()
            size = struct.unpack("<I", await reader.readexactly(4))[0]
            if size > MAX_FRAME_BYTES:
                raise ValueError("frame limit exceeded")
            reply = json.loads(await reader.readexactly(size))
            if not isinstance(reply, dict) or reply.get("id") != request_id:
                raise ValueError("response identity mismatch")
            if "error" in reply:
                raise HostWakeError("desktop_rpc_rejected", "Desktop rejected the application tool request")
            result = reply.get("result")
            if not isinstance(result, dict):
                raise ValueError("object result required")
            return result
        finally:
            writer.close()
            await writer.wait_closed()

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        request_ref = str(uuid4())
        response = self.request("tools/call", {
            "arguments": arguments,
            "callerSource": "codex",
            "callId": f"mcp-call-{request_ref}",
            "namespace": "codex_app",
            "threadId": self.caller_thread_id,
            "tool": name,
            "turnId": f"mcp-turn-{request_ref}",
        })
        if response.get("success") is not True:
            raise HostWakeError("desktop_tool_rejected", "Desktop application tool did not succeed")
        items = response.get("contentItems", [])
        for item in items:
            if isinstance(item, dict) and item.get("type") == "inputText":
                try:
                    result = json.loads(item.get("text", ""))
                except (ValueError, TypeError):
                    continue
                if isinstance(result, dict):
                    return result
        raise HostWakeError("desktop_tool_result_invalid", "Desktop tool returned no structured result")

    def close(self) -> None:
        with self._lock:
            self._closed = True


class CodexDesktopProvider:
    """Wake a user-created thread through its original Desktop application."""

    provider_name = "codex_desktop_app"

    def __init__(
        self, store: PrivateBindingStore, *,
        client_factory: Callable[[dict[str, Any]], NativeAppToolsClient] | None = None,
    ) -> None:
        self.store = store
        self.client_factory = client_factory or self._client
        self._pending: dict[str, tuple[HostWakeRequest, WakeAttempt]] = {}
        self._lock = threading.RLock()

    def register_binding(
        self, *, agent_id: str, binding_id: str, adapter_profile: str,
        cwd: str | Path, scope_digest: str, policy_digest: str,
        endpoint: str | None = None, thread_id: str | None = None,
        caller_thread_id: str | None = None, host_generation: str | None = None,
        host_id: str = "local", app_version: str | None = None,
        plugin_version: str | None = None, connection_epoch: int | None = None,
        attach_confirmed: bool = False, **host_options: Any,
    ) -> HostBindingRef:
        if not attach_confirmed or not endpoint or not thread_id:
            raise HostWakeError("desktop_binding_context_required", "Authorized original Desktop context is required")
        if any(host_options.get(k) is not None for k in (
            "model", "approval_policy", "sandbox", "sandbox_policy", "executable",
        )):
            raise HostWakeError("desktop_policy_override_unsupported", "Desktop wake preserves the host's settings")
        prior = self.store.get(agent_id)
        if prior and prior[1].get("thread_id") != thread_id:
            raise HostWakeError("host_binding_thread_mismatch", "A binding cannot change its original conversation")
        if (prior and prior[0].status == "ready" and prior[1].get("endpoint") == endpoint
                and prior[0].connection_epoch == connection_epoch
                and prior[0].scope_digest == scope_digest and prior[0].policy_digest == policy_digest
                and prior[0].cwd_digest == canonical_digest({"cwd": str(Path(cwd).resolve())})
                and prior[1].get("extra", {}).get("host_generation") == (host_generation or canonical_digest(endpoint))):
            return prior[0]
        ref = HostBindingRef(
            binding_id=prior[0].binding_id if prior else binding_id,
            agent_id=agent_id, provider=self.provider_name, adapter_profile=adapter_profile,
            thread_id_digest=canonical_digest({"thread_id": thread_id}),
            endpoint_kind="named_pipe" if os.name == "nt" else "unix_socket",
            cwd_digest=canonical_digest({"cwd": str(Path(cwd).resolve())}),
            scope_digest=scope_digest, policy_digest=policy_digest,
            status="ready", binding_revision=prior[0].binding_revision + 1 if prior else 1,
            connection_epoch=connection_epoch,
        )
        return self.store.put(ref, endpoint=endpoint, thread_id=thread_id, extra={
            "caller_thread_id": caller_thread_id or thread_id,
            "host_generation": host_generation or canonical_digest(endpoint),
            "host_id": host_id, "app_version": app_version, "plugin_version": plugin_version,
            "connected_at": format_timestamp(now_ms()),
        })

    def validate_refresh(self, agent_id: str, refresh: dict[str, Any]) -> None:
        item = self.store.get(agent_id)
        if item is None or item[0].provider != self.provider_name:
            raise HostWakeError("host_binding_not_found", "Only an existing Desktop binding can be refreshed")
        allowed = {"provider", "endpoint", "host_generation", "app_version", "plugin_version"}
        if set(refresh) - allowed or refresh.get("provider") != self.provider_name:
            raise HostWakeError("host_binding_refresh_invalid", "Refresh cannot change the bound identity")
        endpoint = refresh.get("endpoint")
        generation = refresh.get("host_generation")
        if not isinstance(endpoint, str) or not endpoint or not isinstance(generation, str) or not generation:
            raise HostWakeError("host_binding_refresh_invalid", "Endpoint and host generation are required")

    def refresh_binding(self, agent_id: str, refresh: dict[str, Any], *, connection_epoch: int) -> HostBindingRef:
        self.validate_refresh(agent_id, refresh)
        item = self.store.get(agent_id)
        assert item is not None
        endpoint = str(refresh["endpoint"])
        generation = str(refresh["host_generation"])
        ref, record = item
        changed = endpoint != record.get("endpoint") or generation != record.get("extra", {}).get("host_generation")
        return self.store.put(
            replace(ref, connection_epoch=connection_epoch, status="ready",
                    binding_revision=ref.binding_revision + int(changed)),
            endpoint=endpoint, extra={**refresh, "connected_at": format_timestamp(now_ms())},
        )

    def _record(self, binding: HostBindingRef) -> dict[str, Any]:
        item = self.store.get(binding.agent_id)
        if item is None or item[0].provider != self.provider_name:
            raise HostWakeError("host_binding_not_found", "Desktop binding is unavailable")
        if item[0].binding_revision != binding.binding_revision or item[0].thread_id_digest != binding.thread_id_digest:
            raise HostWakeError("host_binding_changed", "Desktop connection changed during the request")
        if item[0].status != "ready":
            raise HostWakeError("host_binding_not_ready", "Desktop binding is not connected")
        return item[1]

    @staticmethod
    def _client(record: dict[str, Any]) -> NativeAppToolsClient:
        return NativeAppToolsClient(str(record["endpoint"]), str(record["extra"]["caller_thread_id"]))

    def _read(self, binding: HostBindingRef, *, include_outputs: bool = False) -> dict[str, Any]:
        record = self._record(binding)
        client = self.client_factory(record)
        try:
            result = client.call_tool("read_thread", {
                "threadId": record["thread_id"], "hostId": record["extra"].get("host_id", "local"),
                "turnLimit": 3, "includeOutputs": include_outputs, "maxOutputCharsPerItem": 1200,
            })
        finally:
            client.close()
        self._record(binding)
        if result.get("thread", {}).get("id") != record["thread_id"]:
            raise HostWakeError("host_binding_thread_mismatch", "Desktop returned another conversation")
        return result

    @staticmethod
    def _busy(view: dict[str, Any]) -> bool:
        status = view.get("thread", {}).get("status", {})
        return status.get("type") in {"active", "running"} if isinstance(status, dict) else status in {"active", "running"}

    def probe(self, binding: HostBindingRef) -> HostCapabilityReport:
        try:
            self._read(binding)
            return HostCapabilityReport(self.provider_name, "unknown", None, binding.endpoint_kind,
                                        methods=("read_thread",), reason="connectivity_only")
        except HostWakeError as exc:
            return HostCapabilityReport(self.provider_name, "degraded", None, binding.endpoint_kind, reason=exc.code)

    def ensure_thread(self, binding: HostBindingRef) -> ThreadHandle:
        view = self._read(binding)
        return ThreadHandle(str(view["thread"]["id"]), metadata={"status": view["thread"].get("status")})

    @staticmethod
    def _evidence(kind: str, request: HostWakeRequest, **details: Any) -> HostEvidence:
        return HostEvidence(
            kind, request.wake_attempt_id, request.agent_id, request.message_id, "observed",
            canonical_digest({"kind": kind, "attempt": request.wake_attempt_id, **details}),
            observed_at=cast(str, format_timestamp(now_ms())), details={"trigger_source": "daemon_delivery", **details},
        )

    @staticmethod
    def _marker(wake_attempt_id: str) -> str:
        return f"[Tsunagou wake {wake_attempt_id}]"

    @staticmethod
    def _is_wake_input(item: dict[str, Any], marker: str) -> bool:
        """Match only the host's original input, never an Agent/tool quotation."""
        if item.get("type") == "userMessage":
            return any(
                isinstance(part, dict) and part.get("type") == "text"
                and isinstance(part.get("text"), str) and part["text"].startswith(marker + " ")
                for part in item.get("content", [])
            )
        if (item.get("type") != "functionCallOutput" or item.get("namespace") != "codex_app"
                or item.get("name") != "send_message_to_thread"):
            return False
        output = item.get("output")
        if not isinstance(output, dict) or not isinstance(output.get("text"), str) or output.get("truncated"):
            return False
        try:
            delegation = ElementTree.fromstring(output["text"])
        except ElementTree.ParseError:
            return False
        inputs = delegation.findall("input")
        return (delegation.tag == "codex_delegation" and len(inputs) == 1
                and isinstance(inputs[0].text, str) and inputs[0].text.startswith(marker + " "))

    def wake(self, request: HostWakeRequest) -> WakeAttempt:
        request.validate()
        with self._lock:
            prior = self._pending.get(request.wake_attempt_id)
            if prior is not None:
                return prior[1]
        attempt = WakeAttempt(request.wake_attempt_id, request.agent_id, request.message_id, "queued",
                              thread_id_digest=request.binding.thread_id_digest)
        try:
            view = self._read(request.binding)
            if not self._busy(view):
                try:
                    attempt = self._send(request, attempt)
                except HostWakeError as exc:
                    attempt = self._failure(request, exc)
        except HostWakeError as exc:
            attempt = self._read_failure(request, attempt, exc)
        with self._lock:
            self._pending[request.wake_attempt_id] = (request, attempt)
        return attempt

    def _send(self, request: HostWakeRequest, attempt: WakeAttempt) -> WakeAttempt:
        record = self._record(request.binding)
        client = self.client_factory(record)
        try:
            client.call_tool("send_message_to_thread", {
                "threadId": record["thread_id"], "hostId": record["extra"].get("host_id", "local"),
                "prompt": f"{self._marker(request.wake_attempt_id)} Read your Tsunagou project context and "
                          "pending coordination inbox using its MCP tools, present/ACK the messages, "
                          "then handle them under your current role and task scope. "
                          "This notification contains no task instructions or new permissions.",
            })
        finally:
            client.close()
        self._record(request.binding)
        return replace(attempt, state="starting", evidence=attempt.evidence + (self._evidence("host_accepted", request),))

    def _failure(self, request: HostWakeRequest, exc: HostWakeError) -> WakeAttempt:
        unknown = exc.code in {
            "desktop_request_timeout", "desktop_connection_lost", "host_binding_changed",
            "desktop_response_invalid", "desktop_tool_result_invalid",
        }
        return WakeAttempt(
            request.wake_attempt_id, request.agent_id, request.message_id, "unknown" if unknown else "failed",
            thread_id_digest=request.binding.thread_id_digest,
            evidence=(self._evidence("wake_unknown" if unknown else "wake_failed", request, error_code=exc.code),),
            error_code=exc.code, error_message=str(exc),
        )

    def _read_failure(self, request: HostWakeRequest, attempt: WakeAttempt, exc: HostWakeError) -> WakeAttempt:
        failure = self._failure(request, exc)
        if attempt.state == "queued" and failure.state == "unknown":
            # No send was attempted: keep the queued intent eligible after a
            # connection refresh. Do not confuse this with a lost send reply.
            return replace(attempt, error_code=exc.code, error_message=str(exc),
                           evidence=attempt.evidence + failure.evidence)
        return replace(failure, evidence=attempt.evidence + failure.evidence)

    def restore_attempt(self, request: HostWakeRequest, state: str) -> None:
        # A possibly accepted request is observed first. Only a durably queued
        # request, which has not been sent, is eligible for a fresh send.
        with self._lock:
            self._pending.setdefault(request.wake_attempt_id, (request, WakeAttempt(
                request.wake_attempt_id, request.agent_id, request.message_id,
                "queued" if state == "queued" else "unknown",
                thread_id_digest=request.binding.thread_id_digest,
            )))

    def poll(self, wake_attempt_id: str) -> WakeAttempt | None:
        with self._lock:
            pending = self._pending.get(wake_attempt_id)
        if pending is None:
            return None
        request, attempt = pending
        if attempt.state in {"completed", "failed"}:
            return attempt
        current = self.store.get(request.agent_id)
        if current is not None and current[0].binding_revision != request.binding.binding_revision:
            new_binding = current[0]
            if (new_binding.thread_id_digest, new_binding.scope_digest, new_binding.policy_digest) == (
                request.binding.thread_id_digest, request.binding.scope_digest, request.binding.policy_digest,
            ):
                request = replace(request, binding=new_binding, connection_epoch=new_binding.connection_epoch)
        try:
            # Native Desktop follow-ups arrive as an application-tool output.
            # Without includeOutputs its initiating input is omitted entirely.
            view = self._read(request.binding, include_outputs=attempt.state != "queued")
            if attempt.state == "queued":
                if not self._busy(view):
                    try:
                        attempt = self._send(request, attempt)
                    except HostWakeError as exc:
                        attempt = self._failure(request, exc)
            else:
                marker = self._marker(wake_attempt_id)
                matching = next((turn for turn in view.get("turns", []) if any(
                    self._is_wake_input(item, marker) for item in turn.get("items", [])
                )), None)
                if matching is not None:
                    status = matching.get("status")
                    state: WakeState = (
                        "completed" if status == "completed" else "failed" if status in {"failed", "interrupted"} else "running"
                    )
                    evidence = list(attempt.evidence)
                    if not any(e.kind == "turn_started" for e in evidence):
                        evidence.append(self._evidence("turn_started", request, host_started_at=matching.get("startedAt")))
                    if state in {"completed", "failed"}:
                        evidence.append(self._evidence("turn_completed" if state == "completed" else "wake_failed", request,
                                                       host_completed_at=matching.get("completedAt")))
                    attempt = replace(attempt, state=state, evidence=tuple(evidence),
                                      turn_id_digest=canonical_digest({"turn_id": matching["id"]}),
                                      error_code="desktop_turn_failed" if state == "failed" else None,
                                      error_message=None, updated_at=cast(str, format_timestamp(now_ms())))
        except HostWakeError as exc:
            attempt = self._read_failure(request, attempt, exc)
        with self._lock:
            self._pending[wake_attempt_id] = (request, attempt)
        return attempt

    def inspect(self, binding: HostBindingRef) -> dict[str, Any]:
        view = self._read(binding)
        return {"provider": self.provider_name, "thread_id_digest": binding.thread_id_digest,
                "status": view["thread"].get("status"), "binding_revision": binding.binding_revision}

    def close(self, binding: HostBindingRef, reason: str) -> None:
        self.store.update_status(binding.agent_id, "detached", reason=reason)
