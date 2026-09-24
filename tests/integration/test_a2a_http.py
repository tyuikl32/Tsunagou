"""Loopback HTTP acceptance for the A2A adapter."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from urllib.request import Request, urlopen

import uvicorn
from tests.unit.test_a2a import _app

ROOT = Path(__file__).parents[2]


def _post(url: str, body: dict[str, object], headers: dict[str, str]) -> dict[str, object]:
    request = Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={**headers, "Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=5) as response:
        return json.load(response)


def test_a2a_http_loopback_card_message_and_task(tmp_path: Path) -> None:
    app, sender, recipient, messages = _app(tmp_path)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.time() + 10
        while not server.started and time.time() < deadline:
            time.sleep(0.05)
        assert server.started
        assert server.servers
        port = server.servers[0].sockets[0].getsockname()[1]
        base_url = f"http://127.0.0.1:{port}"

        with urlopen(f"{base_url}/.well-known/agent-card.json", timeout=5) as response:
            card = json.load(response)
        assert card["protocolVersion"] == "1.0"
        assert card["capabilities"]["pushNotifications"] is True

        body = json.loads((ROOT / "tests" / "fixtures" / "a2a" / "message-send.json").read_text(encoding="utf-8"))
        body["params"]["message"]["metadata"]["tsunagou"]["recipient_agent_id"] = recipient.agent_id
        headers = {
            "Authorization": f"Bearer {sender.secret_token}",
            "Tsunagou-Session-Id": sender.session_id,
            "Tsunagou-Connection-Epoch": str(sender.connection_epoch),
        }
        result = _post(f"{base_url}/api/v1/a2a/agents/{recipient.agent_id}", body, headers)
        assert "result" in result
        assert len(messages.messages) == 1

        task_body = json.loads((ROOT / "tests" / "fixtures" / "a2a" / "tasks-get.json").read_text(encoding="utf-8"))
        task_body["params"]["id"] = "tsunagou:task:task-1"
        task_result = _post(f"{base_url}/api/v1/a2a", task_body, headers)
        assert task_result["result"]["status"]["state"] == "working"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
