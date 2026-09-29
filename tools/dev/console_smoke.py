"""One command that proves the console works: project -> daemon -> page -> views.

What it does, in order (all inside a sandbox directory, nothing outside it is
touched):

1. creates a project at ``<sandbox>/projects/<name>`` and registers it;
2. starts that project's daemon (``tsunagou daemon start``) and waits for it to
   answer ``/api/v1/health``;
3. writes a console config that points *only* at the sandbox, starts
   ``tsunagou web start``, and waits for the console manifest;
4. asks the console the questions the page asks — project list, its own config,
   the generated ``/console.config.js``, the page itself, ``/console/profile``,
   every aggregation view, the exits the page reads on its own (history,
   checkpoints, checkpoint failures, reviews, intents, conflicts), and one
   refusal for a project that has no daemon. Each view answer is judged against
   the view table the console itself serves (``CONSOLE_VIEWS``): every declared
   source must come back either gathered or explicitly missing, and the ones the
   page has a column for must not be missing — "a panel that is always empty" is
   otherwise a failure with no error message anywhere;
5. prints ``PASS``/``FAIL`` per probe, then stops what it started (unless
   ``--keep`` was passed, in which case it prints the URL and waits).

Usage::

    uv run python tools/dev/console_smoke.py            # smoke, then clean up
    uv run python tools/dev/console_smoke.py --keep     # leave it running to click around
    uv run python tools/dev/console_smoke.py --url http://127.0.0.1:50190   # probe a console already running

The page's *structure* (the row selector, the multi-line cell rule) is guarded by
``web/tests/behavior.smoke.test.ts`` instead — that one runs under vitest + jsdom,
needs no daemon, and is part of the repository's checks.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from tsunagou.console.app import CONSOLE_VIEWS

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SANDBOX = Path.home() / ".tsunagou" / "console-smoke"
HEALTH_TIMEOUT = 20.0
VIEWS = tuple(CONSOLE_VIEWS)
# 页面在这些源上各有一块栗目：它们必须真的答上来（不能是 403/404），
# 少一个的表现就是“那一块永远是空的”，而且不会报任何错。
CRITICAL_SOURCES = {
    "overview": ("overview", "tasks", "agents", "checkpoints", "decisions"),
    "collaboration": ("agents", "conflicts"),
    "audit": ("intents", "agents"),
    "tasks": ("tasks", "attempts", "agents", "results"),
    "acceptance": ("overview", "decisions", "tasks", "results", "reviews", "agents"),
}


def _request(url: str, project_id: str | None = None, timeout: float = 5.0) -> tuple[int, bytes]:
    headers = {"Accept": "application/json"}
    if project_id:
        headers["Tsunagou-Project"] = project_id
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def _wait_for(url: str, *, timeout: float = HEALTH_TIMEOUT) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            status, _ = _request(url)
        except (urllib.error.URLError, OSError):
            status = 0
        if status == 200:
            return True
        time.sleep(0.3)
    return False


def _run(*args: str, cwd: Path, env: dict[str, str] | None = None) -> dict[str, object]:
    environment = {**os.environ, **(env or {})}
    completed = subprocess.run(
        [sys.executable, "-m", "tsunagou", "--json", *args],
        cwd=cwd, capture_output=True, text=True, check=False, env=environment,
    )
    if completed.returncode != 0:
        raise SystemExit(f"command failed: {' '.join(args)}\n{completed.stderr or completed.stdout}")
    parsed = json.loads(completed.stdout.strip().splitlines()[-1])
    if not isinstance(parsed, dict):
        raise SystemExit(f"unexpected answer from {' '.join(args)}: {completed.stdout.strip()[:200]}")
    return parsed


def _sandbox_environment(index_path: Path) -> dict[str, str]:
    """Keep every subprocess inside the sandbox: the real project index stays untouched.

    ``PYTHONUNBUFFERED`` matters here: the console is started as a child and a
    buffered child would hide its startup line until it exits.
    """

    return {"TSUNAGOU_PROJECT_INDEX": str(index_path), "PYTHONUNBUFFERED": "1"}


def _prepare_sandbox(sandbox: Path, index_path: Path) -> tuple[Path, str]:
    """A project that exists, is registered, and has a daemon config of its own."""

    project_root = sandbox / "projects" / "冒烟项目"
    if not (project_root / ".tsunagou" / "project.json").is_file():
        project_root.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "--quiet", str(project_root)], check=True)
        created = _run(
            "project", "init", "--coordination-root", str(project_root),
            "--name", "冒烟项目", "--objective", "用控制台把后端读起来",
            cwd=REPOSITORY_ROOT, env=_sandbox_environment(index_path),
        )
        project_id = str(created["project_id"])
    else:
        manifest = json.loads((project_root / ".tsunagou" / "project.json").read_text(encoding="utf-8"))
        project_id = str(manifest["project_id"])
    return project_root, project_id


def _endpoint_url(endpoint: Path) -> str:
    if not endpoint.is_file():
        return ""
    try:
        return str(json.loads(endpoint.read_text(encoding="utf-8"))["url"])
    except (OSError, json.JSONDecodeError, KeyError):
        return ""


def _daemon_failure(project_root: Path, launcher: subprocess.Popen[bytes]) -> str:
    """Say what actually happened, from the only place that records it.

    The launcher's own stream cannot be read here: the daemon it spawns inherits
    that pipe, so the pipe never reaches end-of-file. The daemon writes its log
    next to its state instead, which is where a real cause shows up.
    """

    lines = [f"daemon did not answer within {HEALTH_TIMEOUT:.0f}s"]
    if launcher.poll() is not None:
        lines.append(f"  launcher exit code: {launcher.returncode}")
        if launcher.returncode == 4:
            lines.append("  (4 = checkpoint_restore_required: run `project restore` for this project)")
    else:
        lines.append("  launcher still running (waiting for the daemon to answer)")
    log = project_root / ".tsunagou" / "local" / "daemon.log"
    if log.is_file():
        tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-15:]
        lines.append(f"  last lines of {log}:")
        lines.extend(f"    {line}" for line in tail)
    else:
        lines.append(f"  no log at {log} (the daemon never got that far)")
    return "\n".join(lines)


def _start_daemon(project_root: Path, env: dict[str, str]) -> str:
    """Start the project's daemon (or reuse a running one) and return its url."""

    launcher = subprocess.Popen(
        [sys.executable, "-m", "tsunagou", "--json", "daemon", "start", "--coordination-root", str(project_root)],
        cwd=REPOSITORY_ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        env={**os.environ, **env},
    )
    endpoint = project_root / ".tsunagou" / "local" / "endpoint.json"
    deadline = time.time() + HEALTH_TIMEOUT
    while time.time() < deadline:
        url = _endpoint_url(endpoint)
        if url and _wait_for(url.rstrip("/") + "/api/v1/health", timeout=2.0):
            return url
        # The launcher exits as soon as it has spawned the daemon (or found one
        # already running), so a zero exit is normal here and must not stop the
        # wait; only a failed launch does.
        if launcher.poll() not in (None, 0):
            break
        time.sleep(0.3)
    raise SystemExit(_daemon_failure(project_root, launcher))


