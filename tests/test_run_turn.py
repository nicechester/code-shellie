from types import SimpleNamespace

import pytest
from google.genai import errors

from code_shellie import core
from code_shellie.core import Agent

class FakeChat:
    """Returns scripted responses and records every message sent to it."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.sent = []

    def send_message(self, message):
        self.sent.append(message)
        return self.responses.pop(0)

def make_agent(chat):
    # Skip __init__, which needs an API key and a live client
    agent = Agent.__new__(Agent)
    agent.chat = chat
    agent.model = "test-model"
    agent.prompt_token_count = 0
    agent.total_token_count = 0
    agent.model_limit = None
    return agent

def reply(function_calls=None, text=None):
    return SimpleNamespace(function_calls=function_calls, text=text, usage_metadata=None)

def test_parallel_calls_send_all_results_in_one_request(monkeypatch):
    calls = [
        SimpleNamespace(id="call-1", name="read_file", args={"file_path": "a"}),
        SimpleNamespace(id="call-1", name="read_file", args={"file_path": "b"}),
    ]
    chat = FakeChat([reply(function_calls=calls), reply(text="done")])
    monkeypatch.setattr(core, "execute_tool", lambda name, args: f"contents of {args['file_path']}")

    make_agent(chat).run_turn("read both")

    assert len(chat.sent) == 2
    results = chat.sent[1]
    assert [p.function_response.name for p in results] == ["read_file", "read_file"]
    assert [p.function_response.id for p in results] == ["call-1", "call-1"]
    assert [p.function_response.response["result"] for p in results] == ["contents of a", "contents of b"]

def test_follow_up_tool_call_is_not_dropped(monkeypatch):
    first = [SimpleNamespace(id="call-1", name="read_file", args={"file_path": "a"})]
    follow_up = [SimpleNamespace(id="call-1", name="list_directory", args={"dir_path": "."})]
    chat = FakeChat([reply(function_calls=first), reply(function_calls=follow_up), reply(text="done")])
    monkeypatch.setattr(core, "execute_tool", lambda name, args: f"{name} ran")

    agent = make_agent(chat)
    agent.run_turn("look around")

    assert len(chat.sent) == 3
    assert chat.sent[2][0].function_response.name == "list_directory"

def quota_error():
    body = {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "Quota exceeded for input tokens"}}
    return errors.ClientError(429, body)

class FailingChat:
    """Raises 429 for the first `failures` calls, then returns a reply."""

    def __init__(self, failures):
        self.failures = failures
        self.calls = 0

    def send_message(self, message):
        self.calls += 1
        if self.calls <= self.failures:
            raise quota_error()
        return reply(text="done")

def test_rate_limit_waits_60s_and_retries(monkeypatch):
    sleeps = []
    monkeypatch.setattr(core.time, "sleep", lambda s: sleeps.append(s))
    chat = FailingChat(failures=2)

    response = make_agent(chat)._send("hi")

    assert response.text == "done"
    assert sleeps == [60, 60]

def test_rate_limit_gives_up_without_exiting_process(monkeypatch):
    monkeypatch.setattr(core.time, "sleep", lambda s: None)
    agent = make_agent(FailingChat(failures=10))

    with pytest.raises(errors.APIError):
        agent._send("hi")
    assert agent.chat.calls == 4  # first attempt plus 3 retries
