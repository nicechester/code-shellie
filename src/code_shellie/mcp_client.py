"""MCP (Model Context Protocol) server support.

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

A server with "command" is launched over stdio; a server with "url" is reached
over streamable HTTP. Tools are exposed to the model as
`mcp__<server>__<tool>`.
"""
import asyncio
import atexit
import json
import os
import re
import threading
from contextlib import AsyncExitStack
from pathlib import Path

from google.genai import types
from rich.console import Console

from .config import CONFIG_DIR

MCP_CONFIG_PATH = CONFIG_DIR / "mcp.json"
MCP_TOOL_PREFIX = "mcp__"
CALL_TIMEOUT_SEC = 60
CONNECT_TIMEOUT_SEC = 30

console = Console()


def _expand_env(value: str) -> str:
    """Replace ${VAR} with the value of the environment variable VAR."""
    return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", lambda m: os.getenv(m.group(1), ""), value)


def load_mcp_config(path: Path = MCP_CONFIG_PATH) -> dict:
    """Return the mcpServers mapping from the config file, or {} if absent."""
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("mcpServers", {})


class MCPManager:
    """Owns a background asyncio loop with one session per configured server."""

    def __init__(self, servers: dict):
        self.servers = servers
        self.sessions = {}   # server name -> ClientSession
        self.tools = {}      # exposed tool name -> (server name, raw tool name)
        self.declarations = []
        self.errors = {}     # server name -> startup error message
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()
        self._ready = threading.Event()
        self._supervisor_future = None
        self._stop = None

    def _run(self, coro, timeout):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout=timeout)

    def start(self):
        """Connect to every configured server. Failing servers are reported and skipped."""
        # The supervisor task enters and exits every connection context itself,
        # because anyio requires enter and exit to happen in the same task.
        self._supervisor_future = asyncio.run_coroutine_threadsafe(self._supervise(), self._loop)
        self._ready.wait(timeout=CONNECT_TIMEOUT_SEC * max(1, len(self.servers)))
        return self

    async def _supervise(self):
        self._stop = asyncio.Event()
        async with AsyncExitStack() as stack:
            for name, cfg in self.servers.items():
                try:
                    await asyncio.wait_for(self._connect(stack, name, cfg), CONNECT_TIMEOUT_SEC)
                except Exception as e:
                    self.errors[name] = str(e) or type(e).__name__
                    console.print(f"[bold red]MCP server '{name}' failed to start: {self.errors[name]}[/bold red]")
            self._ready.set()
            await self._stop.wait()

    async def _connect(self, stack, name, cfg):
        from mcp import ClientSession

        if "command" in cfg:
            from mcp import StdioServerParameters
            from mcp.client.stdio import stdio_client

            params = StdioServerParameters(
                command=_expand_env(cfg["command"]),
                args=[_expand_env(a) for a in cfg.get("args", [])],
                env={k: _expand_env(v) for k, v in cfg.get("env", {}).items()} or None,
            )
            read, write = await stack.enter_async_context(stdio_client(params))
        elif "url" in cfg:
            from mcp.client.streamable_http import streamablehttp_client

            headers = {k: _expand_env(v) for k, v in cfg.get("headers", {}).items()}
            read, write, _ = await stack.enter_async_context(
                streamablehttp_client(_expand_env(cfg["url"]), headers=headers or None)
            )
        else:
            raise ValueError("config needs either 'command' (stdio) or 'url' (HTTP)")

        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        self.sessions[name] = session

        listed = await session.list_tools()
        for tool in listed.tools:
            exposed = f"{MCP_TOOL_PREFIX}{name}__{tool.name}"
            self.tools[exposed] = (name, tool.name)
            self.declarations.append(
                types.FunctionDeclaration(
                    name=exposed,
                    description=tool.description or f"MCP tool '{tool.name}' from server '{name}'.",
                    parameters_json_schema=tool.inputSchema or {"type": "object", "properties": {}},
                )
            )
        console.print(f"[dim]MCP server '{name}' connected: {len(listed.tools)} tool(s)[/dim]")

    def print_status(self):
        """Print each configured server with its connection state and tools."""
        if not self.servers:
            console.print(f"No MCP servers configured. Add them to [bold]{MCP_CONFIG_PATH}[/bold].")
            return
        console.print("[bold yellow]Configured MCP servers:[/bold yellow]")
        for name, cfg in self.servers.items():
            transport = "http" if "url" in cfg else "stdio"
            if name in self.sessions:
                tools = [t for t, (server, _) in self.tools.items() if server == name]
                console.print(f"  [green]●[/green] [cyan]{name}[/cyan] ({transport}) - {len(tools)} tool(s)")
                for tool in tools:
                    console.print(f"      [dim]{tool}[/dim]")
            else:
                reason = self.errors.get(name, "not connected")
                console.print(f"  [red]●[/red] [cyan]{name}[/cyan] ({transport}) - failed: {reason}")

    def tool_declarations(self) -> list:
        """Function declarations for all connected MCP tools (empty if none)."""
        return [types.Tool(function_declarations=self.declarations)] if self.declarations else []

    def has_tool(self, name: str) -> bool:
        return name in self.tools

    def call(self, name: str, args: dict) -> str:
        server, tool_name = self.tools[name]
        try:
            result = self._run(self.sessions[server].call_tool(tool_name, args or {}), CALL_TIMEOUT_SEC)
        except Exception as e:
            return f"Error calling MCP tool '{name}': {e}"

        text = "\n".join(c.text for c in result.content if getattr(c, "type", None) == "text")
        if result.isError:
            return f"Error from MCP tool '{name}': {text or 'unknown error'}"
        return text or "[MCP tool executed with no text output]"

    def close(self):
        if self._stop is None:
            return
        self._loop.call_soon_threadsafe(self._stop.set)
        try:
            self._supervisor_future.result(timeout=CALL_TIMEOUT_SEC)
        except Exception:
            pass
        self._stop = None
        self._loop.call_soon_threadsafe(self._loop.stop)


_manager = None


def get_manager() -> MCPManager:
    """Return the process-wide MCP manager, starting it on first use."""
    global _manager
    if _manager is None:
        servers = load_mcp_config()
        _manager = MCPManager(servers).start() if servers else MCPManager({})
        atexit.register(_manager.close)
    return _manager
