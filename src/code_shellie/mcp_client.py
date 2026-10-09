"""MCP (Model Context Protocol) client over stdio and streamable HTTP. Standard library only.

Servers are configured in ~/.config/shellie-code/mcp.json:

    {
      "mcpServers": {
        "fs": {
          "command": "npx",
          "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
          "env": {}
        },
        "remote": {
          "url": "https://example.com/mcp",
          "headers": {"Authorization": "Bearer ${MY_TOKEN}"}
        }
      }
    }

A server with "command" is launched as a subprocess and spoken to over stdin and stdout.
A server with "url" is reached over streamable HTTP. Tools are exposed to the model as
`mcp__<server>__<tool>`.
"""
import atexit
import json
import os
import queue
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from pathlib import Path

from . import __version__
from .config import CONFIG_DIR
from .term import dim, green, red

MCP_CONFIG_PATH = CONFIG_DIR / "mcp.json"
MCP_TOOL_PREFIX = "mcp__"
PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "code-shellie", "version": __version__}
CALL_TIMEOUT_SEC = 60
CONNECT_TIMEOUT_SEC = 30


def _expand_env(value: str) -> str:
    """Replace ${VAR} with the value of the environment variable VAR."""
    return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", lambda m: os.getenv(m.group(1), ""), value)


