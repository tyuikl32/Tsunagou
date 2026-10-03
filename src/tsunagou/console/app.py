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
from tsunagou.console.history import HistoryStore
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
    #: ``local`` 是本机接入；``network`` 是"发一张邀请给另一台机器"（那段内容由人转交）。
    place: str = "local"
    #: 只有"会话名由宿主自己生成"的宿主（Codex、DeepSeek Harness）才需要：远端报上来的号。
    conversation_id: str = ""


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
    # It is also the place where a vendor is filled in for Agents the console never
    # enrolled (see ``agents.reconcile_vendors``).
    directory = AgentDirectory(profile_path=settings.profile_path)
    # 控制台自己的记录：它搬运过的那些出口，最近一次看到的样子（见 console/history.py）。
    # 放在索引旁边，所以测试把索引指到临时目录时，记录自然也跟着进临时目录。
    history = HistoryStore.beside_index(settings.index_path)
    app = FastAPI(title="Tsunagou Console", version=CONSOLE_VERSION)

    @app.exception_handler(ConsoleError)
    async def console_error(_request: Request, exc: ConsoleError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content=exc.body())

    def _resolve_project(project_id: str) -> tuple[ProjectEntry, dict[str, Any]]:
        entry = find(settings, project_id)
        endpoint = ensure_daemon(entry, autostart=settings.daemon_autostart)
        ensure_matching_project(endpoint, project_id)
        return entry, endpoint

    # 只有这两种拒绝才允许"用记录顶上"：daemon 不在（没起过 / 起不来）。项目对不上号
    # （daemon_project_mismatch）是配置出了问题，那时拿一份记录出来只会把问题藏起来。
    _STOPPED_CODES = ("daemon_not_running", "daemon_start_failed")

    def _resolve_readable(project_id: str) -> tuple[ProjectEntry, dict[str, Any] | None]:
        """Where to read a screen from: this project's daemon, or its record.

        A finished project's daemon is gone, and ``ensure_daemon`` refuses long before any
        exit is asked. For a **read** that is too early to give up: if this console has a
        record of the project, the answer is "here is what it last said", not an error.
        Nothing else changes — a project we never saw still refuses exactly as before.
        """

        try:
            entry, endpoint = _resolve_project(project_id)
        except ConsoleError as exc:
            if exc.code not in _STOPPED_CODES or history.summary(project_id)["sources"] == 0:
                raise
            return find(settings, project_id), None
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

    def _relay_source(path: str) -> str:
        """How one relayed exit is named in the record: the path, without its query.

        The page varies the query (limits, cursors); "the same screen" is the path, and
        keeping one entry per path is what stops the record from growing with every page.
        """

        return "relay:" + path.split("?", 1)[0]

    async def _relay(
        entry: ProjectEntry, endpoint: dict[str, Any] | None, method: str, path: str, request: Request,
    ) -> Response:
        body = await request.body() if method.upper() not in {"GET", "HEAD"} else None
        reading = method.upper() in {"GET", "HEAD"}
        recorded = history.payload(entry.project_id, _relay_source(path)) if reading else None
        if endpoint is not None:
            try:
                forwarded = await run_in_threadpool(
                    forward,
                    endpoint=endpoint, method=method, path=path, query=request.url.query,
                    body=body, token=project_token(entry.path, endpoint),
                )
            except ConsoleError:
                # 连不上（daemon 停了、挂了）：读得出记录就拿记录顶上，并明确标出它是什么
                # 时候的。写动作永不记录，也永不用记录顶替。
                if recorded is None:
                    raise
                return _recorded_answer(recorded)
            if reading and 200 <= forwarded.status < 300:
                # 读得通就记一份（这个出口下次 daemon 不在了也能看）。
                try:
                    history.record(entry.project_id, _relay_source(path), json.loads(forwarded.body or b"null"),
                                   captured_at=format_timestamp(now_ms()))
                except json.JSONDecodeError:
                    pass
            # daemon 自己给的回答（包括 4xx 的拒绝）一律原样送回去：那是**现在**的答案，
            # 不该被一份旧记录顶掉 —— 藏着活的拒绝比留空更坏。
            return Response(
                content=forwarded.body, status_code=forwarded.status,
                media_type=forwarded.content_type or "application/json",
            )
        # 已经没有 daemon 可问了（项目结束）：这一条读的是记录，没有记录就照旧说连不上。
        if recorded is None:
            raise ConsoleError("daemon_not_running", status=503,
                               detail={"project_id": entry.project_id, "path": entry.path.as_posix()})
        return _recorded_answer(recorded)

    def _recorded_answer(recorded: tuple[Any, str]) -> Response:
        """One recorded exit, marked so nobody mistakes it for a live answer."""

        payload, captured_at = recorded
        if isinstance(payload, dict):
            payload = {**payload, "_history": {"captured_at": captured_at}}
        return JSONResponse(content=payload, headers={"X-Tsunagou-History": captured_at})

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

        Each row also carries ``history``: when this project's record was last written and
        how many exits it holds. The page uses it to say "last seen at ..." on a card whose
        daemon is gone — the record itself is read through the exits, not from here.
        """

        items: list[dict[str, Any]] = []
        for entry in discover(settings, probe=probe, agents=directory if agents else None):
            row = entry.public()
            # 只在**这一行的内容真的来自 daemon**（刚探活成功）时记一份。否则"上次记录"
            # 会被"看了一次列表"本身刷新成现在 —— 那它就再也说不出"最后活着是什么时候"。
            if isinstance(entry.daemon, dict) and entry.daemon.get("running"):
                history.record(entry.project_id, "console.project", row, captured_at=format_timestamp(now_ms()))
            row["history"] = history.summary(entry.project_id)
            items.append(row)
        return {
            "items": items,
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

    @app.get("/api/v1/console/enrollments/current")
    def read_current_enrollment() -> dict[str, Any]:
        """Recover the active Codex wait without exposing its private chat identity."""
        return enrollment.current_status(settings=settings, directory=directory)

    @app.get("/api/v1/console/enrollments/{enrollment_id}")
    def read_enrollment(enrollment_id: str) -> dict[str, Any]:
        """Is that Agent here yet? — the question the waiting overlay keeps asking.

        The answer is derived, not remembered by the daemon: the project's roster is
        re-read and compared with the one seen when the ticket was issued. Asking
        twice is harmless, and once an Agent has been found the answer stops changing,
        so a page that lost its polling loop can still pick the result up again.
        """

        return enrollment.status(enrollment_id, settings=settings, directory=directory)

    @app.get("/api/v1/console/projects/{project_id}/enrollments:observe")
    def observe_project_enrollment(
        project_id: str, adapter: str = "", baseline: str = "", enrollment_id: str = "",
    ) -> dict[str, Any]:
        """Watch for a host that enrolls inside its own chat (``in_host``).

        Nothing is signed, queued or remembered here — that is the whole point of this
        mode: the host's own chat signs its ticket with the identity the host gave it.
        The answer is derived from what the project can prove (a seat new to this caller
        whose vendor came out of an enrollment file), so asking twice is harmless and a
        page that lost its loop can ask again with the same ``baseline``.
        ``enrollment_id`` is the machine-level record this attempt wrote; on arrival it
        is closed, so the single slot frees up for the next Agent.
        """

        return enrollment.observe(
            settings=settings, directory=directory, project_id=project_id, adapter=adapter,
            baseline={item.strip() for item in baseline.split(",") if item.strip()},
            enrollment_id=enrollment_id.strip(),
        )

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

        Codex stores selection only; its target chat starts the daemon and signs
        a ticket after claiming. Other hosts need a live daemon, so an explicit
        ``start_daemon`` may wake the project the same way a person would; without it
        the configured ``daemon_autostart`` decides, as everywhere else. The ticket's
        secret stays in this process and inside its private file: the answer carries
        paths and statuses only.
        """

        entry = find(settings, project_id)
        if payload.vendor.strip().lower() == "codex" and payload.place != "network":
            # A refreshed page may have stopped polling after the chat completed.
            # Verify that receipt before reusing the slot or starting another one.
            enrollment.current_status(settings=settings, directory=directory)
            return enrollment.prepare(
                entry, dict(entry.daemon or {}), vendor=payload.vendor, role=payload.role,
                nickname=payload.nickname, profile=payload.profile, mode=payload.mode, directory=directory,
                place=payload.place, conversation_id=payload.conversation_id,
            )
        endpoint = ensure_daemon(entry, autostart=settings.daemon_autostart or payload.start_daemon)
        ensure_matching_project(endpoint, project_id)
        return enrollment.prepare(
            entry, endpoint, vendor=payload.vendor, role=payload.role, nickname=payload.nickname,
            profile=payload.profile, mode=payload.mode, directory=directory,
            token=project_token(entry.path, endpoint),
            place=payload.place, conversation_id=payload.conversation_id,
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
        what the page needs to say "未启动" — unless this console has a record of the
        project, in which case the panel is filled from it and every such source is
        named in ``history`` with the moment it was recorded.
        """

        sources = CONSOLE_VIEWS.get(view)
        if sources is None:
            raise ConsoleError("console_view_unknown", status=404, detail={"view": view})
        project_id = _requested_project(request, project_id)
        entry, endpoint = _resolve_readable(project_id)
        token = project_token(entry.path, endpoint)
        gathered: dict[str, Any] = {}
        missing: dict[str, Any] = {}
        # 哪几个来源这一屏其实是从记录里拿的（页面据此写「上次记录（记录到 …）」）。
        from_history: dict[str, str] = {}
        unreachable: ConsoleError | None = None
        for name, source in sources.items():
            answered: ForwardResponse | None = None
            if endpoint is not None:
                try:
                    answered = await run_in_threadpool(
                        forward, endpoint=endpoint, method="GET",
                        path=exit_path(project_id, source), token=token,
                    )
                except ConsoleError as exc:
                    unreachable = unreachable or exc
            if answered is None:
                # The daemon is not there at all. Serve what was recorded for this exit; if
                # nothing was, this panel keeps its hole (and the view refuses below when
                # *no* source had a record).
                kept = history.payload(project_id, name)
                if kept is None:
                    missing[name] = {"status": 503, "code": "daemon_not_running"}
                    continue
                payload, captured_at = kept
                gathered[name] = payload
                from_history[name] = captured_at
                continue
            if answered.status >= 400:
                # A live refusal stays a hole in this panel: it is an answer about *now*,
                # and an old record must not paper over it.
                missing[name] = explain_missing(answered)
                continue
            try:
                payload = json.loads(answered.body or b"null")
            except json.JSONDecodeError:
                missing[name] = {"status": answered.status, "code": "unreadable_answer"}
                continue
            gathered[name] = payload
            # 读得通就记一份（这一屏下次 daemon 不在了也能看）。
            history.record(project_id, name, payload, captured_at=format_timestamp(now_ms()))
        if unreachable is not None and not from_history:
            # Nothing was ever recorded either: this is the plain "daemon 未启动" case.
            raise unreachable
        return {
            "project_id": project_id, "view": view, "sources": gathered, "missing": missing,
            "gathered_at": format_timestamp(now_ms()),
            **({"history": from_history} if from_history else {}),
        }

    @app.post("/api/v1/commands/{command_kind}")
    async def relay_command(command_kind: str, request: Request, project_id: str | None = None) -> Response:
        project_id = _requested_project(request, project_id)
        entry, endpoint = _resolve_project(project_id)
        return await _relay(entry, endpoint, "POST", f"/api/v1/commands/{command_kind}", request)

    @app.api_route("/api/v1/projects/{project_id}/{rest:path}", methods=RELAY_METHODS)
    async def relay_project(project_id: str, rest: str, request: Request) -> Response:
        entry, endpoint = _resolve_readable(project_id)
        return await _relay(entry, endpoint, request.method, f"/api/v1/projects/{project_id}/{rest}", request)

    @app.api_route("/api/v1/{rest:path}", methods=RELAY_METHODS)
    async def relay_anything(rest: str, request: Request) -> Response:
        project_id = _requested_project(request, None)
        entry, endpoint = _resolve_readable(project_id)
        return await _relay(entry, endpoint, request.method, f"/api/v1/{rest}", request)

    # ---- the page itself ---------------------------------------------------

    @app.get("/console.config.js")
    def console_configuration_script() -> Response:
        """The page's own switch, generated where the console knows the answer.

        Opening ``index.html`` straight from disk uses the checked-in default; a
        page served by the console is told the API prefix this process answers
        on, so the two can never disagree.
        """

        payload = {"baseUrl": "/api/v1", **settings.public()}
        script = "window.TSUNAGOU_CONSOLE_CONFIG = " + json.dumps(payload, sort_keys=True) + ";\n"
        return Response(content=script, media_type="application/javascript")

    app.mount("/", StaticFiles(directory=str(web_directory), html=True), name="web")
    return app