def _start_console(sandbox: Path, project_root: Path, environment: dict[str, str]) -> tuple[subprocess.Popen[bytes], str]:
    config_path = sandbox / ".tsunagou-console.json"
    config_path.write_text(json.dumps({
        "host": "127.0.0.1", "port": 0,
        "projects_root": str(sandbox / "projects"),
        "scan_roots": [str(sandbox)],
        "index_path": str(sandbox / "projects.json"),
        "profile_path": str(sandbox / "console-profile.json"),
        "poll_ms": 5000, "daemon_autostart": False,
    }, indent=2) + "\n", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, "-m", "tsunagou", "--json", "web", "start", "--config", str(config_path)],
        cwd=REPOSITORY_ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        env={**os.environ, **environment},
    )
    # 控制台自己会把监听地址写进它旁边的 .tsunagou-console.local.json，
    # 所以这里读文件而不是读子进程的 stdout（不会因管道缓冲而卡住）。
    manifest = sandbox / ".tsunagou-console.local.json"
    deadline = time.time() + HEALTH_TIMEOUT
    while time.time() < deadline:
        if process.poll() is not None:
            raise SystemExit("console exited before it reported a URL")
        if manifest.is_file():
            try:
                url = str(json.loads(manifest.read_text(encoding="utf-8"))["url"])
            except (OSError, json.JSONDecodeError, KeyError):
                url = ""
            if url and _wait_for(url.rstrip("/") + "/api/v1/console/config", timeout=5.0):
                print(f"console: {url}   (page: {url}/)")
                return process, url
        time.sleep(0.3)
    raise SystemExit("console did not report a URL in time")


