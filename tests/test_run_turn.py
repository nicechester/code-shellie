import copy

import pytest

from code_shellie import core
from code_shellie.core import Agent
from code_shellie.gemini import GeminiError


class FakeModel:
    """Returns scripted (status, body) pairs and records a snapshot of the history sent with each request."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, payload):
        self.requests.append(copy.deepcopy(payload["contents"]))
        return self.responses.pop(0)


def make_agent(responses):
    # Skip __init__, which needs an API key and a live client
    agent = Agent.__new__(Agent)
    agent.model = "test-model"
    agent.api_key = "test-key"
    agent.system_instruction = "system"
    agent.history = []
    agent.prompt_token_count = 0
    agent.total_token_count = 0
    agent.model_limit = None
    agent.last_answer = ""
    agent._generate = FakeModel(responses)  # instance attribute shadows the method
    return agent


@pytest.fixture(autouse=True)
def no_mcp_tools(monkeypatch):
    # Keep tests away from the user's real MCP config
    monkeypatch.setattr(core, "all_declarations", lambda: [])


def ok(function_calls=(), text=None):
    parts = [{"functionCall": {"name": name, "args": args}} for name, args in function_calls]
    if text is not None:
        parts.append({"text": text})
    return 200, {"candidates": [{"content": {"role": "model", "parts": parts}}]}


def failure(status, message="boom", status_name=""):
    return status, {"error": {"code": status, "status": status_name, "message": message}}


def quota_error():
    return failure(429, "Quota exceeded for input tokens", "RESOURCE_EXHAUSTED")


def function_responses(content):
    return [(p["functionResponse"]["name"], p["functionResponse"]["response"]["result"])
            for p in content["parts"] if "functionResponse" in p]


def test_parallel_calls_send_all_results_in_one_request(monkeypatch):
    calls = [("read_file", {"file_path": "a"}), ("read_file", {"file_path": "b"})]
    agent = make_agent([ok(function_calls=calls), ok(text="done")])
    monkeypatch.setattr(core, "execute_tool", lambda name, args: f"contents of {args['file_path']}")

    agent.run_turn("read both")

    assert len(agent._generate.requests) == 2
    assert function_responses(agent._generate.requests[1][-1]) == [
        ("read_file", "contents of a"),
        ("read_file", "contents of b"),
    ]


def test_follow_up_tool_call_is_not_dropped(monkeypatch):
    first = [("read_file", {"file_path": "a"})]
    follow_up = [("list_directory", {"dir_path": "."})]
    agent = make_agent([ok(function_calls=first), ok(function_calls=follow_up), ok(text="done")])
    monkeypatch.setattr(core, "execute_tool", lambda name, args: f"{name} ran")

    agent.run_turn("look around")

    assert len(agent._generate.requests) == 3
    assert function_responses(agent._generate.requests[2][-1]) == [("list_directory", "list_directory ran")]


def test_rate_limit_waits_60s_and_retries(monkeypatch):
    sleeps = []
    monkeypatch.setattr(core.time, "sleep", lambda s: sleeps.append(s))
    agent = make_agent([quota_error(), quota_error(), ok(text="done")])

    reply = agent._send([{"text": "hi"}])

    assert reply.text == "done"
    assert sleeps == [60, 60]


def test_rate_limit_gives_up_without_exiting_process(monkeypatch):
    monkeypatch.setattr(core.time, "sleep", lambda s: None)
    agent = make_agent([quota_error()] * 10)

    with pytest.raises(GeminiError) as info:
        agent._send([{"text": "hi"}])
    assert info.value.code == 429
    assert len(agent._generate.requests) == 4  # first attempt plus 3 retries


def test_daily_quota_is_not_retried(monkeypatch):
    sleeps = []
    monkeypatch.setattr(core.time, "sleep", lambda s: sleeps.append(s))
    per_day = {"error": {"details": [{"violations": [{"quotaId": "GenerateRequestsPerDayPerProject"}]}]}}
    agent = make_agent([(429, per_day)])

    with pytest.raises(GeminiError):
        agent._send([{"text": "hi"}])
    assert sleeps == []
    assert len(agent._generate.requests) == 1


def test_server_errors_back_off_then_succeed(monkeypatch):
    sleeps = []
    monkeypatch.setattr(core.time, "sleep", lambda s: sleeps.append(s))
    agent = make_agent([failure(500), failure(503), ok(text="done")])

    assert agent._send([{"text": "hi"}]).text == "done"
    assert sleeps == [1, 2]


def test_failed_turn_is_removed_from_history():
    agent = make_agent([failure(400, "bad request")])

    with pytest.raises(GeminiError):
        agent.run_turn("hello")
    assert agent.history == []


@pytest.fixture
def compact_view():
    # verbose is a class-level setting that the REPL toggles; restore it after each test
    previous = Agent.verbose
    Agent.verbose = False
    yield
    Agent.verbose = previous


def test_compact_view_shows_one_line_per_tool_call(monkeypatch, capsys, compact_view):
    agent = make_agent([ok(function_calls=[("read_file", {"file_path": "secret.txt"})]), ok(text="done")])
    monkeypatch.setattr(core, "execute_tool", lambda name, args: "secret contents")

    agent.run_turn("read it")
    out = capsys.readouterr().out

    assert "read_file called" in out
    assert "Executing tool" not in out
    assert "secret contents" not in out


def test_compact_view_reports_edited_path_after_write_file(monkeypatch, capsys, compact_view):
    agent = make_agent([ok(function_calls=[("write_file", {"file_path": "notes/a.md", "content": "x"})]),
                        ok(text="done")])
    monkeypatch.setattr(core, "execute_tool", lambda name, args: "Successfully wrote to notes/a.md")

    agent.run_turn("write it")

    assert "notes/a.md edited" in capsys.readouterr().out


def test_compact_view_always_shows_failed_tool_calls(monkeypatch, capsys, compact_view):
    agent = make_agent([ok(function_calls=[("read_file", {"file_path": "missing"})]), ok(text="done")])
    monkeypatch.setattr(core, "execute_tool", lambda name, args: "Error: File 'missing' does not exist.")

    agent.run_turn("read it")

    assert "read_file failed" in capsys.readouterr().out


def test_verbose_view_keeps_tool_arguments_and_results(monkeypatch, capsys, compact_view):
    Agent.verbose = True
    agent = make_agent([ok(function_calls=[("read_file", {"file_path": "a.txt"})]), ok(text="done")])
    monkeypatch.setattr(core, "execute_tool", lambda name, args: "file body")

    agent.run_turn("read it")
    out = capsys.readouterr().out

    assert "Executing tool: read_file" in out
    assert "file body" in out


def test_view_does_not_change_what_is_sent_to_model(monkeypatch, compact_view):
    monkeypatch.setattr(core, "execute_tool", lambda name, args: "body")

    results = []
    for verbose in (False, True):
        Agent.verbose = verbose
        agent = make_agent([ok(function_calls=[("read_file", {"file_path": "a"})]), ok(text="done")])
        agent.run_turn("read it")
        results.append(function_responses(agent._generate.requests[1][-1]))

    assert results[0] == results[1] == [("read_file", "body")]


def test_compact_view_always_shows_failed_web_search(monkeypatch, capsys, compact_view):
    agent = make_agent([ok(function_calls=[("execute_web_search", {"query": "x"})]), ok(text="done")])
    monkeypatch.setattr(core, "execute_tool", lambda name, args: "Web search failed (HTTP 429)")

    agent.run_turn("search it")

    assert "execute_web_search failed" in capsys.readouterr().out


def test_answer_after_web_search_hints_at_sources(monkeypatch, capsys, compact_view):
    monkeypatch.setattr(core.gemini, "last_sources", [("npmjs.com", "https://r.example/1")])
    agent = make_agent([ok(function_calls=[("execute_web_search", {"query": "x"})]), ok(text="done")])
    monkeypatch.setattr(core, "execute_tool", lambda name, args: "done")

    agent.run_turn("search it")

    assert "type /sources for the full links" in capsys.readouterr().out


def test_answer_without_search_has_no_sources_hint(monkeypatch, capsys, compact_view):
    monkeypatch.setattr(core.gemini, "last_sources", [("npmjs.com", "https://r.example/1")])
    agent = make_agent([ok(text="plain answer")])

    agent.run_turn("hello")

    assert "/sources" not in capsys.readouterr().out
