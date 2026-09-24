"""Codex app-server JSONL client and the managed (phase A) provider.

The provider deliberately exposes a host-neutral surface.  It never reads or
writes Tsunagou task state and it sends only the fixed coordination pull
prompt to Codex.  Raw thread/session IDs remain in ``PrivateBindingStore``.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import queue
import secrets
import shutil
import socket
import struct
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

from tsunagou.hostwake.binding import PrivateBindingStore
from tsunagou.hostwake.port import (
    HostBindingRef,
    HostCapabilityReport,
    HostEvidence,
    HostWakeError,
    HostWakePort,
    HostWakeRequest,
    ThreadHandle,
    WakeAttempt,
    utc_now,
)
from tsunagou.shared_kernel.digests import canonical_digest

_REQUIRED_METHODS = ("thread/start", "thread/resume", "turn/start")
_TERMINAL_TURN_METHODS = frozenset({"turn/completed", "turn/failed", "turn/aborted", "turn/interrupted"})
_HOST_ID_ENV_NAMES = (
    "CODEX_SESSION_ID", "CODEX_THREAD_ID", "CODEX_CONVERSATION_ID",
    "CODEX_ROLLOUT_ID", "CODEX_AGREEMENT_ID",
)


class _TransportClosed(RuntimeError):
    pass


class AppServerRpcError(HostWakeError):
    """A JSON-RPC error mapped to a stable Tsunagou adapter code."""

    def __init__(self, method: str, payload: dict[str, Any]) -> None:
        code = payload.get("code")
        message = str(payload.get("message") or "app-server request failed")
        super().__init__(
            "app_server_rpc_error",
            f"app-server rejected {method}",
            details={"method": method, "rpc_code": code, "message_digest": canonical_digest({"message": message})},
        )
        self.method = method
        self.rpc_code = code


class CodexAppServerClient:
    """Small synchronous JSONL app-server client.

    A reader thread is necessary on Windows because ``select`` cannot wait on
    anonymous subprocess pipes.  Requests are correlated by JSON-RPC ID and
    notifications remain available to the provider for turn evidence.
    """

    def __init__(
        self,
        executable: str | Path,
        *,
        args: tuple[str, ...] = ("app-server", "--stdio"),
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
        startup_timeout: float = 10.0,
    ) -> None:
        self.executable = str(executable)
        self.args = args
        self.cwd = str(cwd) if cwd is not None else None
        self.env = env
        self.startup_timeout = startup_timeout
        self.process: subprocess.Popen[str] | None = None
        self._reader_thread: threading.Thread | None = None
        self._write_lock = threading.Lock()
        self._pending: dict[int, queue.Queue[dict[str, Any] | BaseException]] = {}
        self._pending_lock = threading.Lock()
        self._notifications: queue.Queue[dict[str, Any] | BaseException] = queue.Queue()
        self._next_id = 1
        self._closed = False
        self._initialized = False
        self.server_info: dict[str, Any] = {}
        self.methods: tuple[str, ...] = ()

    @classmethod
    def from_environment(cls, *, cwd: str | Path | None = None) -> CodexAppServerClient:
        executable = os.environ.get("CODEX_CLI_PATH") or shutil.which("codex")
        if not executable:
            local_app_data = os.environ.get("LOCALAPPDATA")
            if local_app_data:
                candidates = sorted((Path(local_app_data) / "OpenAI" / "Codex" / "bin").glob("*/codex.exe"))
                if candidates:
                    executable = str(candidates[-1])
        if not executable:
            raise HostWakeError("codex_executable_not_found", "could not locate the Codex executable")
        return cls(executable, cwd=cwd)

    def start(self) -> None:
        if self.process is not None and self.process.poll() is None:
            return
        self._closed = False
        self._initialized = False
        try:
            self.process = subprocess.Popen(
                [self.executable, *self.args],
                cwd=self.cwd,
                env=self.env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as exc:
            raise HostWakeError("app_server_start_failed", "could not start Codex app-server") from exc
        assert self.process.stdout is not None
        self._reader_thread = threading.Thread(target=self._read_loop, args=(self.process.stdout,), daemon=True)
        self._reader_thread.start()

    def initialize(self, *, client_name: str = "tsunagou", client_version: str = "0.1.0") -> dict[str, Any]:
        if self._initialized and self.process is not None and self.process.poll() is None:
            return {"serverInfo": self.server_info, "methods": list(self.methods)}
        self.start()
        result = self.request(
            "initialize",
            {"clientInfo": {"name": client_name, "title": "Tsunagou", "version": client_version}},
            timeout=self.startup_timeout,
        )
        self.notify("initialized", {})
        self.server_info = dict(result.get("serverInfo") or result.get("server_info") or {})
        methods = result.get("methods") or result.get("capabilities", {}).get("methods") or []
        self.methods = tuple(sorted(str(item) for item in methods if isinstance(item, str)))
        self._initialized = True
        return result

    def request(self, method: str, params: dict[str, Any], *, timeout: float = 30.0) -> dict[str, Any]:
        if self.process is None or self.process.poll() is not None or self._closed:
            raise HostWakeError("app_server_unavailable", "Codex app-server is not running")
        if self.process.stdin is None:
            raise HostWakeError("app_server_stdin_unavailable", "Codex app-server stdin is unavailable")
        request_id = self._next_id
        self._next_id += 1
        response_queue: queue.Queue[dict[str, Any] | BaseException] = queue.Queue(maxsize=1)
        with self._pending_lock:
            self._pending[request_id] = response_queue
        try:
            self._write({"method": method, "id": request_id, "params": params})
            try:
                item = response_queue.get(timeout=timeout)
            except queue.Empty as exc:
                raise HostWakeError("app_server_request_timeout", f"app-server request timed out: {method}") from exc
            if isinstance(item, BaseException):
                raise HostWakeError("app_server_connection_lost", "app-server connection closed") from item
            if "error" in item:
                error = item.get("error")
                raise AppServerRpcError(method, error if isinstance(error, dict) else {})
            result = item.get("result")
            if not isinstance(result, dict):
                raise HostWakeError("app_server_result_invalid", f"app-server returned no object result: {method}")
            return result
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)

    def notify(self, method: str, params: dict[str, Any]) -> None:
        if self.process is None or self.process.stdin is None or self._closed:
            raise HostWakeError("app_server_unavailable", "Codex app-server is not running")
        self._write({"method": method, "params": params})

    def next_notification(self, *, timeout: float = 0.0) -> dict[str, Any] | None:
        try:
            item = self._notifications.get(timeout=timeout)
        except queue.Empty:
            return None
        if isinstance(item, BaseException):
            raise HostWakeError("app_server_connection_lost", "app-server connection closed") from item
        return item

    def close(self) -> None:
        self._closed = True
        process = self.process
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        self.process = None
        self._initialized = False
        with self._pending_lock:
            pending = list(self._pending.values())
            self._pending.clear()
        for response_queue in pending:
            response_queue.put(_TransportClosed())

    def _write(self, message: dict[str, Any]) -> None:
        process = self.process
        if process is None or process.stdin is None:
            raise HostWakeError("app_server_unavailable", "Codex app-server is not running")
        serialized = json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n"
        with self._write_lock:
            try:
                process.stdin.write(serialized)
                process.stdin.flush()
            except OSError as exc:
                raise HostWakeError("app_server_write_failed", "could not write to app-server") from exc

    def _read_loop(self, stdout: Any) -> None:
        try:
            for line in stdout:
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(message, dict):
                    continue
                request_id = message.get("id")
                if isinstance(request_id, int):
                    with self._pending_lock:
                        response_queue = self._pending.get(request_id)
                    if response_queue is not None:
                        response_queue.put(message)
                        continue
                self._notifications.put(message)
        finally:
            if not self._closed:
                error = _TransportClosed()
                with self._pending_lock:
                    pending = list(self._pending.values())
                for response_queue in pending:
                    response_queue.put(error)
                self._notifications.put(error)


class UnixWebSocketAppServerClient:
    """JSON-RPC client for the documented Unix-socket WebSocket transport.

    Codex's Unix app-server listener is a WebSocket endpoint rather than a
    newline-delimited stream.  Keeping this small client in the adapter avoids
    depending on a browser/WebSocket package in the daemon runtime.
    """

    def __init__(
        self,
        socket_path: str,
        *,
        executable: str | None = None,
        cwd: str | Path | None = None,
        startup_timeout: float = 10.0,
    ) -> None:
        self.socket_path = socket_path
        self.executable = executable
        self.cwd = str(cwd) if cwd is not None else None
        self.startup_timeout = startup_timeout
        self.socket: socket.socket | None = None
        self._process: subprocess.Popen[bytes] | None = None
        self.process: UnixWebSocketAppServerClient | None = self
        self._reader_thread: threading.Thread | None = None
        self._write_lock = threading.Lock()
        self._pending: dict[int, queue.Queue[dict[str, Any] | BaseException]] = {}
        self._pending_lock = threading.Lock()
        self._notifications: queue.Queue[dict[str, Any] | BaseException] = queue.Queue()
        self._next_id = 1
        self._closed = False
        self._initialized = False
        self.server_info: dict[str, Any] = {}
        self.methods: tuple[str, ...] = ()

    def start(self) -> None:
        if (self.socket is not None or (self._process is not None and self._process.poll() is None)) and not self._closed:
            return
        self._closed = False
        unix_family = getattr(socket, "AF_UNIX", None)
        if isinstance(unix_family, int):
            connection = socket.socket(unix_family, socket.SOCK_STREAM)
            connection.settimeout(self.startup_timeout)
            try:
                connection.connect(self.socket_path)
                self._handshake(connection, connection)
                connection.settimeout(None)
            except OSError as exc:
                connection.close()
                raise HostWakeError("app_server_socket_unavailable", "could not connect to the Codex Unix socket") from exc
            self.socket = connection
        else:
            executable = self.executable
            if not executable:
                executable = CodexAppServerClient.from_environment(cwd=self.cwd).executable
            try:
                process = subprocess.Popen(
                    [executable, "app-server", "proxy", "--sock", self.socket_path],
                    cwd=self.cwd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except OSError as exc:
                raise HostWakeError("app_server_proxy_start_failed", "could not start the Codex app-server proxy") from exc
            if process.stdin is None or process.stdout is None:
                process.kill()
                raise HostWakeError("app_server_proxy_unavailable", "Codex app-server proxy has no byte streams")
            self._process = process
            try:
                self._handshake(process.stdout, process.stdin)
            except (OSError, HostWakeError):
                process.kill()
                process.wait(timeout=2)
                self._process = None
                raise
        self._reader_thread = threading.Thread(target=self._read_loop, daemon=True, name="tsunagou-codex-unix-ws")
        self._reader_thread.start()

    def initialize(self, *, client_name: str = "tsunagou", client_version: str = "0.1.0") -> dict[str, Any]:
        if self._initialized and self._connected() and not self._closed:
            return {"serverInfo": self.server_info, "methods": list(self.methods)}
        self.start()
        result = self.request(
            "initialize",
            {"clientInfo": {"name": client_name, "title": "Tsunagou", "version": client_version}},
            timeout=self.startup_timeout,
        )
        self.notify("initialized", {})
        self.server_info = dict(result.get("serverInfo") or result.get("server_info") or {})
        methods = result.get("methods") or result.get("capabilities", {}).get("methods") or []
        self.methods = tuple(sorted(str(item) for item in methods if isinstance(item, str)))
        self._initialized = True
        return result

    def request(self, method: str, params: dict[str, Any], *, timeout: float = 30.0) -> dict[str, Any]:
        if not self._connected() or self._closed:
            raise HostWakeError("app_server_unavailable", "Codex Unix socket is not connected")
        request_id = self._next_id
        self._next_id += 1
        response_queue: queue.Queue[dict[str, Any] | BaseException] = queue.Queue(maxsize=1)
        with self._pending_lock:
            self._pending[request_id] = response_queue
        try:
            self._send_json({"method": method, "id": request_id, "params": params})
            try:
                item = response_queue.get(timeout=timeout)
            except queue.Empty as exc:
                raise HostWakeError("app_server_request_timeout", f"app-server request timed out: {method}") from exc
            if isinstance(item, BaseException):
                raise HostWakeError("app_server_connection_lost", "Codex Unix socket connection closed") from item
            if "error" in item:
                error = item.get("error")
                raise AppServerRpcError(method, error if isinstance(error, dict) else {})
            result = item.get("result")
            if not isinstance(result, dict):
                raise HostWakeError("app_server_result_invalid", f"app-server returned no object result: {method}")
            return result
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)

    def notify(self, method: str, params: dict[str, Any]) -> None:
        if not self._connected() or self._closed:
            raise HostWakeError("app_server_unavailable", "Codex Unix socket is not connected")
        self._send_json({"method": method, "params": params})

    def next_notification(self, *, timeout: float = 0.0) -> dict[str, Any] | None:
        try:
            item = self._notifications.get(timeout=timeout)
        except queue.Empty:
            return None
        if isinstance(item, BaseException):
            raise HostWakeError("app_server_connection_lost", "Codex Unix socket connection closed") from item
        return item

    def poll(self) -> int | None:
        return 0 if self._closed or (self._process is not None and self._process.poll() is not None) else None

    def close(self) -> None:
        self._closed = True
        connection = self.socket
        self.socket = None
        if connection is not None:
            try:
                connection.close()
            except OSError:
                pass
        process = self._process
        self._process = None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        with self._pending_lock:
            pending = list(self._pending.values())
            self._pending.clear()
        for response_queue in pending:
            response_queue.put(_TransportClosed())

    def _send_json(self, message: dict[str, Any]) -> None:
        self._send_frame(json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))

    def _send_frame(self, payload: bytes, *, opcode: int = 1) -> None:
        if not self._connected() or self._closed:
            raise HostWakeError("app_server_unavailable", "Codex Unix socket is not connected")
        length = len(payload)
        if length < 126:
            header = bytes((0x80 | opcode, 0x80 | length))
        elif length < 65536:
            header = bytes((0x80 | opcode, 0x80 | 126)) + struct.pack(">H", length)
        else:
            header = bytes((0x80 | opcode, 0x80 | 127)) + struct.pack(">Q", length)
        mask = secrets.token_bytes(4)
        masked = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        with self._write_lock:
            try:
                self._write_raw(header + mask + masked)
            except OSError as exc:
                raise HostWakeError("app_server_write_failed", "could not write to Codex Unix socket") from exc

    def _handshake(self, reader: Any, writer: Any) -> None:
        key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
        request = (
            "GET / HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        ).encode("ascii")
        self._write_raw(request, writer=writer)
        response = bytearray()
        while b"\r\n\r\n" not in response:
            chunk = self._read_stream(reader, 4096)
            if not chunk:
                raise HostWakeError("app_server_socket_handshake_failed", "Codex Unix socket closed during WebSocket handshake")
            response.extend(chunk)
            if len(response) > 16384:
                raise HostWakeError("app_server_socket_handshake_failed", "Codex WebSocket handshake response is too large")
        header = bytes(response).split(b"\r\n\r\n", 1)[0].decode("latin-1")
        lines = header.split("\r\n")
        if not lines or " 101 " not in f" {lines[0]} ":
            raise HostWakeError("app_server_socket_handshake_failed", "Codex Unix socket did not accept WebSocket upgrade")
        expected = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()).decode("ascii")
        accept = next((line.split(":", 1)[1].strip() for line in lines[1:] if line.lower().startswith("sec-websocket-accept:")), "")
        if accept != expected:
            raise HostWakeError("app_server_socket_handshake_failed", "Codex WebSocket accept key did not match")

    def _read_loop(self) -> None:
        fragment_opcode: int | None = None
        fragments = bytearray()
        try:
            while not self._closed and self._connected():
                final, opcode, payload = self._recv_frame()
                if opcode == 8:
                    break
                if opcode == 9:
                    self._send_frame(payload, opcode=10)
                    continue
                if opcode == 0:
                    if fragment_opcode is None:
                        continue
                    fragments.extend(payload)
                    if not final:
                        continue
                    opcode = fragment_opcode
                    payload = bytes(fragments)
                    fragment_opcode = None
                    fragments.clear()
                elif not final and opcode in {1, 2}:
                    fragment_opcode = opcode
                    fragments = bytearray(payload)
                    continue
                if opcode != 1:
                    continue
                try:
                    message = json.loads(payload.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if not isinstance(message, dict):
                    continue
                request_id = message.get("id")
                if isinstance(request_id, int):
                    with self._pending_lock:
                        response_queue = self._pending.get(request_id)
                    if response_queue is not None:
                        response_queue.put(message)
                        continue
                self._notifications.put(message)
        except (OSError, HostWakeError) as exc:
            if not self._closed:
                with self._pending_lock:
                    pending = list(self._pending.values())
                for response_queue in pending:
                    response_queue.put(exc)
                self._notifications.put(exc)

    def _recv_frame(self) -> tuple[bool, int, bytes]:
        if not self._connected():
            raise HostWakeError("app_server_connection_lost", "Codex Unix socket connection closed")
        first, second = self._recv_exact(2)
        final = bool(first & 0x80)
        opcode = first & 0x0F
        length = second & 0x7F
        if length == 126:
            length = struct.unpack(">H", self._recv_exact(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", self._recv_exact(8))[0]
        masked = bool(second & 0x80)
        mask = self._recv_exact(4) if masked else b""
        payload = bytearray(self._recv_exact(length))
        if masked:
            payload = bytearray(value ^ mask[index % 4] for index, value in enumerate(payload))
        return final, opcode, bytes(payload)

    def _recv_exact(self, length: int) -> bytes:
        output = bytearray()
        while len(output) < length:
            chunk = self._read_raw(length - len(output))
            if not chunk:
                raise HostWakeError("app_server_connection_lost", "Codex Unix socket connection closed")
            output.extend(chunk)
        return bytes(output)

    def _connected(self) -> bool:
        return self.socket is not None or (self._process is not None and self._process.poll() is None)

    def _write_raw(self, payload: bytes, *, writer: Any | None = None) -> None:
        target = writer
        if target is None:
            if self.socket is not None:
                self.socket.sendall(payload)
                return
            target = self._process.stdin if self._process is not None else None
        if target is None:
            raise OSError("transport is closed")
        target.write(payload)
        target.flush()

    def _read_raw(self, length: int) -> bytes:
        if self.socket is not None:
            return self.socket.recv(length)
        if self._process is None or self._process.stdout is None:
            raise OSError("transport is closed")
        return self._process.stdout.read(length)

    @staticmethod
    def _read_stream(stream: Any, length: int) -> bytes:
        if hasattr(stream, "recv"):
            return cast(bytes, stream.recv(length))
        if hasattr(stream, "read1"):
            return cast(bytes, stream.read1(length))
        return cast(bytes, stream.read(length))


AppServerClient = CodexAppServerClient | UnixWebSocketAppServerClient


def _toml_string(value: str) -> str:
    """Encode one string as a TOML basic string without shell parsing."""

    return json.dumps(str(value), ensure_ascii=False)


def _load_bridge_config(path: str | Path) -> dict[str, Any]:
    """Load and validate one private bridge JSON record.

    Codex app-server currently has no ``--ignore-user-config`` switch.  The
    managed provider therefore overrides the one Tsunagou MCP entry that it
    owns.  The bridge file remains private; only its command, args and env are
    sent as process-local config arguments.
    """

    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HostWakeError("bridge_config_invalid", "managed bridge configuration is unreadable") from exc
    if not isinstance(raw, dict):
        raise HostWakeError("bridge_config_invalid", "managed bridge configuration must be an object")
    command = raw.get("command")
    args = raw.get("args", [])
    env = raw.get("env", {})
    if not isinstance(command, str) or not command:
        raise HostWakeError("bridge_config_invalid", "managed bridge command is missing")
    if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
        raise HostWakeError("bridge_config_invalid", "managed bridge args are invalid")
    if not isinstance(env, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in env.items()):
        raise HostWakeError("bridge_config_invalid", "managed bridge environment is invalid")
    return raw


def _bridge_config_args(path: str | Path) -> tuple[str, ...]:
    raw = _load_bridge_config(path)
    result: list[str] = [
        "-c", f"mcp_servers.tsunagou.command={_toml_string(raw['command'])}",
        "-c", f"mcp_servers.tsunagou.args={json.dumps(raw['args'], ensure_ascii=False)}",
        "-c", "mcp_servers.tsunagou.default_tools_approval_mode=\"approve\"",
    ]
    for key, value in sorted(raw["env"].items()):
        result.extend(["-c", f"mcp_servers.tsunagou.env.{key}={_toml_string(value)}"])
    return tuple(result)


def _bridge_config_values(path: str | Path) -> dict[str, Any]:
    """Return the same private bridge as a thread-level Codex config object."""

    raw = _load_bridge_config(path)
    return {
        "command": raw["command"],
        "args": list(raw["args"]),
        "env": dict(raw["env"]),
        "default_tools_approval_mode": "approve",
    }


class ManagedCodexProvider:
    """Stage A provider that owns one app-server client per Agent binding."""

    provider_name = "managed_app_server"

    def __init__(
        self,
        store: PrivateBindingStore,
        *,
        client_factory: Callable[[dict[str, Any]], AppServerClient] | None = None,
        wake_timeout: float = 2.0,
    ) -> None:
        self.store = store
        self.client_factory = client_factory or self._default_client
        self.wake_timeout = wake_timeout
        self._clients: dict[str, AppServerClient] = {}
        self._active_turns: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    def register_binding(
        self,
        *,
        provider: str | None = None,
        agent_id: str,
        binding_id: str,
        adapter_profile: str,
        cwd: str | Path,
        scope_digest: str,
        policy_digest: str,
        executable: str | None = None,
        model: str | None = None,
        approval_policy: str | None = None,
        sandbox: str | None = None,
        sandbox_policy: dict[str, Any] | None = None,
        bridge_config: str | Path | None = None,
        endpoint: str | None = None,
        thread_id: str | None = None,
        attach_confirmed: bool = False,
    ) -> HostBindingRef:
        if provider is not None and provider != self.provider_name:
            raise HostWakeError("host_provider_unsupported", "binding provider does not match managed app-server")
        if endpoint is not None or thread_id is not None or attach_confirmed:
            raise HostWakeError("managed_binding_attach_fields_unsupported", "managed bindings do not accept Desktop attach fields")
        if sandbox is not None and sandbox_policy is not None:
            raise HostWakeError("sandbox_policy_conflict", "sandbox and sandbox_policy cannot both be configured")
        ref = HostBindingRef(
            binding_id=binding_id,
            agent_id=agent_id,
            provider=self.provider_name,
            adapter_profile=adapter_profile,
            endpoint_kind="stdio",
            cwd_digest=canonical_digest({"cwd": str(Path(cwd).resolve())}),
            scope_digest=scope_digest,
            policy_digest=policy_digest,
            status="ready",
            capabilities={name: "unknown" for name in _REQUIRED_METHODS},
        )
        return self.store.put(
            ref,
            executable=executable,
            extra={
                "cwd": str(Path(cwd).resolve()),
                "model": model,
                "approvalPolicy": approval_policy,
                "sandbox": sandbox,
                "sandboxPolicy": sandbox_policy,
                "bridgeConfig": str(Path(bridge_config).expanduser().resolve()) if bridge_config else None,
            },
        )

    def probe(self, binding: HostBindingRef) -> HostCapabilityReport:
        record = self._record(binding)
        client = self._client(binding.agent_id, record)
        try:
            client.initialize()
        except HostWakeError as exc:
            return HostCapabilityReport(
                provider=self.provider_name,
                status="degraded",
                version=None,
                transport="stdio",
                reason=exc.code,
            )
        methods = set(client.methods)
        version = client.server_info.get("version") if isinstance(client.server_info, dict) else None
        try:
            thread = self.ensure_thread(binding)
            methods.update({"thread/start", "thread/resume"})
            thread_data = thread.metadata.get("thread") if isinstance(thread.metadata, dict) else None
            if isinstance(thread_data, dict) and thread_data.get("cliVersion"):
                version = thread_data["cliVersion"]
        except HostWakeError as exc:
            return HostCapabilityReport(
                provider=self.provider_name,
                status="degraded",
                version=str(version) if version is not None else None,
                transport="stdio",
                methods=tuple(sorted(methods)),
                reason=exc.code,
            )
        capabilities = {
            method: cast(Any, "supported" if method in methods else "unknown")
            for method in _REQUIRED_METHODS
        }
        # Some app-server versions expose no method catalogue.  An initialize
        # response alone proves connectivity, not method support.
        status = cast(Any, "supported" if methods and all(value == "supported" for value in capabilities.values()) else "unknown")
        evidence = canonical_digest({"provider": self.provider_name, "version": version, "methods": sorted(methods)})
        current_item = self.store.get(binding.agent_id)
        current_ref, current_record = current_item if current_item is not None else (binding, record)
        self.store.put(
            replace(current_ref, status=current_ref.status, capabilities=capabilities,
                    last_probe={"version": version, "methods": sorted(methods), "evidence_digest": evidence}),
            executable=current_record.get("executable"), extra=current_record.get("extra", {}),
        )
        return HostCapabilityReport(
            provider=self.provider_name,
            status=status,
            version=str(version) if version is not None else None,
            transport="stdio",
            methods=tuple(sorted(methods)),
            capabilities=capabilities,
            evidence_digest=evidence,
        )

    def ensure_thread(self, binding: HostBindingRef) -> ThreadHandle:
        record = self._record(binding)
        client = self._client(binding.agent_id, record)
        client.initialize()
        raw_thread_id = record.get("thread_id")
        if raw_thread_id:
            try:
                resume_params: dict[str, Any] = {"threadId": raw_thread_id}
                extra = record.get("extra", {})
                for key in ("cwd", "model", "approvalPolicy", "sandbox", "sandboxPolicy"):
                    if extra.get(key) is not None:
                        resume_params[key] = extra[key]
                bridge_config = extra.get("bridgeConfig")
                if bridge_config:
                    resume_params["config"] = {"mcp_servers": {"tsunagou": _bridge_config_values(str(bridge_config))}}
                result = client.request("thread/resume", resume_params)
                thread = result.get("thread") or {}
                return ThreadHandle(
                    str(thread.get("id") or raw_thread_id),
                    str(thread.get("sessionId")) if thread.get("sessionId") else None,
                    True,
                    result,
                )
            except AppServerRpcError as exc:
                # Codex does not materialize a brand-new thread's rollout file
                # until its first turn.  A provider probe can therefore leave
                # a valid thread ID that is not resumable yet.  Only the
                # protocol's invalid/not-found responses use this recovery;
                # all other RPC errors remain visible to the caller.
                if exc.rpc_code not in {-32600, -32602}:
                    raise
        extra = record.get("extra", {})
        params: dict[str, Any] = {"cwd": extra.get("cwd"), "serviceName": "tsunagou"}
        for key in ("model", "approvalPolicy", "sandbox", "sandboxPolicy"):
            if extra.get(key) is not None:
                params[key] = extra[key]
        bridge_config = extra.get("bridgeConfig")
        if bridge_config:
            params["config"] = {"mcp_servers": {"tsunagou": _bridge_config_values(str(bridge_config))}}
        result = client.request("thread/start", {key: value for key, value in params.items() if value is not None})
        thread = result.get("thread") or {}
        thread_id = str(thread.get("id") or "")
        if not thread_id:
            raise HostWakeError("app_server_thread_invalid", "thread/start did not return a thread id")
        session_id = str(thread.get("sessionId")) if thread.get("sessionId") else None
        updated = replace(
            binding,
            thread_id_digest=canonical_digest({"thread_id": thread_id}),
            session_id_digest=canonical_digest({"session_id": session_id}) if session_id else None,
            status="ready",
        )
        self.store.put(updated, thread_id=thread_id, session_id=session_id, executable=record.get("executable"), extra=extra)
        return ThreadHandle(thread_id, session_id, False, result)

    def wake(self, request: HostWakeRequest) -> WakeAttempt:
        request.validate()
        binding = request.binding
        evidence: list[HostEvidence] = []
        try:
            thread = self.ensure_thread(binding)
            evidence.append(self._evidence("thread_resumed" if thread.resumed else "thread_started", request, "observed", {
                "thread_id_digest": canonical_digest({"thread_id": thread.thread_id}),
            }))
            record = self._record(binding)
            client = self._client(binding.agent_id, record)
            params: dict[str, Any] = {
                "threadId": thread.thread_id,
                "input": [{
                    "type": "text",
                    "text": (
                        "Use the Tsunagou MCP tools context__project_read and inbox__claim/fetch/presented "
                        "to read the coordination context and pending inbox delivery, then continue the "
                        "coordination work. Do not use shell or infer the message contents from this prompt."
                    ),
                }],
            }
            extra = record.get("extra", {})
            for key in ("cwd", "approvalPolicy", "sandbox", "sandboxPolicy", "model"):
                if extra.get(key) is not None:
                    params[key] = extra[key]
            bridge_config = extra.get("bridgeConfig")
            if bridge_config:
                params["config"] = {"mcp_servers": {"tsunagou": _bridge_config_values(str(bridge_config))}}
            result = client.request("turn/start", params)
            turn = result.get("turn") or {}
            turn_id = str(turn.get("id") or "")
            if not turn_id:
                raise HostWakeError("app_server_turn_invalid", "turn/start did not return a turn id")
            evidence.append(self._evidence("turn_started", request, "observed", {
                "thread_id_digest": canonical_digest({"thread_id": thread.thread_id}),
                "turn_id_digest": canonical_digest({"turn_id": turn_id}),
            }))
            completed = self._wait_for_turn(client, thread.thread_id, turn_id, request, evidence)
            attempt = WakeAttempt(
                request.wake_attempt_id, request.agent_id, request.message_id,
                "completed" if completed else "running",
                thread_id_digest=canonical_digest({"thread_id": thread.thread_id}),
                turn_id_digest=canonical_digest({"turn_id": turn_id}),
                evidence=tuple(evidence),
            )
            if not completed:
                with self._lock:
                    self._active_turns[request.wake_attempt_id] = {
                        "request": request,
                        "client": client,
                        "thread_id": thread.thread_id,
                        "turn_id": turn_id,
                        "evidence": evidence,
                    }
            return attempt
        except HostWakeError as exc:
            return WakeAttempt(
                request.wake_attempt_id, request.agent_id, request.message_id, "failed",
                evidence=tuple(evidence), error_code=exc.code, error_message=exc.message,
            )

    def poll(self, wake_attempt_id: str) -> WakeAttempt | None:
        """Consume terminal events for a bounded wake without starting a turn."""

        with self._lock:
            active = self._active_turns.get(wake_attempt_id)
        if active is None:
            return None
        request = cast(HostWakeRequest, active["request"])
        evidence = cast(list[HostEvidence], active["evidence"])
        client = cast(AppServerClient, active["client"])
        completed = self._wait_for_turn(
            client, str(active["thread_id"]), str(active["turn_id"]), request, evidence,
            timeout=min(0.5, self.wake_timeout),
        )
        attempt = WakeAttempt(
            request.wake_attempt_id, request.agent_id, request.message_id,
            "completed" if completed else "running",
            thread_id_digest=canonical_digest({"thread_id": active["thread_id"]}),
            turn_id_digest=canonical_digest({"turn_id": active["turn_id"]}),
            evidence=tuple(evidence),
        )
        if completed:
            with self._lock:
                self._active_turns.pop(wake_attempt_id, None)
        return attempt

    def inspect(self, binding: HostBindingRef) -> dict[str, Any]:
        record = self._record(binding)
        client = self._clients.get(binding.agent_id)
        return {
            "provider": self.provider_name,
            "agent_id": binding.agent_id,
            "status": binding.status,
            "process_running": bool(client and client.process and client.process.poll() is None),
            "thread_id_digest": binding.thread_id_digest,
            "session_id_digest": binding.session_id_digest,
            "record_present": bool(record),
        }

    def close(self, binding: HostBindingRef, reason: str) -> None:
        del reason
        with self._lock:
            client = self._clients.pop(binding.agent_id, None)
            for attempt_id, active in list(self._active_turns.items()):
                request = cast(HostWakeRequest, active["request"])
                if request.agent_id == binding.agent_id:
                    self._active_turns.pop(attempt_id, None)
            if client is not None:
                client.close()

    def _wait_for_turn(
        self, client: AppServerClient, thread_id: str, turn_id: str,
        request: HostWakeRequest, evidence: list[HostEvidence],
        *, timeout: float | None = None,
    ) -> bool:
        deadline = time.monotonic() + (self.wake_timeout if timeout is None else timeout)
        while time.monotonic() < deadline:
            notification = client.next_notification(timeout=min(0.1, max(0, deadline - time.monotonic())))
            if notification is None:
                continue
            if notification.get("method") not in _TERMINAL_TURN_METHODS:
                continue
            params = notification.get("params") or {}
            turn = params.get("turn") or {}
            if turn.get("id") not in {None, turn_id}:
                continue
            evidence.append(self._evidence("turn_completed", request, "observed", {
                "thread_id_digest": canonical_digest({"thread_id": thread_id}),
                "turn_id_digest": canonical_digest({"turn_id": turn_id}),
                "terminal_method": notification.get("method"),
                "status": turn.get("status"),
            }))
            return True
        return False

    def _record(self, binding: HostBindingRef) -> dict[str, Any]:
        stored = self.store.get(binding.agent_id)
        if stored is None:
            raise HostWakeError("host_binding_not_found", "host binding is not registered")
        ref, record = stored
        if ref.binding_id != binding.binding_id or ref.binding_revision != binding.binding_revision:
            raise HostWakeError("host_binding_revision_conflict", "host binding revision is stale")
        return record

    def _client(self, agent_id: str, record: dict[str, Any]) -> AppServerClient:
        with self._lock:
            client = self._clients.get(agent_id)
            if client is None:
                client = self.client_factory(record)
                self._clients[agent_id] = client
            return client

    @staticmethod
    def _default_client(record: dict[str, Any]) -> AppServerClient:
        executable = record.get("executable")
        extra = record.get("extra") or {}
        cwd = extra.get("cwd")
        bridge_config = extra.get("bridgeConfig")
        args: tuple[str, ...] = ("app-server", "--stdio")
        if bridge_config:
            args += _bridge_config_args(str(bridge_config))
        # The daemon may itself have been launched from a Codex conversation.
        # Never leak that parent conversation identity into the child bridge;
        # it would make separate managed workers appear to be one host.
        environment = os.environ.copy()
        for name in _HOST_ID_ENV_NAMES:
            environment.pop(name, None)
        if executable:
            return CodexAppServerClient(str(executable), args=args, cwd=cwd, env=environment)
        client = CodexAppServerClient.from_environment(cwd=cwd)
        client.args = args
        client.env = environment
        return client

    @staticmethod
    def _evidence(kind: str, request: HostWakeRequest, status: str, details: dict[str, Any]) -> HostEvidence:
        digest = canonical_digest({"kind": kind, "attempt": request.wake_attempt_id, "details": details})
        return HostEvidence(kind, request.wake_attempt_id, request.agent_id, request.message_id, status, digest, utc_now(), details)


def _desktop_socket_path(endpoint: str | None) -> str:
    """Validate the explicit local endpoint used by the Desktop attach path."""

    if not isinstance(endpoint, str) or not endpoint.startswith("unix://"):
        raise HostWakeError(
            "desktop_attach_transport_unsupported",
            "Desktop attach currently accepts only an explicit unix:// endpoint",
        )
    path = endpoint.removeprefix("unix://")
    if not path or not Path(path).is_absolute():
        raise HostWakeError("desktop_attach_endpoint_invalid", "Desktop attach endpoint must be an absolute local socket path")
    return path


class DesktopAttachProvider(ManagedCodexProvider):
    """Stage B provider for an explicitly confirmed local app-server thread.

    This provider never creates a thread.  It uses the public Codex proxy
    command to connect to a user-supplied Unix socket and resumes only the
    private thread id recorded during the user-controlled attach operation.
    """

    provider_name = "desktop_attach"

    def register_binding(
        self,
        *,
        provider: str | None = None,
        agent_id: str,
        binding_id: str,
        adapter_profile: str,
        cwd: str | Path,
        scope_digest: str,
        policy_digest: str,
        endpoint: str | None = None,
        thread_id: str | None = None,
        attach_confirmed: bool = False,
        executable: str | None = None,
        model: str | None = None,
        approval_policy: str | None = None,
        sandbox: str | None = None,
        sandbox_policy: dict[str, Any] | None = None,
        bridge_config: str | Path | None = None,
    ) -> HostBindingRef:
        if provider is not None and provider != self.provider_name:
            raise HostWakeError("host_provider_unsupported", "binding provider does not match Desktop attach")
        if not attach_confirmed:
            raise HostWakeError("desktop_attach_confirmation_required", "Desktop attach requires explicit user confirmation")
        socket_path = _desktop_socket_path(endpoint)
        if not thread_id or not thread_id.strip():
            raise HostWakeError("desktop_thread_required", "Desktop attach requires an existing thread id")
        if sandbox is not None and sandbox_policy is not None:
            raise HostWakeError("sandbox_policy_conflict", "sandbox and sandbox_policy cannot both be configured")
        ref = HostBindingRef(
            binding_id=binding_id,
            agent_id=agent_id,
            provider=self.provider_name,
            adapter_profile=adapter_profile,
            thread_id_digest=canonical_digest({"thread_id": thread_id}),
            endpoint_kind="unix_proxy",
            cwd_digest=canonical_digest({"cwd": str(Path(cwd).resolve())}),
            scope_digest=scope_digest,
            policy_digest=policy_digest,
            status="ready",
            capabilities={name: "unknown" for name in (*_REQUIRED_METHODS, "thread/read")},
        )
        extra = {
            "cwd": str(Path(cwd).resolve()),
            "model": model,
            "approvalPolicy": approval_policy,
            "sandbox": sandbox,
            "sandboxPolicy": sandbox_policy,
            "bridgeConfig": str(Path(bridge_config).expanduser().resolve()) if bridge_config else None,
            "endpoint": endpoint,
            "socketPath": socket_path,
            "attachConfirmed": True,
        }
        # A re-attach for the same Agent must not reuse the old proxy process;
        # its endpoint and thread identity belong to the previous binding.
        with self._lock:
            previous = self._clients.pop(agent_id, None)
            if previous is not None:
                previous.close()
        return self.store.put(ref, thread_id=thread_id, endpoint=endpoint, executable=executable, extra=extra)

    def probe(self, binding: HostBindingRef) -> HostCapabilityReport:
        """Probe without resuming or creating the user-selected thread."""

        record = self._record(binding)
        client = self._client(binding.agent_id, record)
        methods: set[str] = set()
        try:
            client.initialize()
            methods.update(client.methods)
            thread_id = record.get("thread_id")
            if not thread_id:
                raise HostWakeError("desktop_thread_required", "Desktop attach has no private thread id")
            result = client.request("thread/read", {"threadId": thread_id, "includeTurns": False})
            thread = result.get("thread") or {}
            if str(thread.get("id") or "") != str(thread_id):
                raise HostWakeError("desktop_thread_identity_mismatch", "thread/read returned a different thread")
            methods.add("thread/read")
            session_id = thread.get("sessionId")
            if session_id:
                updated = replace(
                    binding,
                    session_id_digest=canonical_digest({"session_id": str(session_id)}),
                    capabilities={**binding.capabilities, "thread/read": "supported"},
                    last_probe={"thread_confirmation": "supported"},
                )
                self.store.put(
                    updated,
                    thread_id=str(thread_id),
                    session_id=str(session_id),
                    endpoint=record.get("endpoint"),
                    executable=record.get("executable"),
                    extra=record.get("extra", {}),
                )
            capabilities = {
                "thread/read": "supported",
                "thread/resume": "supported" if "thread/resume" in methods else "unknown",
                "turn/start": "supported" if "turn/start" in methods else "unknown",
            }
            status = (
                "supported"
                if capabilities["thread/resume"] == "supported" and capabilities["turn/start"] == "supported"
                else "unknown"
            )
            version = client.server_info.get("version") if isinstance(client.server_info, dict) else None
            evidence = canonical_digest({"provider": self.provider_name, "thread_confirmation": True, "methods": sorted(methods)})
            return HostCapabilityReport(
                provider=self.provider_name,
                status=cast(Any, status),
                version=str(version) if version is not None else None,
                transport="unix_proxy",
                methods=tuple(sorted(methods)),
                capabilities=cast(dict[str, Any], capabilities),
                evidence_digest=evidence,
            )
        except AppServerRpcError as exc:
            return HostCapabilityReport(
                provider=self.provider_name,
                status="unknown",
                version=None,
                transport="unix_proxy",
                methods=tuple(sorted(methods)),
                reason=f"rpc_{exc.rpc_code}",
            )
        except HostWakeError as exc:
            return HostCapabilityReport(
                provider=self.provider_name,
                status="degraded",
                version=None,
                transport="unix_proxy",
                methods=tuple(sorted(methods)),
                reason=exc.code,
            )

    def ensure_thread(self, binding: HostBindingRef) -> ThreadHandle:
        record = self._record(binding)
        raw_thread_id = record.get("thread_id")
        if not raw_thread_id:
            raise HostWakeError("desktop_thread_required", "Desktop attach has no private thread id")
        client = self._client(binding.agent_id, record)
        client.initialize()
        try:
            result = client.request("thread/resume", {"threadId": str(raw_thread_id)})
        except AppServerRpcError as exc:
            raise HostWakeError("desktop_thread_unavailable", "the attached Desktop thread cannot be resumed") from exc
        thread = result.get("thread") or {}
        returned_id = str(thread.get("id") or raw_thread_id)
        if returned_id != str(raw_thread_id):
            raise HostWakeError("desktop_thread_identity_mismatch", "thread/resume returned a different thread")
        session_id = str(thread.get("sessionId")) if thread.get("sessionId") else None
        if session_id:
            self.store.put(
                replace(binding, session_id_digest=canonical_digest({"session_id": session_id})),
                thread_id=str(raw_thread_id), session_id=session_id,
                endpoint=record.get("endpoint"), executable=record.get("executable"), extra=record.get("extra", {}),
            )
        return ThreadHandle(str(raw_thread_id), session_id, True, result)

    @staticmethod
    def _default_client(record: dict[str, Any]) -> AppServerClient:
        extra = record.get("extra") or {}
        endpoint = record.get("endpoint") or extra.get("endpoint")
        socket_path = _desktop_socket_path(endpoint)
        return UnixWebSocketAppServerClient(
            socket_path,
            executable=record.get("executable"),
            cwd=extra.get("cwd"),
        )


class HostWakeProviderRegistry:
    """Route one shared host-wake port to managed or explicitly attached Codex."""

    def __init__(self, managed: ManagedCodexProvider, desktop: DesktopAttachProvider) -> None:
        self.managed = managed
        self.desktop = desktop
        self.store = managed.store

    def register_binding(self, *, provider: str = "managed_app_server", **kwargs: Any) -> HostBindingRef:
        if provider == "managed_app_server":
            return self.managed.register_binding(**kwargs)
        if provider == "desktop_attach":
            return self.desktop.register_binding(**kwargs)
        raise HostWakeError("host_provider_unsupported", "unknown host binding provider")

    def _provider(self, binding: HostBindingRef) -> HostWakePort:
        if binding.provider == "desktop_attach":
            return self.desktop
        if binding.provider == "managed_app_server":
            return self.managed
        raise HostWakeError("host_provider_unsupported", "unknown host binding provider")

    def probe(self, binding: HostBindingRef) -> HostCapabilityReport:
        return self._provider(binding).probe(binding)

    def ensure_thread(self, binding: HostBindingRef) -> ThreadHandle:
        return self._provider(binding).ensure_thread(binding)

    def wake(self, request: HostWakeRequest) -> WakeAttempt:
        return self._provider(request.binding).wake(request)

    def poll(self, wake_attempt_id: str) -> WakeAttempt | None:
        for provider in (self.desktop, self.managed):
            result = provider.poll(wake_attempt_id)
            if result is not None:
                return result
        return None

    def inspect(self, binding: HostBindingRef) -> dict[str, Any]:
        return self._provider(binding).inspect(binding)

    def close(self, binding: HostBindingRef, reason: str) -> None:
        self._provider(binding).close(binding, reason)
