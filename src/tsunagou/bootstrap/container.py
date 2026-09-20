"""Application assembly; domain services are added by their owning tasks."""

from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import FastAPI

from tsunagou.api.app import create_app
from tsunagou.api.auth import LocalCommandAuthenticator
from tsunagou.application.handlers import build_handlers
from tsunagou.interfaces.runtime import CommandDispatcher
from tsunagou.modules.authority import AuthorityService
from tsunagou.modules.cognition import CognitionService
from tsunagou.modules.messaging import MessageStore
from tsunagou.modules.tasks import TaskService

_REGISTRY = Path(__file__).resolve().parents[3] / "protocol" / "registry" / "commands.json"


def build_application() -> FastAPI:
    """Assemble the real application with authority, handlers and control credentials.

    Credentials come only from the environment, never from request headers or hardcoded
    defaults. When unset, the application stays fail-closed for every business command:

    - ``TSUNAGOU_CONTROL_TOKEN`` is the private user-control bearer credential.
    - ``TSUNAGOU_STATE_DIR`` points at the durable authority state directory; without it,
      authority state is in-memory only and does not survive a restart.
    """
    state_dir = os.environ.get("TSUNAGOU_STATE_DIR")
    state_path = Path(state_dir) / "identity.json" if state_dir else None
    authority = AuthorityService(state_path)
    tasks = TaskService()
    cognition = CognitionService()
    messages = MessageStore(Path(state_dir) / "messages.json" if state_dir else None)
    project_id = _project_id()
    dispatcher = CommandDispatcher(_REGISTRY)
    for command_kind, handler in build_handlers(
        authority=authority, tasks=tasks, cognition=cognition, messages=messages,
        project_id=project_id,
    ).items():
        dispatcher.register(command_kind, handler)
    authenticator = LocalCommandAuthenticator(
        authority=authority, control_token=os.environ.get("TSUNAGOU_CONTROL_TOKEN")
    )
    return create_app(dispatcher, authenticator=authenticator)


def _project_id() -> str | None:
    """Resolve a project id from the environment or the coordination repo."""
    configured = os.environ.get("TSUNAGOU_PROJECT_ID")
    if configured:
        return configured
    project_root = os.environ.get("TSUNAGOU_PROJECT_ROOT")
    if not project_root:
        return None
    project_file = Path(project_root) / ".tsunagou" / "project.json"
    if not project_file.is_file():
        return None
    try:
        raw = json.loads(project_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = raw.get("project_id")
    return value if isinstance(value, str) and value else None
