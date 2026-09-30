"""One local HTTP process routing to independent per-project applications."""

from __future__ import annotations

import asyncio
import json
import os
import secrets
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict
from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send

from tsunagou import __version__
from tsunagou.bootstrap.container import build_application
from tsunagou.platform.private_files import write_private_bytes
from tsunagou.platform.runtime_context import read_object, running_source_root
from tsunagou.shared_kernel.time import format_timestamp, now_ms


class RegisterProject(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_root: str
    state_dir: str


class ProjectDaemon:
    """Route first, then let that project's normal authenticator decide access.

    The private registry stores locations only. Domain state and control/session
    credentials remain in each project's existing database and private directory.
    """

    def __init__(self, config: dict[str, str]) -> None:
        self.config = config
        self.registry_path = Path(config.get("TSUNAGOU_DAEMON_REGISTRY") or
                                  str(Path(config["TSUNAGOU_STATE_DIR"]) / "daemon-projects.json"))
        self.apps: dict[str, FastAPI] = {}
        self.lifespans: dict[str, AbstractAsyncContextManager[Any]] = {}
        self.projects: dict[str, dict[str, str]] = {}
        self.lock = asyncio.Lock()
        self.runtime_id = str(uuid4())
        self.started_at = format_timestamp(now_ms())
        self.owner = {"project_root": config["TSUNAGOU_PROJECT_ROOT"], "state_dir": config["TSUNAGOU_STATE_DIR"]}
        self.control_token = config["TSUNAGOU_CONTROL_TOKEN"]

        @asynccontextmanager
        async def lifespan(_: FastAPI) -> AsyncIterator[None]:
            registry = read_object(self.registry_path)
            self.owner = registry.get("owner", self.owner)
            # The same registered daemon can be restarted from any member root.
            self.control_token = (Path(self.owner["state_dir"]) / "control.token").read_text(encoding="utf-8").strip()
            entries = registry.get("projects") or [self.owner]
            try:
                for entry in entries:
                    await self.add_project(entry["project_root"], entry["state_dir"], persist=False)
                self.save_registry()
                yield
            finally:
                for context in reversed(list(self.lifespans.values())):
                    await context.__aexit__(None, None, None)

        self.control = FastAPI(lifespan=lifespan)

        @self.control.get("/api/v1/health")
        def health() -> dict[str, Any]:
            return {"status": "ok", "version": __version__, "runtime": self.runtime_info()}

        @self.control.post("/api/v1/daemon/projects")
        async def register(body: RegisterProject, authorization: str | None = Header(default=None)) -> dict[str, Any]:
            if not secrets.compare_digest((authorization or "").encode(), f"Bearer {self.control_token}".encode()):
                raise HTTPException(401, detail={"code": "authentication_failed"})
            async with self.lock:
                try:
                    return await self.add_project(body.project_root, body.state_dir)
                except (OSError, RuntimeError, ValueError) as exc:
                    raise HTTPException(409, detail={"code": "project_registration_failed"}) from exc

    def runtime_info(self) -> dict[str, Any]:
        first = next(iter(self.apps.values()), None)
        return {
            "pid": os.getpid(), "runtime_id": self.runtime_id,
            "source_root": str(running_source_root()), "project_ids": sorted(self.apps),
            "schema_bundle_digest": first.state.runtime_info["schema_bundle_digest"] if first else None,
        }

    def save_registry(self) -> None:
        value = {"format_version": 1, "owner": self.owner, "projects": list(self.projects.values())}
        write_private_bytes(self.registry_path, (json.dumps(value, sort_keys=True) + "\n").encode())

    def endpoint(self, project_id: str) -> dict[str, Any]:
        return {
            "url": self.config["TSUNAGOU_DAEMON_URL"], "pid": os.getpid(), "project_id": project_id,
            "state_dir": self.projects[project_id]["state_dir"], "runtime_id": self.runtime_id,
            "source_root": str(running_source_root()), "started_at": self.started_at,
            "host_wake": self.config.get("TSUNAGOU_HOST_WAKE") or "disabled",
            "daemon_registry": str(self.registry_path), "daemon_owner_root": self.owner["project_root"],
            "daemon_owner_state_dir": self.owner["state_dir"],
        }

    async def add_project(self, project_root: str, state_dir: str, *, persist: bool = True) -> dict[str, Any]:
        root, state = Path(project_root).resolve(), Path(state_dir).resolve()
        project = read_object(root / ".tsunagou/project.json")
        project_id = project.get("project_id")
        if not isinstance(project_id, str) or not project_id:
            raise ValueError("project_not_initialized")
        entry = {"project_root": str(root), "state_dir": str(state)}
        if project_id in self.apps:
            if self.projects[project_id] != entry:
                raise ValueError("project_location_conflict")
            # Repeated attachment repairs an interrupted endpoint write too.
            value = self.endpoint(project_id)
            write_private_bytes(state / "endpoint.json", (json.dumps(value, sort_keys=True) + "\n").encode())
            if persist:
                self.save_registry()
            return value
        if any(item["state_dir"] == str(state) for item in self.projects.values()):
            raise ValueError("project_state_conflict")
        token_path = state / "control.token"
        if not token_path.is_file():
            write_private_bytes(token_path, (secrets.token_urlsafe(32) + "\n").encode())
        app = build_application({**self.config, "TSUNAGOU_PROJECT_ROOT": str(root),
                                 "TSUNAGOU_STATE_DIR": str(state), "TSUNAGOU_PROJECT_ID": project_id,
                                 "TSUNAGOU_CONTROL_TOKEN": token_path.read_text(encoding="utf-8").strip()})
        context = app.router.lifespan_context(app)
        try:
            await context.__aenter__()
            self.apps[project_id], self.projects[project_id] = app, entry
            self.lifespans[project_id] = context
            if persist:
                self.save_registry()
            value = self.endpoint(project_id)
            write_private_bytes(state / "endpoint.json", (json.dumps(value, sort_keys=True) + "\n").encode())
            return value
        except BaseException:
            self.apps.pop(project_id, None)
            self.projects.pop(project_id, None)
            self.lifespans.pop(project_id, None)
            await context.__aexit__(None, None, None)
            raise

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if scope["type"] != "http" or path in {"/api/v1/health", "/api/v1/daemon/projects"}:
            await self.control(scope, receive, send)
            return
        headers = [v.decode("utf-8") for k, v in scope.get("headers", []) if k.lower() == b"tsunagou-project-id"]
        url_id = path.split("/")[4] if path.startswith("/api/v1/projects/") else None
        choices = set(headers + ([url_id] if url_id else []))
        project_id = next(iter(choices), None)
        if not choices and len(self.apps) == 1:
            project_id = next(iter(self.apps))
        code = ("project_context_conflict" if len(choices) > 1 else
                "project_context_required" if not project_id else
                "project_not_registered" if project_id not in self.apps else None)
        if code:
            await JSONResponse({"detail": {"code": code}}, status_code=400)(scope, receive, send)
            return
        assert project_id is not None
        await self.apps[project_id](scope, receive, send)


def build_daemon() -> ProjectDaemon:
    return ProjectDaemon(dict(os.environ))
