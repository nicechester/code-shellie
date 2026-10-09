"""MCP (Model Context Protocol) client for servers reached over streamable HTTP.

Servers are configured in ~/.config/shellie-code/mcp.json:

    {
      "mcpServers": {
        "remote": {
          "url": "https://example.com/mcp",
          "headers": {"Authorization": "Bearer ${MY_TOKEN}"}
        }
      }
    }

Tools are exposed to the model as `mcp__<server>__<tool>`. Servers with a
"command" (stdio transport) are reported as unsupported for now.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

from .config import CONFIG_DIR
from .term import dim, green, red

MCP_CONFIG_PATH = CONFIG_DIR / "mcp.json"
MCP_TOOL_PREFIX = "mcp__"
PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "code-shellie", "version": "0.1.0"}
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

    def __init__(self, url: str, headers: dict, timeout: int):
        self.url = url
        self.headers = headers
        self.timeout = timeout
        self.session_id = None
        self._next_id = 1

    def _post(self, message: dict):
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
            with urllib.request.urlopen(req, timeout=self.timeout) as res:
                session = res.headers.get("Mcp-Session-Id")
                if session:
                    self.session_id = session
                return res.headers.get("Content-Type", ""), res.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            raise MCPError(f"HTTP {e.code}") from e
        except OSError as e:
            raise MCPError(str(e) or type(e).__name__) from e

    def request(self, method: str, params: dict = None):
        """Send a JSON-RPC request and return its result. Raises MCPError on protocol or transport errors."""
        msg_id = self._next_id
        self._next_id += 1
        content_type, body = self._post({"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params or {}})
        for message in _messages(content_type, body):
            if message.get("id") != msg_id:
                continue
            if "error" in message:
                raise MCPError(str(message["error"].get("message", message["error"])))
            return message.get("result", {})
        raise MCPError(f"no response to {method}")

    def notify(self, method: str):
        self._post({"jsonrpc": "2.0", "method": method})


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


class MCPManager:
    """Connects to every configured HTTP server and keeps the tools they expose."""

    def __init__(self, servers: dict):
        self.servers = servers
        self.sessions = {}   # server name -> _HttpServer
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
        if "url" not in cfg:
            raise MCPError("stdio servers ('command') are not supported yet; use a 'url' server")
        headers = {k: _expand_env(v) for k, v in cfg.get("headers", {}).items()}
        server = _HttpServer(_expand_env(cfg["url"]), headers, CONNECT_TIMEOUT_SEC)
        server.request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": CLIENT_INFO,
        })
        server.notify("notifications/initialized")
        listed = server.request("tools/list")
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
                "tools/call", {"name": tool_name, "arguments": args or {}}
            )
        except Exception as e:
            return f"Error calling MCP tool '{name}': {e}"

        text = "\n".join(c.get("text", "") for c in result.get("content", []) if c.get("type") == "text")
        if result.get("isError"):
            return f"Error from MCP tool '{name}': {text or 'unknown error'}"
        return text or "[MCP tool executed with no text output]"


_manager = None


def get_manager() -> MCPManager:
    """Return the process-wide MCP manager, connecting to the configured servers on first use."""
    global _manager
    if _manager is None:
        servers = load_mcp_config()
        _manager = MCPManager(servers).start() if servers else MCPManager({})
    return _manager


def shutdown_mcp():
    """Forget the connected servers. HTTP sessions hold no open sockets, so nothing else is needed."""
    global _manager
    _manager = None
