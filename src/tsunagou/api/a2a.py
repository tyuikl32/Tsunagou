"""A small, authenticated A2A boundary over the Tsunagou runtime.

The gateway is deliberately an adapter: durable messages and task state still
go through the existing dispatcher/query ports. It does not create a second
task store or treat a caller supplied actor field as identity.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from tsunagou import __version__
from tsunagou.api.auth import LocalCommandAuthenticator
from tsunagou.interfaces.runtime import CommandDispatcher, PrincipalContext
from tsunagou.shared_kernel.digests import canonical_digest
from tsunagou.shared_kernel.errors import TsunagouError

A2A_PROTOCOL_VERSION = "1.0"
JSON_RPC_VERSION = "2.0"
_SUPPORTED_METHODS = frozenset({"message/send", "tasks/get", "tasks/cancel", "tasks/fail", "tasks/retry"})
_MAIN_METHODS = frozenset({"tasks/cancel", "tasks/retry"})


class A2AProtocolError(ValueError):
    """A request that cannot be represented by the local A2A profile."""

    def __init__(self, code: str, message: str, *, rpc_code: int = -32602) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.rpc_code = rpc_code


def _rpc_error(request_id: Any, error: A2AProtocolError) -> dict[str, Any]:
    return {
        "jsonrpc": JSON_RPC_VERSION,
        "id": request_id,
        "error": {
            "code": error.rpc_code,
            "message": error.message,
            "data": {"code": error.code},
        },
    }


def _rpc_result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": JSON_RPC_VERSION, "id": request_id, "result": result}


def _text_parts(message: dict[str, Any]) -> str:
    parts = message.get("parts")
    if not isinstance(parts, list) or not parts:
        raise A2AProtocolError("message_parts_required", "message.parts must contain at least one part")
    text: list[str] = []
    for part in parts:
        if not isinstance(part, dict):
            raise A2AProtocolError("message_part_invalid", "message.parts entries must be objects")
        value = part.get("text")
        if isinstance(value, str) and value:
            text.append(value)
    if not text:
        raise A2AProtocolError("message_text_required", "the local profile requires a text part")
    return "\n".join(text)


def _tsunagou_metadata(message: dict[str, Any]) -> dict[str, Any]:
    metadata = message.get("metadata", {})
    if metadata is None:
        return {}
    if not isinstance(metadata, dict):
        raise A2AProtocolError("message_metadata_invalid", "message.metadata must be an object")
    extension = metadata.get("tsunagou", {})
    if extension is None:
        return {}
    if not isinstance(extension, dict):
        raise A2AProtocolError("tsunagou_metadata_invalid", "metadata.tsunagou must be an object")
    return extension


def _a2a_task_state(status: str) -> str:
    if status in {"completed", "accepted"}:
        return "completed"
    if status in {"failed", "cancelled", "canceled"}:
        return "failed" if status == "failed" else "canceled"
    if status in {"blocked", "input_required"}:
        return "input-required"
    if status in {"draft", "ready", "open", "claimed"}:
        return "submitted"
    return "working"


class A2AGateway:
    """Translate a minimal A2A profile into existing authenticated ports."""

    def __init__(
        self,
        dispatcher: CommandDispatcher,
        authenticator: LocalCommandAuthenticator,
        *,
        project_id: str | None = None,
        query_provider: Callable[[str, str], dict[str, Any]] | None = None,
    ) -> None:
        self.dispatcher = dispatcher
        self.authenticator = authenticator
        self.project_id = project_id
        self.query_provider = query_provider

    def agent_card(self, endpoint: str) -> dict[str, Any]:
        """Return a truthful, secret-free A2A Agent Card."""
        return {
            "name": "Tsunagou Coordination Agent",
            "description": "Authenticated local Agent-to-Agent coordination boundary.",
            "version": __version__,
            "protocolVersion": A2A_PROTOCOL_VERSION,
            "url": endpoint,
            "supportedInterfaces": [
                {"url": endpoint, "protocolBinding": "JSONRPC", "protocolVersion": A2A_PROTOCOL_VERSION},
            ],
            "capabilities": {
                "streaming": False,
                "pushNotifications": False,
                "stateTransitionHistory": False,
            },
            "defaultInputModes": ["text/plain", "application/json"],
            "defaultOutputModes": ["text/plain", "application/json"],
            "skills": [
                {
                    "id": "agent-coordination",
                    "name": "Agent coordination",
                    "description": "Send structured messages, query task progress, and record task transitions.",
                    "tags": ["coordination", "messages", "tasks", "cancellation", "recovery"],
                },
            ],
            "authentication": {"schemes": ["Bearer"]},
            "x-tsunagou": {
                "project_id": self.project_id,
                "internal_source_of_truth": "project-runtime",
                "wake": "unsupported",
                "delivery": "durable-pull-or-client-poll",
                "methods": sorted(_SUPPORTED_METHODS),
            },
        }

    def dispatch(
        self,
        request: dict[str, Any],
        *,
        authorization: str | None,
        session_id: str | None,
        connection_epoch: int | None,
        recipient_agent_id: str | None = None,
    ) -> dict[str, Any]:
        request_id = request.get("id")
        if request.get("jsonrpc") != JSON_RPC_VERSION:
            return _rpc_error(request_id, A2AProtocolError(
                "jsonrpc_version_unsupported", "A2A requests must use JSON-RPC 2.0", rpc_code=-32600,
            ))
        method = request.get("method")
        if method not in _SUPPORTED_METHODS:
            return _rpc_error(request_id, A2AProtocolError(
                "a2a_method_not_supported", f"A2A method is not supported: {method}", rpc_code=-32601,
            ))
        params = request.get("params")
        if not isinstance(params, dict):
            return _rpc_error(request_id, A2AProtocolError(
                "params_object_required", "A2A params must be an object",
            ))
        try:
            principal_kind = "M" if method in _MAIN_METHODS else "B"
            principal = self.authenticator.authenticate(
                principal_kind, authorization, session_id=session_id, connection_epoch=connection_epoch,
            )
            if method == "message/send":
                result = self._message_send(params, principal, recipient_agent_id)
            elif method == "tasks/get":
                result = self._tasks_get(params, principal)
            elif method == "tasks/cancel":
                result = self._task_transition(params, principal, "task.cancel_request", request_id)
            elif method == "tasks/fail":
                result = self._task_transition(params, principal, "task.fail", request_id)
            else:
                result = self._task_transition(params, principal, "task.recover", request_id)
            return _rpc_result(request_id, result)
        except A2AProtocolError as exc:
            return _rpc_error(request_id, exc)
        except PermissionError as exc:
            code = str(exc)
            return _rpc_error(request_id, A2AProtocolError(
                code, "authenticated A2A action was denied", rpc_code=-32003,
            ))
        except KeyError as exc:
            return _rpc_error(request_id, A2AProtocolError(
                str(exc), "A2A target was not found", rpc_code=-32004,
            ))
        except TsunagouError as exc:
            return _rpc_error(request_id, A2AProtocolError(
                getattr(exc, "code", "tsunagou_error"), "A2A action was rejected by the project runtime", rpc_code=-32009,
            ))
        except ValueError as exc:
            code = "idempotency_conflict" if str(exc) == "command_id_conflict" else str(exc)
            return _rpc_error(request_id, A2AProtocolError(
                code, "A2A request was rejected", rpc_code=-32000,
            ))

    def _message_send(
        self, params: dict[str, Any], principal: PrincipalContext, route_recipient: str | None,
    ) -> dict[str, Any]:
        message = params.get("message")
        if not isinstance(message, dict):
            raise A2AProtocolError("message_required", "message/send requires params.message")
        message_id = message.get("messageId")
        if not isinstance(message_id, str) or not message_id.strip():
            raise A2AProtocolError("message_id_required", "message.messageId is required")
        if len(message_id) > 128:
            raise A2AProtocolError("message_id_too_long", "message.messageId must be at most 128 characters")
        context_id = message.get("contextId")
        if context_id is not None and not isinstance(context_id, str):
            raise A2AProtocolError("context_id_invalid", "message.contextId must be a string")
        if isinstance(context_id, str) and len(context_id) > 128:
            raise A2AProtocolError("context_id_too_long", "message.contextId must be at most 128 characters")
        metadata = _tsunagou_metadata(message)
        recipient = route_recipient or metadata.get("recipient_agent_id")
        if not isinstance(recipient, str) or not recipient.strip():
            raise A2AProtocolError(
                "recipient_agent_id_required",
                "the local profile requires metadata.tsunagou.recipient_agent_id or a routed agent path",
            )
        if len(recipient) > 128:
            raise A2AProtocolError("recipient_agent_id_too_long", "recipient agent ID must be at most 128 characters")
        if route_recipient is not None and metadata.get("recipient_agent_id") not in {None, route_recipient}:
            raise A2AProtocolError("recipient_conflict", "routed recipient and metadata recipient differ")
        expected_project = metadata.get("project_id")
        if expected_project is not None and expected_project != self.project_id:
            raise A2AProtocolError("project_scope_denied", "A2A message targets another project", rpc_code=-32003)
        summary = _text_parts(message)
        payload = metadata.get("payload", {})
        if not isinstance(payload, dict):
            raise A2AProtocolError("payload_invalid", "metadata.tsunagou.payload must be an object")
        kind = metadata.get("kind", "message")
        if not isinstance(kind, str) or not kind:
            raise A2AProtocolError("message_kind_invalid", "metadata.tsunagou.kind must be a non-empty string")
        subject_ref = metadata.get("subject_ref", context_id or "a2a")
        if not isinstance(subject_ref, str):
            raise A2AProtocolError("subject_ref_invalid", "metadata.tsunagou.subject_ref must be a string")
        response_contract = metadata.get("response_contract")
        if response_contract is not None and not isinstance(response_contract, dict):
            raise A2AProtocolError("response_contract_invalid", "metadata.tsunagou.response_contract must be an object")
        in_reply_to = metadata.get("in_reply_to")
        if in_reply_to is not None and not isinstance(in_reply_to, str):
            raise A2AProtocolError("in_reply_to_invalid", "metadata.tsunagou.in_reply_to must be a string")
        command_id = f"a2a:message:{message_id}"
        envelope = {
            "command_id": command_id,
            "protocol_version": self.dispatcher.protocol_version,
            "schema_bundle_digest": self.dispatcher.schema_bundle_digest or "sha256:x",
            "payload": {
                "recipient_agent_id": recipient,
                "kind": kind,
                "subject_ref": subject_ref,
                "summary": summary,
                "payload": {
                    **payload,
                    "a2a": {
                        "message_id": message_id,
                        "context_id": context_id,
                        "role": message.get("role"),
                        "parts": message.get("parts"),
                        "metadata": metadata,
                    },
                },
                "priority": self._priority(metadata.get("priority", 0)),
                **({"response_contract": response_contract} if response_contract is not None else {}),
                **({"in_reply_to": in_reply_to} if in_reply_to is not None else {}),
            },
        }
        dispatched = self.dispatcher.dispatch("message.send", envelope, principal=principal)
        result = dispatched.result
        internal_message_id = str(result["message_id"])
        response_message = {
            "messageId": internal_message_id,
            "contextId": context_id or self.project_id,
            "role": "agent",
            "parts": [{"text": "Message accepted by Tsunagou durable delivery."}],
            "metadata": {
                "tsunagou": {
                    "project_id": self.project_id,
                    "message_id": internal_message_id,
                    "delivery": "pending",
                    "wake": "unsupported",
                },
            },
        }
        return {"message": response_message}

    @staticmethod
    def _priority(value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise A2AProtocolError("priority_invalid", "metadata.tsunagou.priority must be an integer")
        return int(value)

    @staticmethod
    def _task_id(params: dict[str, Any]) -> str:
        value = params.get("id")
        if not isinstance(value, str) or not value:
            raise A2AProtocolError("task_id_required", "task operation requires params.id")
        prefix = "tsunagou:task:"
        return value[len(prefix):] if value.startswith(prefix) else value

    def _task_transition(
        self, params: dict[str, Any], principal: PrincipalContext,
        command_kind: str, request_id: Any,
    ) -> dict[str, Any]:
        task_id = self._task_id(params)
        metadata = params.get("metadata", {})
        if metadata is None:
            metadata = {}
        if not isinstance(metadata, dict):
            raise A2AProtocolError("task_metadata_invalid", "task operation metadata must be an object")
        extension = metadata.get("tsunagou", {})
        if extension is None:
            extension = {}
        if not isinstance(extension, dict):
            raise A2AProtocolError("tsunagou_metadata_invalid", "metadata.tsunagou must be an object")
        reason = params.get("reason") or extension.get("reason") or "a2a_task_transition"
        if not isinstance(reason, str) or not reason.strip():
            raise A2AProtocolError("task_reason_required", "task transition reason must be a string")
        payload: dict[str, Any] = {"task_id": task_id, "reason": reason}
        if command_kind == "task.fail":
            attempt_id = params.get("attemptId") or extension.get("attempt_id")
            if not isinstance(attempt_id, str) or not attempt_id:
                raise A2AProtocolError("attempt_id_required", "tasks/fail requires params.attemptId")
            payload["attempt_id"] = attempt_id
            stop_evidence = params.get("stopEvidence") or extension.get("stop_evidence") or {}
            if not isinstance(stop_evidence, dict):
                raise A2AProtocolError("stop_evidence_invalid", "stopEvidence must be an object")
            payload["stop_evidence"] = stop_evidence
            payload["evidence_refs"] = list(extension.get("evidence_refs") or [])
        elif command_kind == "task.recover":
            expected_attempt_id = params.get("attemptId") or extension.get("expected_attempt_id")
            if not isinstance(expected_attempt_id, str) or not expected_attempt_id:
                raise A2AProtocolError("attempt_id_required", "tasks/retry requires params.attemptId")
            payload["expected_attempt_id"] = expected_attempt_id
            payload["disposition"] = "reopen"
        command_suffix = str(request_id) if request_id is not None else "anonymous"
        envelope = {
            "command_id": f"a2a:{command_kind}:{task_id}:{command_suffix}",
            "protocol_version": self.dispatcher.protocol_version,
            "schema_bundle_digest": self.dispatcher.schema_bundle_digest or "sha256:x",
            "payload": payload,
        }
        dispatched = self.dispatcher.dispatch(command_kind, envelope, principal=principal)
        result = dispatched.result
        status = str(result.get("status", "working"))
        return {
            "id": f"tsunagou:task:{task_id}",
            "contextId": self.project_id,
            "status": {"state": _a2a_task_state(status)},
            "metadata": {
                "tsunagou": {
                    "task_id": task_id,
                    "transition": command_kind,
                    "revision": result.get("revision"),
                },
            },
        }

    def _tasks_get(self, params: dict[str, Any], principal: PrincipalContext) -> dict[str, Any]:
        del principal  # authentication is still required; visibility is query-provider scoped.
        task_id = params.get("id")
        if not isinstance(task_id, str) or not task_id:
            raise A2AProtocolError("task_id_required", "tasks/get requires params.id")
        prefix = "tsunagou:task:"
        internal_id = task_id[len(prefix):] if task_id.startswith(prefix) else task_id
        if self.query_provider is None:
            raise A2AProtocolError("task_query_unavailable", "task query is not assembled", rpc_code=-32005)
        view = self.query_provider("tasks", self.project_id or "")
        item = next((candidate for candidate in view.get("items", []) if candidate.get("task_id") == internal_id), None)
        if item is None:
            raise A2AProtocolError("task_not_found", "A2A task is not visible", rpc_code=-32004)
        digest = canonical_digest(item)
        return {
            "id": f"{prefix}{internal_id}",
            "contextId": self.project_id,
            "status": {"state": _a2a_task_state(str(item.get("status", "unknown")))},
            "metadata": {"tsunagou": {"task_id": internal_id, "source_digest": digest}},
        }
