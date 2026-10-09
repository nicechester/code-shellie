import os
import sys
from pathlib import Path

import pytest

from code_shellie import mcp_client
from code_shellie.mcp_client import MCPManager

FAKE = str(Path(__file__).parent / "fake_mcp_stdio.py")


def stdio_config(*mode):
    return {"command": sys.executable, "args": [FAKE, *mode]}


def test_stdio_server_connects_lists_and_calls_tools():
    manager = MCPManager({"demo": stdio_config()}).start()
    try:
        assert manager.has_tool("mcp__demo__echo")
        assert manager.declarations()[0]["name"] == "mcp__demo__echo"
        assert manager.call("mcp__demo__echo", {"text": "hi"}) == "echo: hi"
    finally:
        manager.close()


def test_non_json_output_is_ignored():
    # The fake server writes a log line before each reply; the call must still succeed
    manager = MCPManager({"demo": stdio_config()}).start()
    try:
        assert manager.call("mcp__demo__echo", {"text": "again"}) == "echo: again"
    finally:
        manager.close()


def test_server_that_exits_early_is_reported_with_its_error(capsys):
    manager = MCPManager({"bad": stdio_config("exit")}).start()

    assert "exited with code 3" in manager.errors["bad"]
    assert "fatal: missing API token" in manager.errors["bad"]
    assert not manager.has_tool("mcp__bad__echo")


def test_silent_server_times_out_during_connect(monkeypatch):
    monkeypatch.setattr(mcp_client, "CONNECT_TIMEOUT_SEC", 0.5)
    manager = MCPManager({"quiet": stdio_config("silent")}).start()
    try:
        assert "no response to initialize" in manager.errors["quiet"]
    finally:
        manager.close()


def test_missing_command_is_reported(capsys):
    manager = MCPManager({"nothing": {"command": "/no/such/binary-codesh-test"}}).start()

    assert "nothing" in manager.errors
    assert not manager.has_tool("mcp__nothing__echo")


def test_close_stops_the_child_process():
    manager = MCPManager({"demo": stdio_config()}).start()
    server = manager.sessions["demo"]

    manager.close()

    assert server._proc.poll() is not None


def test_env_from_config_reaches_the_server(monkeypatch):
    monkeypatch.setenv("CODESH_TEST_TOKEN", "from-parent")
    cfg = {"command": sys.executable, "args": [FAKE, "env"], "env": {"EXTRA": "${CODESH_TEST_TOKEN}"}}

    manager = MCPManager({"e": cfg}).start()

    # The fake server reports its environment on stderr and exits; that line appears in the error
    assert "EXTRA=from-parent" in manager.errors["e"]
