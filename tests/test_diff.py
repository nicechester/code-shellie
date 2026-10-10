import copy

import pytest

from code_shellie import core, sessions
from code_shellie.core import Agent


class FakeModel:
    """Returns scripted (status, body) pairs, in order."""

    def __init__(self, responses):
        self.responses = list(responses)

    def __call__(self, payload):
        return self.responses.pop(0)


def make_agent(responses):
    # Skip __init__, which needs an API key and a live client
    agent = Agent.__new__(Agent)
    agent.model = "test-model"
    agent.api_key = "test-key"
    agent.system_instruction = "system"
    agent.history = []
    agent.session = None
    agent.prompt_token_count = 0
    agent.total_token_count = 0
    agent.model_limit = None
    agent.last_answer = ""
    agent.last_edits = {}
    agent._generate = FakeModel(responses)  # instance attribute shadows the method
    return agent


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch, tmp_path):
    monkeypatch.setattr(core, "all_declarations", lambda: [])
    monkeypatch.setattr(sessions, "SESSIONS_DIR", tmp_path / "sessions")


def ok(function_calls=(), text=None):
    parts = [{"functionCall": {"name": name, "args": args}} for name, args in function_calls]
    if text is not None:
        parts.append({"text": text})
    return 200, {"candidates": [{"content": {"role": "model", "parts": parts}}]}


def test_diff_shows_change_to_existing_file(tmp_path):
    target = tmp_path / "a.txt"
    target.write_text("one\ntwo\n", encoding="utf-8")
    agent = make_agent([ok(function_calls=[("write_file", {"file_path": str(target), "content": "one\nTWO\n"})]),
                        ok(text="done")])

    agent.run_turn("change it")

    diff = agent.edits_diff()
    assert f"--- a/{target}" in diff
    assert f"+++ b/{target}" in diff
    assert "-two\n" in diff
    assert "+TWO\n" in diff


def test_diff_of_new_file_is_against_dev_null(tmp_path):
    target = tmp_path / "new.txt"
    agent = make_agent([ok(function_calls=[("write_file", {"file_path": str(target), "content": "hello\n"})]),
                        ok(text="done")])

    agent.run_turn("create it")

    diff = agent.edits_diff()
    assert "--- /dev/null" in diff
    assert "+hello\n" in diff


def test_diff_is_against_contents_before_the_turn(tmp_path):
    target = tmp_path / "a.txt"
    target.write_text("original\n", encoding="utf-8")
    agent = make_agent([
        ok(function_calls=[("write_file", {"file_path": str(target), "content": "first\n"})]),
        ok(function_calls=[("write_file", {"file_path": str(target), "content": "second\n"})]),
        ok(text="done"),
    ])

    agent.run_turn("edit twice")

    diff = agent.edits_diff()
    assert "-original\n" in diff
    assert "+second\n" in diff
    assert "first" not in diff


def test_reverted_file_has_no_diff(tmp_path):
    target = tmp_path / "a.txt"
    target.write_text("same\n", encoding="utf-8")
    agent = make_agent([
        ok(function_calls=[("write_file", {"file_path": str(target), "content": "other\n"})]),
        ok(function_calls=[("write_file", {"file_path": str(target), "content": "same\n"})]),
        ok(text="done"),
    ])

    agent.run_turn("change and change back")

    assert agent.last_edits  # the file was written, so it is tracked
    assert agent.edits_diff() == ""


def test_failed_write_is_not_tracked(tmp_path, monkeypatch):
    target = tmp_path / "a.txt"
    agent = make_agent([ok(function_calls=[("write_file", {"file_path": str(target), "content": "x"})]),
                        ok(text="done")])
    monkeypatch.setattr(core, "execute_tool", lambda name, args: "Error writing file: disk full")

    agent.run_turn("write it")

    assert agent.last_edits == {}
    assert agent.edits_diff() == ""


def test_edits_reset_each_turn(tmp_path):
    target = tmp_path / "a.txt"
    target.write_text("one\n", encoding="utf-8")
    agent = make_agent([
        ok(function_calls=[("write_file", {"file_path": str(target), "content": "two\n"})]),
        ok(text="done"),
        ok(text="just talking"),
    ])

    agent.run_turn("edit")
    assert agent.last_edits
    agent.run_turn("question only")

    assert agent.last_edits == {}
    assert agent.edits_diff() == ""
