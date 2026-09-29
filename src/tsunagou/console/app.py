"""The console's HTTP surface: the page, the two facts it owns, and the proxy.

Route order is the whole design here. The console's own endpoints are declared
first, the project-scoped relay next, and a catch-all relay last, so a request the
daemon understands always reaches the daemon — the console only answers what the
daemon cannot know (which projects exist, what the person calls their agents).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from tsunagou.console import enrollment
from tsunagou.console.agents import AgentDirectory, gather
from tsunagou.console.config import ConsoleConfig
from tsunagou.console.errors import ConsoleError
from tsunagou.console.glossary import public as glossary
from tsunagou.console.profile import load_profile, update_profile
from tsunagou.console.projects import (
    ProjectEntry,
    create,
    daemon_state,
    discover,
    ensure_daemon,
    find,
    forget,
    register,
)
from tsunagou.console.proxy import ForwardResponse, ensure_matching_project, forward, project_token
from tsunagou.shared_kernel.time import format_timestamp, now_ms

CONSOLE_VERSION = "0.1.0"
PROJECT_HEADER = "Tsunagou-Project"
RELAY_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]


@dataclass(frozen=True)
class GlobalExit:
    """An exit that hangs off ``/api/v1`` directly instead of under the project.

    A daemon serves one project, so most exits are project-scoped and the gather
    can build their URL by prefixing the project id. A few are not mounted that
    way — ``/decisions`` is the one this page needs — and prefixing them yields a
    404 that looks like "this project has nothing", which is a lie about state.
    Naming the exception here keeps the URL rule in one place.
    """

    route: str


ExitSource = str | GlobalExit

# A screen that needs several exits reads them in one call. Source names are the
# daemon's own exit names; the console gathers and never interprets, because the
# translating from a domain answer to a screen happens in the page (see
# BACKEND_SHAPE in web/assets/js/behavior.js).
CONSOLE_VIEWS: dict[str, dict[str, ExitSource]] = {
    "overview": {
        "overview": "/overview", "tasks": "/tasks", "agents": "/agents",
        "cognition": "/cognition", "checkpoints": "/checkpoints",
        # 「待用户决定」那一节读的是 decisions（BACKEND_SHAPE.project）。
        "decisions": GlobalExit("/decisions"),
    },
    "collaboration": {
        "cognition": "/cognition", "contracts": "/contracts", "messages": "/messages",
        "agents": "/agents",
        # 租约冲突账本就在「冲突与协商 → 冲突」这一栏里，所以它跟着这一屏一起读。
        "conflicts": "/conflicts",
    },
    "audit": {"intents": "/intents", "resources": "/resources", "agents": "/agents"},
    "tasks": {
        "tasks": "/tasks", "attempts": "/attempts", "agents": "/agents", "results": "/results",
        # 开工条件要回答的四件（认知报告 / 契约 / 工作空间 / 租约）与"改动范围"
        # 都在这四个出口里；中间层只搬运，怎么对到任务上是页面的事。
        "cognition": "/cognition", "contracts": "/contracts",
        "workspaces": "/workspaces", "resources": "/resources",
    },
    "acceptance": {
        "overview": "/overview", "decisions": GlobalExit("/decisions"), "tasks": "/tasks",
        "results": "/results", "reviews": "/reviews", "agents": "/agents",
    },
}


def exit_path(project_id: str, source: ExitSource) -> str:
    """Where one view source actually lives on the daemon.

    Exported so the URL rule can be asserted directly instead of only through a
    view's success or failure.
    """

    if isinstance(source, GlobalExit):
        return f"/api/v1{source.route}"
    return f"/api/v1/projects/{project_id}{source}"


class ProjectRequest(BaseModel):
    """Either create a project under ``projects_root``, or register one that exists."""

    name: str | None = None
    objective: str | None = None
    path: str | None = None


class AgentPrepareRequest(BaseModel):
    """Which host conversation should become an Agent, and who may wake the daemon.

    ``vendor`` is the host's adapter name (the same word the bridge uses); ``name`` is
    whatever the person called this conversation, which becomes its local profile.
    """

    vendor: str
    role: str = "worker"
    nickname: str = ""
    profile: str | None = None
    mode: str = "attach"
    start_daemon: bool = False


class ForgetProjectRequest(BaseModel):
    """Delete one whole project. ``delete_files`` is the caller's decision, not ours.

    The console refuses to touch files outside its own ``projects_root`` regardless;
    this switch only lets a caller keep the folder of a project it did create.
    """

    delete_files: bool = False


def explain_missing(answer: ForwardResponse) -> dict[str, Any]:
    """Why one source of a view is missing, in the daemon's own code shape."""

    try:
        payload = json.loads(answer.body or b"null")
    except json.JSONDecodeError:
        payload = None
    detail = payload.get("detail") if isinstance(payload, dict) else None
    code = detail.get("code") if isinstance(detail, dict) else detail if isinstance(detail, str) else None
    return {"status": answer.status, "code": code or "source_unavailable"}


