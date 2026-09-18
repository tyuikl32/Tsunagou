"""Side-effect-free HTTP application factory."""

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict

from tsunagou import __version__


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: str
    version: str


def create_app() -> FastAPI:
    app = FastAPI(title="Tsunagou", version=__version__, docs_url=None, redoc_url=None)

    @app.get("/api/v1/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok", version=__version__)

    return app
