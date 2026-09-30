"""The private files that put a bridge next to one host conversation.

Enrolment is a chain of local documents and exactly one secret:

* ``host-identity.json`` — who this conversation is (adapter, profile, ids);
* ``ticket.json`` — the one-time enrollment secret, private to its owner;
* ``<adapter>-<installation>.json`` — how to launch the bridge: command, args, env.

The third one is what a host's MCP configuration is built from, which is why it
never contains the secret itself: it points at the ticket file instead.

They live under the project (``.tsunagou/bridges/...``), not under the product
checkout, so cloning the repository never carries them and a project stays movable
as a unit. The host's own configuration remains the host's business — this module
only produces the launch description and reads it back.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import Any

from tsunagou.platform.private_file_lock import private_file_lock
from tsunagou.platform.private_files import write_private_bytes

PLACEHOLDER_ENTRY = "<tsunagou-bridge-server>/dist/server.js"
_ENTRY_RELATIVE = Path("packages") / "bridge-server" / "dist" / "server.js"
BRIDGE_DIRECTORY = Path(".tsunagou") / "bridges"
# Shared by CLI and Console enrollment: these hosts must prove their
# conversation identity through MCP metadata on every bridge tool call.
HOST_META_KEYS = {"opencode": "ai.opencode/sessionID"}


def bridge_entry_path() -> Path:
    """Where the bridge's compiled stdio entry lives, next to this checkout.

    A placeholder is written when it has not been built: the host config must still
    be readable, and the person who opens it should see that nothing was invented.
    """

    candidate = Path(__file__).resolve().parents[3] / _ENTRY_RELATIVE
    return candidate if candidate.is_file() else Path(PLACEHOLDER_ENTRY)


def write_ticket_file(
    installation_id: str, conversation_id: str, secret: str, ticket_file: Path | None,
    requested_role: str = "worker",
    host_binding_generation: str | None = None,
) -> Path:
    """Deliver a one-time enrollment ticket through a private file, never stdout.

    The ticket secret is a bearer credential for ``agent.enroll``; echoing it to a
    terminal leaks it into scrollback, logs and shell history. The bridge reads it
    from this file through its own private channel instead. The file is restricted
    to its creator (POSIX ``0600``, or a stripped Windows ACL) so other local
    accounts cannot read the secret.
    """

    if ticket_file is None:
        fd, temp_name = tempfile.mkstemp(prefix="tsunagou-ticket-", suffix=".json")
        os.close(fd)
        path = Path(temp_name)
    else:
        path = ticket_file
    path.parent.mkdir(parents=True, exist_ok=True)
    with private_file_lock(path):
        write_private_bytes(path, (json.dumps({
            "installation_id": installation_id,
            "conversation_id": conversation_id,
            "secret": secret,
            "requested_role": requested_role,
            **({"host_binding_generation": host_binding_generation} if host_binding_generation else {}),
        }, sort_keys=True) + "\n").encode("utf-8"))
    return path


def profile_identity(
    output_dir: Path, adapter: str, profile: str, *, environ: dict[str, str] | None = None,
) -> tuple[str, str]:
    """Return a stable local fallback identity when the host hides its ID.

    The native host ID wins when the adapter exposes it. Otherwise the profile file
    gives one conversation a stable binding while keeping separately named subagent
    profiles isolated.
    """

    environment = os.environ if environ is None else environ
    output_dir.mkdir(parents=True, exist_ok=True)
    identity_path = output_dir / "host-identity.json"
    configured = environment.get("TSUNAGOU_HOST_CONVERSATION_ID")
    if configured:
        conversation_id = configured
    elif identity_path.is_file():
        try:
            stored = json.loads(identity_path.read_text(encoding="utf-8"))
            conversation_id = stored.get("conversation_id", "")
        except (OSError, json.JSONDecodeError):
            conversation_id = ""
    else:
        conversation_id = ""
    if not isinstance(conversation_id, str) or not conversation_id:
        conversation_id = f"tsunagou:{adapter}:{profile}:{uuid.uuid4()}"
    installation_id = environment.get("TSUNAGOU_INSTALLATION_ID") or f"{adapter}:{profile}"
    identity_path.write_text(json.dumps({
        "adapter": adapter, "profile": profile,
        "installation_id": installation_id, "conversation_id": conversation_id,
    }, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    return installation_id, conversation_id


def bridge_file_name(adapter: str, installation_id: str) -> str:
    """The bridge config's file name: adapter and installation, made path-safe."""

    component = re.sub(r"[^A-Za-z0-9_.-]+", "-", f"{adapter}-{installation_id}").strip(".")
    return f"{component or 'bridge'}.json"


def write_bridge_config(
    *, adapter: str, mode: str, installation_id: str, output_dir: Path,
    ticket_path: Path, daemon_url: str, daemon_state_dir: str, project_root: Path,
) -> Path:
    """Write how to launch this conversation's bridge, for a host to pick up.

    Everything the bridge needs to find its daemon and its ticket is an environment
    variable, so a host's MCP entry can be generated from this file mechanically —
    see ``host_registration`` for the per-host spelling of that.
    """

    output_dir.mkdir(parents=True, exist_ok=True)
    session_path = output_dir / "bridge-session.json"
    bridge_config_path = output_dir / bridge_file_name(adapter, installation_id)
    bridge_config_path.write_text(json.dumps({
        "adapter": adapter,
        "mode": mode,
        "command": "node",
        "args": [str(bridge_entry_path())],
        "env": {
            "TSUNAGOU_HTTP_URL": daemon_url,
            "TSUNAGOU_DAEMON_STATE_DIR": daemon_state_dir,
            "TSUNAGOU_TICKET_FILE": str(ticket_path),
            "TSUNAGOU_SESSION_FILE": str(session_path),
            "TSUNAGOU_PROJECT_ROOT": str(project_root),
            "TSUNAGOU_STATE_DIR": str(output_dir),
            **({"TSUNAGOU_HOST_META_KEY": HOST_META_KEYS[adapter]} if adapter in HOST_META_KEYS else {}),
        },
        "secret_fields": [],
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return bridge_config_path


def read_bridge_config(path: Path) -> dict[str, Any]:
    """Read back a launch description; a damaged file is the caller's error to raise."""

    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("bridge_config_must_be_an_object")
    return raw
