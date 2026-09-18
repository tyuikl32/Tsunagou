from __future__ import annotations

import platform
import shutil
import subprocess


def command_version(command: str) -> str:
    path = shutil.which(command)
    if not path:
        return "unavailable"
    try:
        return subprocess.check_output([path, "--version"], text=True, stderr=subprocess.STDOUT).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        return f"error: {exc}"


if __name__ == "__main__":
    print(f"platform={platform.platform()}")
    for name in ("python", "uv", "node", "pnpm", "npm"):
        print(f"{name}={command_version(name)}")