def load_mcp_config(path: Path = MCP_CONFIG_PATH) -> dict:
    """Return the mcpServers mapping from the config file, or {} if absent or unreadable."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(red(f"Cannot read {path}: {e}"), file=sys.stderr)
        return {}
    return data.get("mcpServers", {})


class MCPError(Exception):
    pass


class _HttpServer:
    """One streamable HTTP MCP server: JSON-RPC over POST, with the session id kept between calls."""

    def __init__(self, url: str, headers: dict):
        self.url = url
        self.headers = headers
        self.session_id = None
        self._next_id = 1

    def _post(self, message: dict, timeout: float):
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
            **self.headers,
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        req = urllib.request.Request(
            self.url, data=json.dumps(message).encode("utf-8"), headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as res:
                session = res.headers.get("Mcp-Session-Id")
                if session:
                    self.session_id = session
                return res.headers.get("Content-Type", ""), res.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            raise MCPError(f"HTTP {e.code}") from e
        except OSError as e:
            raise MCPError(str(e) or type(e).__name__) from e

    def request(self, method: str, params: dict = None, timeout: float = CALL_TIMEOUT_SEC):
        """Send a JSON-RPC request and return its result. Raises MCPError on protocol or transport errors."""
        msg_id = self._next_id
        self._next_id += 1
        content_type, body = self._post(
            {"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params or {}}, timeout
        )
        for message in _messages(content_type, body):
            if message.get("id") != msg_id:
                continue
            if "error" in message:
                raise MCPError(str(message["error"].get("message", message["error"])))
            return message.get("result", {})
        raise MCPError(f"no response to {method}")

    def notify(self, method: str):
        self._post({"jsonrpc": "2.0", "method": method}, CONNECT_TIMEOUT_SEC)

    def close(self):
        """Nothing to release: HTTP requests do not hold a connection open."""


def _messages(content_type: str, body: str):
    """Yield JSON-RPC messages from a plain JSON body or from a text/event-stream body."""
    if "text/event-stream" in content_type:
        for line in body.splitlines():
            if line.startswith("data:"):
                try:
                    yield json.loads(line[len("data:"):].strip())
                except ValueError:
                    continue
    elif body.strip():
        data = json.loads(body)
        for message in (data if isinstance(data, list) else [data]):
            yield message


class _StdioServer:
    """One stdio MCP server: newline-delimited JSON-RPC over the child's stdin and stdout.

    A reader thread drains stdout into a queue, so a silent server hits the timeout instead of
    blocking the REPL. Stderr is kept (its last lines help explain a failure) and is not mixed
    into the protocol. Output that is not JSON is ignored. The child runs in its own process
    group, so close() can stop anything it started.
    """

    def __init__(self, command: str, args: list, env: dict):
        self._next_id = 1
        self._lock = threading.Lock()
        self._responses = queue.Queue()
        self._stderr = deque(maxlen=20)
        self._proc = subprocess.Popen(
            [command, *args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={**os.environ, **env},
            start_new_session=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def _read_stdout(self):
        for line in self._proc.stdout:
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if not isinstance(message, dict):
                continue
            if "method" in message and "id" in message:
                # The server asks us something. This client offers no methods, so decline.
                self._send({"jsonrpc": "2.0", "id": message["id"],
                            "error": {"code": -32601, "message": "method not supported by client"}})
            elif "id" in message:
                self._responses.put(message)
        self._responses.put(None)  # stdout closed

    def _read_stderr(self):
        for line in self._proc.stderr:
            self._stderr.append(line.rstrip())

    def _send(self, message: dict):
        with self._lock:
            self._proc.stdin.write(json.dumps(message) + "\n")
            self._proc.stdin.flush()

    def _exit_message(self) -> str:
        last = self._stderr[-1] if self._stderr else ""
        code = self._proc.poll()
        if code is None:
            reason = "closed its output"
        else:
            reason = f"exited with code {code}"
        return f"server {reason}" + (f": {last}" if last else "")

    def request(self, method: str, params: dict = None, timeout: float = CALL_TIMEOUT_SEC):
        """Send a JSON-RPC request and return its result. Raises MCPError on protocol or transport errors."""
        msg_id = self._next_id
        self._next_id += 1
        try:
            self._send({"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params or {}})
        except OSError:
            raise MCPError(self._exit_message())
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise MCPError(f"no response to {method} within {timeout:g}s")
            try:
                message = self._responses.get(timeout=min(remaining, 0.5))
            except queue.Empty:
                if self._proc.poll() is not None:
                    raise MCPError(self._exit_message())
                continue
            if message is None:
                raise MCPError(self._exit_message())
            if message.get("id") != msg_id:
                continue
            if "error" in message:
                raise MCPError(str(message["error"].get("message", message["error"])))
            return message.get("result", {})

    def notify(self, method: str):
        try:
            self._send({"jsonrpc": "2.0", "method": method})
        except OSError:
            raise MCPError(self._exit_message())

    def close(self):
        """Close stdin and give the server a moment to exit, then kill its process group."""
        try:
            self._proc.stdin.close()
        except OSError:
            pass
        if self._proc.poll() is not None:
            return
        try:
            self._proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(self._proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            self._proc.wait()


class MCPManager:
    """Connects to every configured server and keeps the tools they expose."""

    def __init__(self, servers: dict):
        self.servers = servers
        self.sessions = {}   # server name -> _HttpServer or _StdioServer
        self.tools = {}      # exposed tool name -> (server name, raw tool name)
        self._declarations = []
        self.errors = {}     # server name -> startup error message

    def start(self):
        for name, cfg in self.servers.items():
            try:
                self._connect(name, cfg)
            except Exception as e:
                self.errors[name] = str(e) or type(e).__name__
                print(red(f"MCP server '{name}' failed to start: {self.errors[name]}"), file=sys.stderr)
        return self

    def _connect(self, name: str, cfg: dict):
        if "command" in cfg:
            server = _StdioServer(
                _expand_env(cfg["command"]),
                [_expand_env(a) for a in cfg.get("args", [])],
                {k: _expand_env(v) for k, v in cfg.get("env", {}).items()},
            )
        elif "url" in cfg:
            headers = {k: _expand_env(v) for k, v in cfg.get("headers", {}).items()}
            server = _HttpServer(_expand_env(cfg["url"]), headers)
        else:
            raise MCPError("config needs either 'command' (stdio) or 'url' (HTTP)")
        try:
            server.request("initialize", {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": CLIENT_INFO,
            }, timeout=CONNECT_TIMEOUT_SEC)
            server.notify("notifications/initialized")
            listed = server.request("tools/list", timeout=CONNECT_TIMEOUT_SEC)
        except Exception:
            server.close()
            raise
        self.sessions[name] = server
        tools = listed.get("tools", [])
        for tool in tools:
            exposed = f"{MCP_TOOL_PREFIX}{name}__{tool['name']}"
            self.tools[exposed] = (name, tool["name"])
            self._declarations.append({
                "name": exposed,
                "description": tool.get("description") or f"MCP tool '{tool['name']}' from server '{name}'.",
                "parametersJsonSchema": tool.get("inputSchema") or {"type": "object", "properties": {}},
            })
        print(dim(f"MCP server '{name}' connected: {len(tools)} tool(s)"))

    def print_status(self):
        """Print each configured server with its connection state and tools."""
        if not self.servers:
            print(f"No MCP servers configured. Add them to {MCP_CONFIG_PATH}.")
            return
        print("Configured MCP servers:")
        for name, cfg in self.servers.items():
            transport = "http" if "url" in cfg else "stdio"
            if name in self.sessions:
                tools = [t for t, (server, _) in self.tools.items() if server == name]
                print(f"  {green('●')} {name} ({transport}) - {len(tools)} tool(s)")
                for tool in tools:
                    print(dim(f"      {tool}"))
            else:
                reason = self.errors.get(name, "not connected")
                print(f"  {red('●')} {name} ({transport}) - failed: {reason}")

    def declarations(self) -> list:
        """Function declarations for all connected MCP tools (empty if none)."""
        return list(self._declarations)

    def has_tool(self, name: str) -> bool:
        return name in self.tools

    def call(self, name: str, args: dict) -> str:
        server_name, tool_name = self.tools[name]
        try:
            result = self.sessions[server_name].request(
                "tools/call", {"name": tool_name, "arguments": args or {}}, timeout=CALL_TIMEOUT_SEC
            )
        except Exception as e:
            return f"Error calling MCP tool '{name}': {e}"

        text = "\n".join(c.get("text", "") for c in result.get("content", []) if c.get("type") == "text")
        if result.get("isError"):
            return f"Error from MCP tool '{name}': {text or 'unknown error'}"
        return text or "[MCP tool executed with no text output]"

    def close(self):
        """Stop every stdio server this manager started."""
        for server in self.sessions.values():
            server.close()


_manager = None


def get_manager() -> MCPManager:
    """Return the process-wide MCP manager, connecting to the configured servers on first use."""
    global _manager
    if _manager is None:
        servers = load_mcp_config()
        _manager = MCPManager(servers).start() if servers else MCPManager({})
        atexit.register(shutdown_mcp)
    return _manager


def shutdown_mcp():
    """Stop the connected servers, including their child processes. Safe to call more than once."""
    global _manager
    if _manager is not None:
        _manager.close()
        _manager = None