def _probe(base: str, path: str, *, project_id: str | None = None, expect: int = 200,
           note: str = "") -> bool:
    try:
        status, body = _request(base + path, project_id)
    except (urllib.error.URLError, OSError) as error:
        status, body = 0, str(error).encode()
    ok = status == expect
    detail = ""
    if ok and body:
        try:
            payload = json.loads(body)
            if isinstance(payload, dict) and "sources" in payload:
                gathered = sorted(payload.get("sources") or {})
                missing = sorted(payload.get("missing") or {})
                detail = f" sources={gathered} missing={missing}"
            elif isinstance(payload, dict) and "items" in payload:
                detail = f" items={len(payload['items'])}"
        except json.JSONDecodeError:
            detail = f" {len(body)}B"
    print(f"  {'PASS' if ok else 'FAIL'}  {status:>3} {path}{note}{detail}")
    return ok


def _config_script_is_demo_free(base: str) -> bool:
    """The generated switch must not hand the page a demo mode again."""

    status, body = _request(base + "/console.config.js")
    text = body.decode("utf-8", "replace")
    mentioned = sorted(word for word in ("demo", "mode") if word in text)
    ok = status == 200 and not mentioned
    note = "" if ok else "  (still mentions " + ",".join(mentioned) + ")"
    print(f"  {'PASS' if ok else 'FAIL'}  {status:>3} /console.config.js carries no demo mode{note}")
    return ok


def _page_loads_no_demo_backend(base: str) -> bool:
    """The shipped page must not pull a file that answers requests by itself."""

    status, body = _request(base + "/")
    text = body.decode("utf-8", "replace")
    ok = status == 200 and "mock-backend" not in text
    note = "" if ok else "  (the page still loads mock-backend.js)"
    print(f"  {'PASS' if ok else 'FAIL'}  {status:>3} / loads only the real behaviour{note}")
    return ok


def _view_health(base: str, view: str, project_id: str) -> bool:
    """Judge one view answer against the view table the console itself serves.

    ``sources`` + ``missing`` must account for exactly the sources that view
    declares: a source dropped from the table would otherwise only show up as
    "that panel is always empty", with nothing failing anywhere.
    """

    status, body = _request(f"{base}/api/v1/console/views/{view}?project_id={project_id}", project_id)
    if status != 200:
        print(f"  FAIL  {status:>3} view {view}")
        return False
    payload = json.loads(body)
    gathered = set(payload.get("sources") or {})
    missing = set(payload.get("missing") or {})
    declared = set(CONSOLE_VIEWS[view])
    problems: list[str] = []
    if gathered | missing != declared:
        problems.append("declared=" + ",".join(sorted(declared)))
    absent = sorted(name for name in CRITICAL_SOURCES[view] if name not in gathered)
    if absent:
        problems.append("empty-critical=" + ",".join(absent))
    detail = " sources=" + ",".join(sorted(gathered))
    if missing:
        detail += " missing=" + ",".join(sorted(missing))
    if problems:
        detail += "  " + " ".join(problems)
    print(f"  {'PASS' if not problems else 'FAIL'}  {status:>3} view {view}{detail}")
    return not problems


