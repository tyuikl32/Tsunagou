"""User-level registration owns only its bootstrap and one credential-free MCP entry."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tsunagou.platform import opencode_onboarding as onboarding


@pytest.fixture
def config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "中文 config"
    directory.mkdir()
    monkeypatch.setattr(onboarding, "_config_directory", lambda: directory)
    monkeypatch.setattr(onboarding, "_runtime", lambda: (
        tmp_path / "connect.js", {"command": "python", "args": ["-m", "tsunagou"]},
        {"type": "local", "command": ["node", "server.js"], "environment": {
            "TSUNAGOU_ROUTING_DIR": str(tmp_path / "routes"), "TSUNAGOU_HOST_META_KEY": "ai.opencode/sessionID",
        }},
    ))
    return directory


def test_register_preserves_user_config_and_is_idempotent(config: Path) -> None:
    path = config / "opencode.json"
    path.write_text(json.dumps({"model": "user/model", "plugins": ["other"], "mcp": {
        "servers": {"other": {"type": "remote", "url": "http://localhost"}},
    }}), encoding="utf-8")
    result = onboarding.prepare_opencode_host()
    assert result.status == "registered"
    before = {file: (file.read_bytes(), file.stat().st_mtime_ns) for file in result.files}
    onboarding.prepare_opencode_host()
    assert before == {file: (file.read_bytes(), file.stat().st_mtime_ns) for file in result.files}
    value = json.loads(path.read_text(encoding="utf-8"))
    assert value["model"] == "user/model"
    assert value["plugins"][0] == "other"
    assert value["mcp"]["servers"]["other"]["url"] == "http://localhost"
    assert set(value["mcp"]["servers"]["tsunagou"]["environment"]) == {
        "TSUNAGOU_ROUTING_DIR", "TSUNAGOU_HOST_META_KEY",
    }


@pytest.mark.parametrize("conflict", ["mcp", "plugin", "jsonc", "invalid"])
def test_conflicts_leave_user_files_untouched(config: Path, conflict: str) -> None:
    path = config / "opencode.json"
    path.write_text('{"mcp":{"servers":{"tsunagou":{"command":["foreign"]}}}}'
                    if conflict == "mcp" else "[]" if conflict == "invalid" else "{}", encoding="utf-8")
    if conflict == "plugin":
        (config / "tsunagou-connect").mkdir()
        (config / "tsunagou-connect/index.js").write_text("// user plugin", encoding="utf-8")
    if conflict == "jsonc":
        (config / "opencode.jsonc").write_text("// user config\n{}", encoding="utf-8")
    before = {p: p.read_bytes() for p in config.rglob("*") if p.is_file()}
    with pytest.raises(RuntimeError, match="opencode_"):
        onboarding.prepare_opencode_host()
    assert before == {p: p.read_bytes() for p in config.rglob("*") if p.is_file() and not p.name.endswith(".lock")}


def test_user_changes_to_managed_mcp_are_not_overwritten(config: Path) -> None:
    onboarding.prepare_opencode_host()
    path = config / "opencode.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["mcp"]["servers"]["tsunagou"]["disabled"] = True
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(RuntimeError, match="opencode_mcp_conflict"):
        onboarding.prepare_opencode_host()
    assert json.loads(path.read_text(encoding="utf-8")) == value


def test_config_directory_comes_from_host_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(onboarding, "find_executable", lambda _host: "opencode")
    monkeypatch.setattr(onboarding.subprocess, "run", lambda *_a, **_kw: subprocess.CompletedProcess(
        [], 0, stdout=f"home ignored\nconfig     {tmp_path / '中文 config'}\nstate ignored\n",
    ))
    assert onboarding._config_directory() == tmp_path / "中文 config"


def test_real_python_stdout_overrides_inherited_cp936(tmp_path: Path) -> None:
    node = shutil.which("node")
    assert node is not None
    script = tmp_path / "中文 cli.py"
    script.write_text(
        "import json, os\n"
        "assert os.environ['PYTHONIOENCODING'] == 'utf-8'\n"
        "print(json.dumps(dict(status='enrolled', project_id='中文项目', agent_id='agent', role='worker'), ensure_ascii=False))\n",
        encoding="utf-8",
    )
    plugin = Path(__file__).resolve().parents[2] / "packages/adapter-opencode/connect.js"
    runner = tmp_path / "probe.mjs"
    runtime = {"command": sys.executable, "args": [str(script)], "env": {"PYTHONIOENCODING": "cp936"}}
    runner.write_text(
        f"import {{createConnectPlugin}} from {json.dumps(plugin.as_uri())};\n"
        "let tool;\n"
        f"await createConnectPlugin({json.dumps(runtime)}).setup({{tool:{{transform:async f=>f({{add:t=>tool=t}})}}}});\n"
        "console.log((await tool.execute({}, {sessionID:'actual-host'})).content[0].text);\n",
        encoding="utf-8",
    )
    result = subprocess.run([node, str(runner)], capture_output=True, text=True, encoding="utf-8", check=True)
    assert json.loads(result.stdout)["project_id"] == "中文项目"
