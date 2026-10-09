import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from code_shellie import mcp_client
from code_shellie.mcp_client import MCPManager, _messages


class _Handler(BaseHTTPRequestHandler):
    """A minimal streamable HTTP MCP server with one tool, echo."""

    def log_message(self, *args):
        pass

    def do_POST(self):
        message = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        method = message.get("method")
        if method == "notifications/initialized":
            self.send_response(202)
            self.end_headers()
            return
        if method == "initialize":
            result = {"protocolVersion": mcp_client.PROTOCOL_VERSION, "capabilities": {}}
        elif method == "tools/list":
            result = {"tools": [{"name": "echo", "description": "Echo text",
                                 "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}}}]}
        elif method == "tools/call":
            text = message["params"]["arguments"]["text"]
            result = {"content": [{"type": "text", "text": f"echo: {text}"}], "isError": False}
        else:
            result = {}
        reply = json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Mcp-Session-Id", "session-1")
        self.send_header("Content-Length", str(len(reply)))
        self.end_headers()
        self.wfile.write(reply)


@pytest.fixture
def server():
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/mcp"
    httpd.shutdown()


def test_connects_lists_and_calls_tools(server):
    manager = MCPManager({"demo": {"url": server}}).start()

    assert manager.has_tool("mcp__demo__echo")
    assert manager.declarations()[0]["name"] == "mcp__demo__echo"
    assert manager.call("mcp__demo__echo", {"text": "hi"}) == "echo: hi"


def test_unreachable_server_is_reported_and_skipped(capsys):
    manager = MCPManager({"down": {"url": "http://127.0.0.1:1/mcp"}}).start()

    assert "down" in manager.errors
    assert not manager.has_tool("mcp__down__anything")


def test_messages_from_plain_json_and_event_stream():
    assert list(_messages("application/json", '{"id": 1, "result": {}}')) == [{"id": 1, "result": {}}]
    stream = 'event: message\ndata: {"id": 2, "result": {"ok": true}}\n\n'
    assert list(_messages("text/event-stream", stream)) == [{"id": 2, "result": {"ok": True}}]
