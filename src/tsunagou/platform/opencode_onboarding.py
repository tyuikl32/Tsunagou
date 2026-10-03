"""Install OpenCode's credential-free, user-level current-conversation entry."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from tsunagou.platform.db.sqlite import ProjectLock
from tsunagou.platform.host_registration import ConfigChange, find_executable, host_for
from tsunagou.platform.runtime_context import installation_path, read_object, running_source_root

_MARKER = "// TSUNAGOU:MANAGED opencode-connect-v1\n"


def _config_directory() -> Path:
    host = host_for("opencode")
    executable = find_executable(host) if host else None
    if executable is None:
        raise RuntimeError("opencode_executable_missing")
    try:
        result = subprocess.run(
            [executable, "debug", "paths"], capture_output=True, text=True,
            encoding="utf-8", timeout=15, check=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("opencode_config_directory_unavailable") from exc
    for line in result.stdout.splitlines():
        fields = line.split(maxsplit=1)
        if len(fields) == 2 and fields[0] == "config" and Path(fields[1]).is_absolute():
            return Path(fields[1]).resolve()
    raise RuntimeError("opencode_config_directory_unavailable")


def _runtime() -> tuple[Path, dict[str, Any], dict[str, Any]]:
    from tsunagou.application.onboarding import opencode_routing_directory

    source = running_source_root()
    if source is None:
        raise RuntimeError("installation_source_unavailable")
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("bridge_node_unavailable")
    entry = source / "packages/bridge-server/dist/server.js"
    plugin = source / "packages/adapter-opencode/connect.js"
    if not entry.is_file() or not plugin.is_file():
        raise RuntimeError("bridge_build_missing")
    installation = read_object(installation_path())
    python = Path(sys.executable).absolute()
    if installation.get("python") and Path(str(installation.get("source_root", ""))).resolve() == source:
        candidate = Path(installation["python"]).expanduser().resolve()
        if candidate.is_file():
            python = candidate
    packages = [source / ".venv/Lib/site-packages", *sorted((source / ".venv/lib").glob("python*/site-packages"))]
    pythonpath = os.pathsep.join(str(path) for path in [source / "src", *packages] if path.is_dir())
    routes = str(opencode_routing_directory())
    runtime = {
        "command": str(python), "args": ["-m", "tsunagou"], "routingDir": routes,
        "env": {"PYTHONPATH": pythonpath, "PYTHONNOUSERSITE": "1",
                "PATH": str(Path(node).resolve().parent) + os.pathsep + os.environ.get("PATH", "")},
    }
    mcp = {
        "type": "local", "command": [str(Path(node).resolve()), str(entry)], "codemode": False,
        "environment": {"TSUNAGOU_ROUTING_DIR": routes, "TSUNAGOU_HOST_META_KEY": "ai.opencode/sessionID"},
    }
    return plugin, runtime, mcp


def prepare_opencode_host() -> ConfigChange:
    """Check all ownership conflicts before updating only our three managed files."""
    directory = _config_directory()
    source, runtime, entry = _runtime()
    config = directory / "opencode.json"
    plugin_dir = directory / "tsunagou-connect"
    bootstrap = plugin_dir / "index.js"
    package = plugin_dir / "package.json"
    body = (_MARKER + f"import {{ createConnectPlugin }} from {json.dumps(source.as_uri())};\n"
            + f"export default createConnectPlugin({json.dumps(runtime, ensure_ascii=False)});\n")
    package_body = '{"name":"tsunagou-connect","private":true,"type":"module"}\n'
    with ProjectLock(directory / ".tsunagou-registration.lock"):
        if (directory / "opencode.jsonc").exists():
            raise RuntimeError("opencode_jsonc_config_conflict")
        try:
            value = json.loads(config.read_text(encoding="utf-8-sig")) if config.exists() else {}
        except (OSError, ValueError) as exc:
            raise RuntimeError("opencode_config_invalid") from exc
        if not isinstance(value, dict):
            raise RuntimeError("opencode_config_invalid")
        plugins = value.setdefault("plugins", [])
        mcp = value.setdefault("mcp", {})
        if not isinstance(plugins, list) or not isinstance(mcp, dict):
            raise RuntimeError("opencode_config_invalid")
        servers = mcp.setdefault("servers", {})
        if not isinstance(servers, dict):
            raise RuntimeError("opencode_config_invalid")
        owned = bootstrap.is_file() and bootstrap.read_text(encoding="utf-8").startswith(_MARKER)
        if plugin_dir.exists() and not owned:
            raise RuntimeError("opencode_plugin_conflict")
        if package.exists() and package.read_text(encoding="utf-8") != package_body:
            raise RuntimeError("opencode_plugin_conflict")
        if "tsunagou" in servers and (not owned or servers["tsunagou"] != entry):
            raise RuntimeError("opencode_mcp_conflict")
        plugin_path = str(plugin_dir)
        if plugin_path not in plugins:
            plugins.append(plugin_path)
        servers["tsunagou"] = entry
        writes = {bootstrap: body, package: package_body,
                  config: json.dumps(value, ensure_ascii=False, indent=2) + "\n"}
        for path, content in writes.items():
            if path.exists() and path.read_text(encoding="utf-8") == content:
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(path.name + ".tmp")
            temporary.write_text(content, encoding="utf-8", newline="\n")
            temporary.replace(path)
    return ConfigChange("registered", tuple(writes), "Reload OpenCode once, return to the same conversation, then call tsunagou_connect.")
