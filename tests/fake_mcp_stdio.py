"""A minimal stdio MCP server for tests. Usage: fake_mcp_stdio.py [mode]

mode: normal (default), exit (exit at once with an error on stderr), silent (never answer),
env (report the EXTRA environment variable on stderr and exit).
"""
import json
import os
import sys
import time

mode = sys.argv[1] if len(sys.argv) > 1 else "normal"

if mode == "exit":
    sys.stderr.write("fatal: missing API token\n")
    sys.exit(3)
if mode == "env":
    sys.stderr.write(f"EXTRA={os.environ.get('EXTRA', '')}\n")
    sys.exit(0)

for line in sys.stdin:
    if mode == "silent":
        time.sleep(60)
    message = json.loads(line)
    if "id" not in message:
        continue  # notifications get no reply
    method = message["method"]
    if method == "initialize":
        result = {"protocolVersion": "2025-06-18", "capabilities": {}}
    elif method == "tools/list":
        result = {"tools": [{"name": "echo", "description": "Echo text",
                             "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}}}]}
    elif method == "tools/call":
        text = message["params"]["arguments"]["text"]
        result = {"content": [{"type": "text", "text": f"echo: {text}"}], "isError": False}
    else:
        result = {}
    sys.stdout.write("this is a log line, not JSON\n")
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}) + "\n")
    sys.stdout.flush()