def smoke(base: str, project_id: str) -> bool:
    print(f"probing {base}")
    results = [
        _probe(base, "/api/v1/console/config"),
        _probe(base, "/api/v1/console/profile"),
        _probe(base, "/api/v1/console/glossary"),
        # Who works where: the one answer no daemon can give on its own.
        _probe(base, "/api/v1/console/agents"),
        _probe(base, "/api/v1/projects"),
        _config_script_is_demo_free(base),
        _page_loads_no_demo_backend(base),
        # The exits the page reads on its own, one probe per screen section.
        _probe(base, "/api/v1/projects/" + project_id + "/history", project_id=project_id),
        _probe(base, "/api/v1/projects/" + project_id + "/checkpoints", project_id=project_id),
        _probe(base, "/api/v1/projects/" + project_id + "/checkpoint-failures", project_id=project_id),
        _probe(base, "/api/v1/projects/" + project_id + "/reviews", project_id=project_id),
        _probe(base, "/api/v1/projects/" + project_id + "/intents", project_id=project_id),
        _probe(base, "/api/v1/projects/" + project_id + "/conflicts", project_id=project_id),
    ]
    results.extend(_view_health(base, view, project_id) for view in VIEWS)
    # A project the console knows nothing about must be refused, not relayed.
    results.append(_probe(
        base, "/api/v1/projects/00000000-0000-0000-0000-000000000000/tasks",
        project_id="00000000-0000-0000-0000-000000000000", expect=404, note="  (expected refusal)",
    ))
    return all(results)


def _run_quiet(*args: str, cwd: Path, env: dict[str, str] | None = None) -> None:
    """Run the CLI and ignore the outcome: used for best-effort cleanup."""

    subprocess.run(
        [sys.executable, "-m", "tsunagou", "--json", *args],
        cwd=cwd, capture_output=True, text=True, check=False,
        env={**os.environ, **(env or {})},
    )


def _stop_everything(
    console: subprocess.Popen[bytes] | None, project_root: Path, environment: dict[str, str],
) -> None:
    """Stop what this script started, by the same doors a person would use.

    The daemon is *detached* by ``daemon start``, so terminating the launcher
    process would leave it running; it is stopped through the CLI instead.
    """

    if isinstance(console, subprocess.Popen) and console.poll() is None:
        console.terminate()
        try:
            console.wait(timeout=5)
        except subprocess.TimeoutExpired:
            console.kill()
    _run_quiet(
        "daemon", "stop", "--coordination-root", str(project_root),
        cwd=REPOSITORY_ROOT, env=environment,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sandbox", type=Path, default=DEFAULT_SANDBOX)
    parser.add_argument("--url", help="probe a console that is already running instead of starting one")
    parser.add_argument("--project-id", help="the project to probe with (only with --url)")
    parser.add_argument("--keep", action="store_true", help="leave the daemon and console running")
    parser.add_argument("--reset", action="store_true", help="delete the sandbox first")
    args = parser.parse_args()

    if args.url:
        if not args.project_id:
            status, body = _request(args.url.rstrip("/") + "/api/v1/projects")
            if status != 200:
                raise SystemExit(f"cannot list projects at {args.url}: {status}")
            entries = json.loads(body).get("items") or []
            if not entries:
                raise SystemExit("that console knows no projects; pass --project-id")
            args.project_id = str(entries[0]["project_id"])
        return 0 if smoke(args.url.rstrip("/"), args.project_id) else 1

    sandbox: Path = args.sandbox.expanduser().resolve()
    if args.reset and sandbox.exists():
        # 上一轮的 daemon 可能还开着日志文件；清不掉就接着用，不因此失败。
        shutil.rmtree(sandbox, ignore_errors=True)
    sandbox.mkdir(parents=True, exist_ok=True)
    environment = _sandbox_environment(sandbox / "projects.json")
    project_root, project_id = _prepare_sandbox(sandbox, sandbox / "projects.json")
    print(f"project: {project_root}  ({project_id})")

    daemon_url = _start_daemon(project_root, environment)
    print(f"daemon: {daemon_url}")
    console: subprocess.Popen[bytes] | None = None
    try:
        console, base = _start_console(sandbox, project_root, environment)
        passed = smoke(base, project_id)
        if args.keep:
            print("\nleft running: open the page above; press Ctrl+C to stop the console")
            print(f"daemon {daemon_url} keeps running until you stop it:")
            print(f'  tsunagou daemon stop --coordination-root "{project_root}"')
            while True:
                time.sleep(3600)
        return 0 if passed else 1
    except KeyboardInterrupt:
        return 130
    finally:
        if not args.keep:
            _stop_everything(console, project_root, environment)
            print("stopped console and daemon (sandbox kept at " + str(sandbox) + ")")


if __name__ == "__main__":
    raise SystemExit(main())
