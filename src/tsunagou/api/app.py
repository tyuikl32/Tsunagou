"""Side-effect-free HTTP application factory."""

from importlib.resources import files
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from tsunagou import __version__
from tsunagou.api.a2a import A2AGateway, http_push_notifier
from tsunagou.api.auth import LocalCommandAuthenticator
from tsunagou.interfaces.runtime import CommandDispatcher
from tsunagou.shared_kernel.errors import IdempotencyConflict, LockUnavailable, RevisionConflict
from tsunagou.shared_kernel.ids import new_id


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: str
    version: str


class CommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: str
    protocol_version: str
    schema_bundle_digest: str
    payload: dict[str, Any] = Field(default_factory=dict)


class HostBindingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    provider: Literal["managed_app_server", "desktop_attach"] = "managed_app_server"
    adapter_profile: str
    cwd: str
    scope_digest: str
    policy_digest: str
    executable: str | None = None
    model: str | None = None
    approval_policy: str | None = None
    sandbox: str | None = None
    sandbox_policy: dict[str, Any] | None = None
    bridge_config: str | None = None
    endpoint: str | None = None
    thread_id: str | None = None
    attach_confirmed: bool = False


def create_app(
    dispatcher: CommandDispatcher | None = None,
    *, authenticator: LocalCommandAuthenticator | None = None,
    query_provider: Any | None = None,
    push_notifier: Any | None = http_push_notifier,
    wake_dispatcher: Any | None = None,
    hostwake_provider: Any | None = None,
) -> FastAPI:
    app = FastAPI(title="Tsunagou", version=__version__, docs_url=None, redoc_url=None)
    if dispatcher is None:
        registry = Path(str(files("tsunagou.protocol_data").joinpath("registry", "commands.json")))
        dispatcher = CommandDispatcher(registry)
    if authenticator is None:
        authenticator = LocalCommandAuthenticator()
    a2a_gateway = A2AGateway(
        dispatcher,
        authenticator,
        project_id=getattr(getattr(dispatcher, "database", None), "project_id", None),
        query_provider=query_provider,
        push_notifier=push_notifier,
        wake_dispatcher=wake_dispatcher,
    )
    app.state.a2a_gateway = a2a_gateway
    app.state.wake_dispatcher = wake_dispatcher
    app.state.hostwake_provider = hostwake_provider

    @app.on_event("shutdown")
    def release_runtime_lock() -> None:
        database = getattr(dispatcher, "database", None)
        if database is not None:
            database.release_process_lock()

    @app.get("/api/v1/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok", version=__version__)

    @app.get("/.well-known/agent-card.json")
    def agent_card(request: Request) -> dict[str, Any]:
        endpoint = f"{str(request.base_url).rstrip('/')}/api/v1/a2a"
        return a2a_gateway.agent_card(endpoint)

    @app.post("/api/v1/a2a")
    def a2a_command(
        request: dict[str, Any],
        authorization: str | None = Header(default=None, alias="Authorization"),
        session_id: str | None = Header(default=None, alias="Tsunagou-Session-Id"),
        connection_epoch: int | None = Header(default=None, alias="Tsunagou-Connection-Epoch"),
    ) -> dict[str, Any]:
        return a2a_gateway.dispatch(
            request,
            authorization=authorization,
            session_id=session_id,
            connection_epoch=connection_epoch,
        )

    @app.post("/api/v1/a2a/agents/{recipient_agent_id}")
    def a2a_agent_command(
        recipient_agent_id: str,
        request: dict[str, Any],
        authorization: str | None = Header(default=None, alias="Authorization"),
        session_id: str | None = Header(default=None, alias="Tsunagou-Session-Id"),
        connection_epoch: int | None = Header(default=None, alias="Tsunagou-Connection-Epoch"),
    ) -> dict[str, Any]:
        return a2a_gateway.dispatch(
            request,
            authorization=authorization,
            session_id=session_id,
            connection_epoch=connection_epoch,
            recipient_agent_id=recipient_agent_id,
        )

    @app.post("/api/v1/commands/{command_kind}")
    def command(
        command_kind: str, request: CommandRequest, response: Response,
        authorization: str | None = Header(default=None, alias="Authorization"),
        session_id: str | None = Header(default=None, alias="Tsunagou-Session-Id"),
        connection_epoch: int | None = Header(default=None, alias="Tsunagou-Connection-Epoch"),
    ) -> dict[str, Any]:
        try:
            policy = dispatcher.registry.get(command_kind)
            if policy is None:
                raise KeyError("unknown_command")
            principal = authenticator.authenticate(
                policy["principal"], authorization,
                session_id=session_id, connection_epoch=connection_epoch,
            )
            dispatched = dispatcher.dispatch(
                command_kind, request.model_dump(), principal=principal,
            )
            if command_kind == "inbox.presented" and wake_dispatcher is not None:
                payload = request.payload
                try:
                    wake_dispatcher.record_presented(
                        agent_id=principal.principal_id,
                        message_id=str(payload.get("message_id", "")),
                        evidence_digest=payload.get("evidence_digest"),
                        evidence_kind=payload.get("evidence_kind"),
                    )
                except Exception:
                    # Presentation evidence is an enhancement record.  The
                    # committed inbox command must remain successful even if
                    # the private host-wake journal is temporarily unavailable.
                    pass
        except PermissionError as exc:
            code = str(exc)
            raise HTTPException(
                status_code=401 if code == "authentication_failed" else 403,
                detail={"code": code},
            ) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"code": str(exc)}) from exc
        except IdempotencyConflict as exc:
            raise HTTPException(status_code=409, detail={"code": exc.code}) from exc
        except RevisionConflict as exc:
            raise HTTPException(status_code=409, detail={"code": str(exc)}) from exc
        except LockUnavailable as exc:
            raise HTTPException(status_code=503, detail={"code": exc.code}) from exc
        except RuntimeError as exc:
            # A command whose runtime dependency is not assembled is an
            # unavailable service capability, not an opaque HTTP 500.
            raise HTTPException(status_code=503, detail={"code": str(exc)}) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"code": str(exc)}) from exc
        response.headers["ETag"] = dispatched.command_hash
        return {"command_hash": dispatched.command_hash, "result": dispatched.result}

    @app.post("/api/v1/host-wake/bindings")
    def host_wake_bind(
        request: HostBindingRequest,
        authorization: str | None = Header(default=None, alias="Authorization"),
        session_id: str | None = Header(default=None, alias="Tsunagou-Session-Id"),
        connection_epoch: int | None = Header(default=None, alias="Tsunagou-Connection-Epoch"),
    ) -> dict[str, Any]:
        try:
            authenticator.authenticate("U", authorization, session_id=session_id, connection_epoch=connection_epoch)
            if query_provider is not None:
                project_id = str(getattr(getattr(dispatcher, "database", None), "project_id", ""))
                agent_view = query_provider("agents", project_id)
                enrolled = any(
                    isinstance(item, dict)
                    and item.get("agent_id") == request.agent_id
                    and item.get("status") == "active"
                    for item in agent_view.get("items", [])
                ) if isinstance(agent_view, dict) else False
                if not enrolled:
                    raise PermissionError("host_agent_not_enrolled")
            provider = getattr(app.state, "hostwake_provider", None)
            if provider is None or not hasattr(provider, "register_binding"):
                raise RuntimeError("host_wake_not_configured")
            ref = provider.register_binding(
                provider=request.provider,
                agent_id=request.agent_id,
                binding_id=f"binding:{new_id()}",
                adapter_profile=request.adapter_profile,
                cwd=request.cwd,
                scope_digest=request.scope_digest,
                policy_digest=request.policy_digest,
                executable=request.executable,
                model=request.model,
                approval_policy=request.approval_policy,
                sandbox=request.sandbox,
                sandbox_policy=request.sandbox_policy,
                bridge_config=request.bridge_config,
                endpoint=request.endpoint,
                thread_id=request.thread_id,
                attach_confirmed=request.attach_confirmed,
            )
            return {"binding": ref.__dict__ if hasattr(ref, "__dict__") else {
                "binding_id": ref.binding_id, "agent_id": ref.agent_id,
                "provider": ref.provider, "adapter_profile": ref.adapter_profile,
                "thread_id_digest": ref.thread_id_digest, "session_id_digest": ref.session_id_digest,
                "endpoint_kind": ref.endpoint_kind, "cwd_digest": ref.cwd_digest,
                "scope_digest": ref.scope_digest, "policy_digest": ref.policy_digest,
                "status": ref.status, "binding_revision": ref.binding_revision,
                "connection_epoch": ref.connection_epoch, "capabilities": ref.capabilities,
                "last_probe": ref.last_probe,
            }}
        except PermissionError as exc:
            code = str(exc)
            raise HTTPException(status_code=401 if code == "authentication_failed" else 403,
                                detail={"code": code}) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail={"code": str(exc)}) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"code": str(exc)}) from exc

    @app.get("/api/v1/host-wake/bindings/{agent_id}")
    def host_wake_binding(
        agent_id: str,
        authorization: str | None = Header(default=None, alias="Authorization"),
        session_id: str | None = Header(default=None, alias="Tsunagou-Session-Id"),
        connection_epoch: int | None = Header(default=None, alias="Tsunagou-Connection-Epoch"),
    ) -> dict[str, Any]:
        try:
            authenticator.authenticate("U", authorization, session_id=session_id, connection_epoch=connection_epoch)
            provider = getattr(app.state, "hostwake_provider", None)
            if provider is None:
                raise RuntimeError("host_wake_not_configured")
            store = getattr(provider, "store", None)
            item = store.get(agent_id) if store is not None else None
            if item is None:
                raise KeyError("host_binding_not_found")
            ref, _record = item
            return {"binding": {
                "binding_id": ref.binding_id, "agent_id": ref.agent_id,
                "provider": ref.provider, "adapter_profile": ref.adapter_profile,
                "thread_id_digest": ref.thread_id_digest, "session_id_digest": ref.session_id_digest,
                "endpoint_kind": ref.endpoint_kind, "cwd_digest": ref.cwd_digest,
                "scope_digest": ref.scope_digest, "policy_digest": ref.policy_digest,
                "status": ref.status, "binding_revision": ref.binding_revision,
                "connection_epoch": ref.connection_epoch, "capabilities": ref.capabilities,
                "last_probe": ref.last_probe,
            }}
        except PermissionError as exc:
            code = str(exc)
            raise HTTPException(status_code=401 if code == "authentication_failed" else 403,
                                detail={"code": code}) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"code": str(exc)}) from exc

    @app.post("/api/v1/host-wake/bindings/{agent_id}:probe")
    def host_wake_probe(
        agent_id: str,
        authorization: str | None = Header(default=None, alias="Authorization"),
        session_id: str | None = Header(default=None, alias="Tsunagou-Session-Id"),
        connection_epoch: int | None = Header(default=None, alias="Tsunagou-Connection-Epoch"),
    ) -> dict[str, Any]:
        try:
            authenticator.authenticate("U", authorization, session_id=session_id, connection_epoch=connection_epoch)
            provider = getattr(app.state, "hostwake_provider", None)
            if provider is None:
                raise RuntimeError("host_wake_not_configured")
            store = getattr(provider, "store", None)
            item = store.get(agent_id) if store is not None else None
            if item is None:
                raise KeyError("host_binding_not_found")
            ref, _record = item
            report = provider.probe(ref)
            return {"provider": report.provider, "status": report.status, "version": report.version,
                    "transport": report.transport, "methods": list(report.methods),
                    "capabilities": report.capabilities, "evidence_digest": report.evidence_digest,
                    "reason": report.reason, "observed_at": report.observed_at}
        except PermissionError as exc:
            code = str(exc)
            raise HTTPException(status_code=401 if code == "authentication_failed" else 403,
                                detail={"code": code}) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"code": str(exc)}) from exc

    @app.get("/api/v1/host-wake/attempts/{attempt_id}")
    def host_wake_attempt(
        attempt_id: str,
        authorization: str | None = Header(default=None, alias="Authorization"),
        session_id: str | None = Header(default=None, alias="Tsunagou-Session-Id"),
        connection_epoch: int | None = Header(default=None, alias="Tsunagou-Connection-Epoch"),
    ) -> dict[str, Any]:
        try:
            authenticator.authenticate("U", authorization, session_id=session_id, connection_epoch=connection_epoch)
            dispatcher_state = getattr(app.state, "wake_dispatcher", None)
            attempts = getattr(dispatcher_state, "attempts", {})
            for item in attempts.values():
                if item.get("wake_attempt_id") == attempt_id:
                    return {"attempt": item}
            raise KeyError("host_wake_attempt_not_found")
        except PermissionError as exc:
            code = str(exc)
            raise HTTPException(status_code=401 if code == "authentication_failed" else 403,
                                detail={"code": code}) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"code": str(exc)}) from exc

    @app.get("/api/v1/projects/{project_id}/tasks")
    def project_tasks(project_id: str) -> dict[str, Any]:
        if query_provider is None:
            return {"project_id": project_id, "items": []}
        try:
            return query_provider("tasks", project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"code": str(exc)}) from exc

    @app.get("/api/v1/projects/{project_id}/attempts")
    def project_attempts(project_id: str) -> dict[str, Any]:
        if query_provider is None:
            return {"project_id": project_id, "items": []}
        try:
            return query_provider("attempts", project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"code": str(exc)}) from exc

    @app.get("/api/v1/projects/{project_id}/results")
    def project_results(project_id: str) -> dict[str, Any]:
        if query_provider is None:
            return {"project_id": project_id, "items": []}
        try:
            return query_provider("results", project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"code": str(exc)}) from exc

    @app.get("/api/v1/projects/{project_id}/jobs")
    def project_jobs(project_id: str) -> dict[str, Any]:
        if query_provider is None:
            return {"project_id": project_id, "items": []}
        try:
            return query_provider("jobs", project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"code": str(exc)}) from exc

    @app.get("/api/v1/projects/{project_id}/roots")
    def project_roots(project_id: str) -> dict[str, Any]:
        if query_provider is None:
            return {"project_id": project_id, "items": []}
        try:
            return query_provider("roots", project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"code": str(exc)}) from exc

    @app.get("/api/v1/projects/{project_id}/repositories")
    def project_repositories(project_id: str) -> dict[str, Any]:
        if query_provider is None:
            return {"project_id": project_id, "items": []}
        try:
            return query_provider("repositories", project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"code": str(exc)}) from exc

    @app.get("/api/v1/projects/{project_id}/contracts")
    def project_contracts(project_id: str) -> dict[str, Any]:
        if query_provider is None:
            return {"items": []}
        try:
            return query_provider("contracts", project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"code": str(exc)}) from exc

    @app.get("/api/v1/projects/{project_id}/cognition")
    def project_cognition(project_id: str) -> dict[str, Any]:
        if query_provider is None:
            return {"reports": [], "discrepancies": [], "contracts": []}
        try:
            return query_provider("cognition", project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"code": str(exc)}) from exc

    @app.get("/api/v1/projects/{project_id}/agents")
    def project_agents(project_id: str) -> dict[str, Any]:
        if query_provider is None:
            return {"items": []}
        try:
            return query_provider("agents", project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"code": str(exc)}) from exc

    @app.get("/api/v1/projects/{project_id}/messages")
    def project_messages(project_id: str) -> dict[str, Any]:
        if query_provider is None:
            return {"items": []}
        try:
            return query_provider("messages", project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"code": str(exc)}) from exc

    @app.get("/api/v1/projects/{project_id}/resources")
    def project_resources(project_id: str) -> dict[str, Any]:
        if query_provider is None:
            return {"items": []}
        try:
            return query_provider("resources", project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"code": str(exc)}) from exc

    @app.get("/api/v1/projects/{project_id}/workspaces")
    def project_workspaces(project_id: str) -> dict[str, Any]:
        if query_provider is None:
            return {"items": []}
        try:
            return query_provider("workspaces", project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"code": str(exc)}) from exc

    @app.get("/api/v1/projects/{project_id}/audit")
    def project_audit(project_id: str) -> dict[str, Any]:
        if query_provider is None:
            return {"project_id": project_id, "items": [], "next_cursor": None}
        try:
            return query_provider("audit", project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"code": str(exc)}) from exc

    @app.get("/api/v1/decisions")
    def decisions() -> dict[str, Any]:
        if query_provider is None:
            return {"items": []}
        return query_provider("decisions", "")

    @app.get("/api/v1/operations/{operation_id}")
    def operation(operation_id: str) -> dict[str, Any]:
        if query_provider is None:
            raise HTTPException(status_code=404, detail={"code": "operation_not_found"})
        result = query_provider("operations", "")
        for item in result.get("items", []):
            if item.get("id") == operation_id:
                return item
        raise HTTPException(status_code=404, detail={"code": "operation_not_found"})

    @app.get("/api/v1/checkpoints")
    def checkpoints() -> dict[str, Any]:
        if query_provider is None:
            return {"items": []}
        return query_provider("checkpoints", "")

    @app.get("/api/v1/artifacts/{artifact_ref:path}")
    def artifact(artifact_ref: str) -> dict[str, Any]:
        if query_provider is None:
            raise HTTPException(status_code=404, detail={"code": "artifact_not_found"})
        try:
            return query_provider("artifact", artifact_ref)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"code": str(exc)}) from exc

    @app.get("/api/v1/recovery")
    def recovery() -> dict[str, Any]:
        if query_provider is None:
            return {"status": "ready"}
        return query_provider("recovery", "")

    return app
