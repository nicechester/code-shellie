import copy
import time

import pytest

from code_shellie import core, gemini, sessions
from code_shellie.core import KEEP_TURNS, Agent
from code_shellie.gemini import GeminiError


class FakeModel:
    """Returns scripted (status, body) pairs and records a snapshot of each request's payload."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.payloads = []

    def __call__(self, payload):
        self.payloads.append(copy.deepcopy(payload))
        return self.responses.pop(0)


def ok(text, prompt_tokens=0):
    return 200, {
        "candidates": [{"content": {"role": "model", "parts": [{"text": text}]}}],
        "usageMetadata": {"promptTokenCount": prompt_tokens},
    }


def turn(n):
    """One completed user turn: a prompt and the model's answer."""
    return [
        {"role": "user", "parts": [{"text": f"question {n}"}]},
        {"role": "model", "parts": [{"text": f"answer {n}"}]},
    ]


def make_agent(responses, turns=6):
    # Skip __init__, which needs an API key and a live client
    agent = Agent.__new__(Agent)
    agent.model = "test-model"
    agent.api_key = "test-key"
    agent.system_instruction = "system"
    agent.history = [message for n in range(1, turns + 1) for message in turn(n)]
    agent.session = None
    agent.last_edits = {}
    agent.last_answer = ""
    agent.prompt_token_count = 9000
    agent.total_token_count = 0
    agent.model_limit = 10000
    agent._generate = FakeModel(responses)  # instance attribute shadows the method
    return agent


@pytest.fixture(autouse=True)
def isolated_sessions(monkeypatch, tmp_path):
    monkeypatch.setattr(core, "all_declarations", lambda: [])
    monkeypatch.setattr(sessions, "SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr(gemini, "count_tokens", lambda model, key, payload: 1234)


def prompts(history):
    return [m["parts"][0]["text"] for m in history if m["role"] == "user"]


def test_keeps_last_turns_verbatim_and_summarizes_the_rest():
    agent = make_agent([ok("The user asked six questions.")])
    recent = agent.history[-KEEP_TURNS * 2:]

    summarized = agent.compress()

    assert summarized == 6 - KEEP_TURNS
    assert agent.history[2:] == recent
    assert "The user asked six questions." in agent.history[0]["parts"][0]["text"]
    assert agent.history[1]["role"] == "model"
    assert len(agent.history) == 2 + KEEP_TURNS * 2


def test_summary_request_sends_older_turns_and_no_tools():
    agent = make_agent([ok("summary")])

    agent.compress()

    request = agent._generate.payloads[0]
    assert "tools" not in request
    assert request["contents"][0]["parts"][0]["text"] == "question 1"
    assert request["contents"][-1]["parts"][0]["text"] == core.SUMMARY_REQUEST


def test_nothing_to_compress_leaves_chat_alone():
    agent = make_agent([], turns=KEEP_TURNS)
    before = copy.deepcopy(agent.history)

    assert agent.compress() == 0
    assert agent.history == before
    assert agent._generate.payloads == []


def test_failed_summary_leaves_history_unchanged(monkeypatch):
    monkeypatch.setattr(core.time, "sleep", lambda seconds: None)
    agent = make_agent([(400, {"error": {"message": "bad request"}})])
    before = copy.deepcopy(agent.history)

    with pytest.raises(GeminiError):
        agent.compress()

    assert agent.history == before
    assert agent.prompt_token_count == 9000


def test_empty_summary_is_an_error_and_leaves_history_unchanged():
    agent = make_agent([ok("   ")])
    before = copy.deepcopy(agent.history)

    with pytest.raises(GeminiError):
        agent.compress()

    assert agent.history == before


def test_context_count_drops_after_compression():
    agent = make_agent([ok("summary")])

    agent.compress()

    assert agent.prompt_token_count == 1234


def test_context_count_is_kept_when_it_cannot_be_fetched(monkeypatch):
    monkeypatch.setattr(gemini, "count_tokens", lambda model, key, payload: None)
    agent = make_agent([ok("summary")])

    agent.compress()

    assert agent.prompt_token_count == 9000


def test_compressed_session_is_saved_and_resumes_compressed(monkeypatch):
    agent = make_agent([ok("summary")])
    agent.session = {
        "id": "0a1b2c3d", "started": time.time(), "cwd": "/tmp", "model": "test-model",
        "description": "question 1",
    }

    agent.compress()

    saved = sessions.load("0a1b2c3d")
    assert saved["history"] == agent.history

    resumed = Agent.__new__(Agent)
    resumed.history = []
    resumed.session = None
    resumed.prompt_token_count = 0
    resumed.total_token_count = 0
    resumed.restore(saved)
    assert resumed.history == agent.history
    assert "summary" in resumed.history[0]["parts"][0]["text"]


def test_turn_starts_skip_tool_results():
    agent = make_agent([])
    agent.history = [
        {"role": "user", "parts": [{"text": "read it"}]},
        {"role": "model", "parts": [{"functionCall": {"name": "read_file", "args": {}}}]},
        {"role": "user", "parts": [{"functionResponse": {"name": "read_file", "response": {}}}]},
        {"role": "model", "parts": [{"text": "done"}]},
    ]

    assert agent._turn_starts() == [0]


def test_compress_then_next_turn_sends_summary_and_new_prompt(monkeypatch):
    agent = make_agent([ok("summary"), ok("fresh answer")])
    monkeypatch.setattr(core, "execute_tool", lambda name, args: "")

    agent.compress()
    agent.run_turn("new question")

    sent = agent._generate.payloads[1]["contents"]
    assert "summary" in sent[0]["parts"][0]["text"]
    assert sent[-1]["parts"][0]["text"] == "new question"
    assert prompts(agent.history)[-1] == "new question"
