"""Side-effect-free HTTP application factory."""

from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from tsunagou import __version__
from tsunagou.interfaces.runtime import CommandDispatcher


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


def create_app(dispatcher: CommandDispatcher | None = None) -> FastAPI:
    app = FastAPI(title="Tsunagou", version=__version__, docs_url=None, redoc_url=None)
    if dispatcher is None:
        registry = Path(__file__).resolve().parents[3] / "protocol" / "registry" / "commands.json"
        dispatcher = CommandDispatcher(registry)

    @app.get("/api/v1/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok", version=__version__)

    @app.post("/api/v1/commands/{command_kind}")
    def command(
        command_kind: str, request: CommandRequest, response: Response,
        x_principal_kind: str = Header(alias="X-Principal-Kind"),
        x_principal_id: str = Header(alias="X-Principal-Id"),
    ) -> dict[str, Any]:
        try:
            dispatched = dispatcher.dispatch(
                command_kind, request.model_dump(), principal_kind=x_principal_kind,
                principal_id=x_principal_id,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail={"code": str(exc)}) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"code": str(exc)}) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"code": str(exc)}) from exc
        response.headers["ETag"] = dispatched.command_hash
        return {"command_hash": dispatched.command_hash, "result": dispatched.result}

    return app