def create_console_app(config: ConsoleConfig | None = None) -> FastAPI:
    settings = config or ConsoleConfig.load()
    web_directory = settings.web_directory()
    # One memory of "who works where", shared by the rail and the refresh route.
    directory = AgentDirectory()
    app = FastAPI(title="Tsunagou Console", version=CONSOLE_VERSION)

    @app.exception_handler(ConsoleError)
    async def console_error(_request: Request, exc: ConsoleError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content=exc.body())

    def _resolve_project(project_id: str) -> tuple[ProjectEntry, dict[str, Any]]:
        entry = find(settings, project_id)
        endpoint = ensure_daemon(entry, autostart=settings.daemon_autostart)
        ensure_matching_project(endpoint, project_id)
        return entry, endpoint

    def _requested_project(request: Request, explicit: str | None) -> str:
        """Which project a project-agnostic route belongs to.

        The page names it on every call; nothing is remembered on the server, so a
        second browser tab cannot silently redirect this one to another project.
        """

        for candidate in (request.headers.get(PROJECT_HEADER), explicit, request.query_params.get("project_id")):
            if candidate:
                return str(candidate)
        raise ConsoleError("project_not_selected")

    async def _relay(
        entry: ProjectEntry, endpoint: dict[str, Any], method: str, path: str, request: Request,
    ) -> Response:
        body = await request.body() if method.upper() not in {"GET", "HEAD"} else None
        forwarded = await run_in_threadpool(
            forward,
            endpoint=endpoint, method=method, path=path, query=request.url.query,
            body=body, token=project_token(entry.path, endpoint),
        )
        return Response(
            content=forwarded.body, status_code=forwarded.status,
            media_type=forwarded.content_type or "application/json",
        )

    # ---- facts that belong to the machine, not to a project ----------------

    @app.get("/api/v1/console/config")
    def console_configuration() -> dict[str, Any]:
        return {"console": True, "version": CONSOLE_VERSION, **settings.public()}

    @app.get("/api/v1/console/profile")
    def read_profile() -> dict[str, Any]:
        return load_profile(settings.profile_path)

    @app.get("/api/v1/console/glossary")
    def read_glossary() -> dict[str, Any]:
        """The console's Chinese for the protocol's tokens (see console/glossary.py).

        The page fetches this instead of carrying its own word list: a token's
        meaning — and the fact that there is only one short word for it — is stated
        once, here, and simply applied where a value is displayed. Raw values keep
        travelling unchanged, because the page compares them (``status == 'active'``)
        and translating data would break that.
        """

        return glossary()

    @app.put("/api/v1/console/profile")
    def write_profile(patch: dict[str, Any]) -> dict[str, Any]:
        try:
            return update_profile(settings.profile_path, patch)
        except ValueError as exc:
            raise ConsoleError(str(exc)) from exc

    @app.get("/api/v1/projects")
    def list_projects(probe: bool = True, agents: bool = False) -> dict[str, Any]:
        """Every project on this machine.

        ``agents=1`` also answers who works on each one, from the console's roster
        memory: the daemons are asked once per project and then only when their own
        storage changed. Default off, because a caller that only wants names should
        not pay for talking to every daemon.
        """

        return {
            "items": [
                entry.public()
                for entry in discover(settings, probe=probe, agents=directory if agents else None)
            ],
            "projects_root": settings.projects_root.as_posix(),
            "scan_roots": [root.as_posix() for root in settings.resolved_scan_roots()],
            "index_path": settings.index_path.as_posix(),
        }

    @app.get("/api/v1/console/agents")
    def list_agents() -> dict[str, Any]:
        """Every agent on this machine, and which project each one works in.

        The console is the only component that sees all projects at once, so the
        answer is assembled here rather than by any daemon (``console/agents.py``
        explains the memory behind it). Rosters come from that memory and cost
        nothing when it is still valid; the "what is it doing now" column is read
        from the daemons on demand, because this route is asked when a person opens
        the window, not on every rail poll.
        """

        return gather(discover(settings, probe=True), directory)

    @app.get("/api/v1/console/hosts")
    def list_hosts() -> dict[str, Any]:
        """Which host products this console can register the bridge into.

        The page asks instead of carrying its own list, so "which vendors work"
        has one answer and adding a vendor is one row in ``platform/host_registration``
        rather than a change in two languages.
        """

        return {"items": enrollment.known_hosts()}

    @app.get("/api/v1/console/enrollments/{enrollment_id}")
    def read_enrollment(enrollment_id: str) -> dict[str, Any]:
        """Is that Agent here yet? — the question the waiting overlay keeps asking.

        The answer is derived, not remembered by the daemon: the project's roster is
        re-read and compared with the one seen when the ticket was issued. Asking
        twice is harmless, and once an Agent has been found the answer stops changing,
        so a page that lost its polling loop can still pick the result up again.
        """

        return enrollment.status(enrollment_id, settings=settings, directory=directory)

    @app.post("/api/v1/console/enrollments/{enrollment_id}:cancel")
    def cancel_enrollment(enrollment_id: str) -> dict[str, Any]:
        """Stop an enrollment the person decided not to finish (see console/enrollment.py).

        The ticket file is deleted and the host entry is taken back out where we know
        how; the report says what actually happened instead of claiming a clean host.
        """

        return enrollment.cancel(enrollment_id, settings=settings)

    @app.post("/api/v1/console/projects/{project_id}/agents:prepare")
    def prepare_project_agent(project_id: str, payload: AgentPrepareRequest) -> dict[str, Any]:
        """Prepare one host conversation to become an Agent (see console/enrollment.py).

        Needs a live daemon — the ticket is the daemon's to issue — so an explicit
        ``start_daemon`` may wake the project the same way a person would; without it
        the configured ``daemon_autostart`` decides, as everywhere else. The ticket's
        secret stays in this process and inside its private file: the answer carries
        paths and statuses only.
        """

        entry = find(settings, project_id)
        endpoint = ensure_daemon(entry, autostart=settings.daemon_autostart or payload.start_daemon)
        ensure_matching_project(endpoint, project_id)
        return enrollment.prepare(
            entry, endpoint, vendor=payload.vendor, role=payload.role, nickname=payload.nickname,
            profile=payload.profile, mode=payload.mode, directory=directory,
            token=project_token(entry.path, endpoint),
        )

    @app.post("/api/v1/console/projects/{project_id}/agents:refresh")
    def refresh_project_agents(project_id: str) -> dict[str, Any]:
        """Re-read one project's roster now, whatever the memory says.

        The automatic occasions (first read, and the daemon's storage moving) cover
        the normal paths; this is the hatch for the case they miss — for example a
        daemon whose state directory moved under the console's feet.
        """

        entry, endpoint = _resolve_project(project_id)
        lineup = directory.roster(project_id, entry.path, endpoint, force=True)
        if lineup is None:
            raise ConsoleError("agents_unavailable", status=503, detail={"project_id": project_id})
        return lineup.public()

    @app.post("/api/v1/projects")
    def open_project(payload: ProjectRequest) -> dict[str, Any]:
        if payload.path:
            entry = register(settings, path=payload.path, name=payload.name, objective=payload.objective)
            return {"status": "registered", "project": _woken(entry)}
        if not payload.name:
            raise ConsoleError("project_name_required")
        entry = create(settings, name=payload.name, objective=payload.objective or "")
        return {"status": "created", "project": _woken(entry)}

    @app.post("/api/v1/console/projects/{project_id}:forget")
    def forget_project(project_id: str, payload: ForgetProjectRequest | None = None) -> dict[str, Any]:
        """Delete a project in one shot: daemon, host registrations, index line, files.

        There is no step-by-step undo in this console, and this is not one: it is the
        single "get rid of it" action. What each step did (and what it refused to do,
        and why) comes back in the report.
        """

        wanted = payload or ForgetProjectRequest()
        return forget(settings, project_id, delete_files=wanted.delete_files)

    def _woken(entry: ProjectEntry) -> dict[str, Any]:
        """Start a freshly created project's daemon, and report what happened.

        A project nobody can open is not finished being made, and "新建协作" is the one
        moment a person asked for this project to exist — so the server starts here and
        not on some background poll. A failure is not a creation failure: the entry's own
        daemon field says 未启动, which is a state the rail already knows how to show.
        """

        try:
            ensure_daemon(entry, autostart=True)
        except ConsoleError:
            pass
        entry.daemon = daemon_state(entry.path, probe=True)
        return entry.public()

    # ---- everything else belongs to a project's daemon ---------------------
    @app.get("/api/v1/console/views/{view}")
    async def console_view(view: str, request: Request, project_id: str | None = None) -> dict[str, Any]:
        """One read for a screen that needs several exits.

        Each source is either the daemon's own answer or an explanation of why it
        is missing, so one refused exit leaves a hole in one panel instead of a
        blank page. If the daemon itself is down the whole view refuses, which is
        what the page needs to say "未启动".
        """

        sources = CONSOLE_VIEWS.get(view)
        if sources is None:
            raise ConsoleError("console_view_unknown", status=404, detail={"view": view})
        project_id = _requested_project(request, project_id)
        entry, endpoint = _resolve_project(project_id)
        token = project_token(entry.path, endpoint)
        gathered: dict[str, Any] = {}
        missing: dict[str, Any] = {}
        for name, source in sources.items():
            answered = await run_in_threadpool(
                forward, endpoint=endpoint, method="GET",
                path=exit_path(project_id, source), token=token,
            )
            if answered.status >= 400:
                missing[name] = explain_missing(answered)
                continue
            try:
                gathered[name] = json.loads(answered.body or b"null")
            except json.JSONDecodeError:
                missing[name] = {"status": answered.status, "code": "unreadable_answer"}
        return {
            "project_id": project_id, "view": view, "sources": gathered, "missing": missing,
            "gathered_at": format_timestamp(now_ms()),
        }

    @app.post("/api/v1/commands/{command_kind}")
    async def relay_command(command_kind: str, request: Request, project_id: str | None = None) -> Response:
        project_id = _requested_project(request, project_id)
        entry, endpoint = _resolve_project(project_id)
        return await _relay(entry, endpoint, "POST", f"/api/v1/commands/{command_kind}", request)

    @app.api_route("/api/v1/projects/{project_id}/{rest:path}", methods=RELAY_METHODS)
    async def relay_project(project_id: str, rest: str, request: Request) -> Response:
        entry, endpoint = _resolve_project(project_id)
        return await _relay(entry, endpoint, request.method, f"/api/v1/projects/{project_id}/{rest}", request)

    @app.api_route("/api/v1/{rest:path}", methods=RELAY_METHODS)
    async def relay_anything(rest: str, request: Request) -> Response:
        project_id = _requested_project(request, None)
        entry, endpoint = _resolve_project(project_id)
        return await _relay(entry, endpoint, request.method, f"/api/v1/{rest}", request)

    # ---- the page itself ---------------------------------------------------

    @app.get("/console.config.js")
    def console_configuration_script() -> Response:
        """The page's own switch, generated where the console knows the answer.

        Opening ``index.html`` straight from disk uses the checked-in default; a
        page served by the console is told whether this machine is in demo mode.
        """

        payload = {"baseUrl": "/api/v1", **settings.public()}
        script = "window.TSUNAGOU_CONSOLE_CONFIG = " + json.dumps(payload, sort_keys=True) + ";\n"
        return Response(content=script, media_type="application/javascript")

    app.mount("/", StaticFiles(directory=str(web_directory), html=True), name="web")
    return app
