"""Side-effect-free HTTP application factory."""

from importlib.resources import files
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from tsunagou import __version__
from tsunagou.api.a2a import A2AGateway
from tsunagou.api.auth import LocalCommandAuthenticator
from tsunagou.interfaces.runtime import CommandDispatcher
from tsunagou.shared_kernel.errors import IdempotencyConflict, LockUnavailable, RevisionConflict


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


def create_app(
    dispatcher: CommandDispatcher | None = None,
    *, authenticator: LocalCommandAuthenticator | None = None,
    query_provider: Any | None = None,
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
    )
    app.state.a2a_gateway = a2a_gateway

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
