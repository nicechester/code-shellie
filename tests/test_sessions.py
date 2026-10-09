import json
import os
import stat
import time

import pytest

from code_shellie import core, sessions
from code_shellie.core import Agent


@pytest.fixture(autouse=True)
def isolated_sessions(monkeypatch, tmp_path):
    # Session files go to a temp dir, and no MCP servers are contacted
    monkeypatch.setattr(sessions, "SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr(core, "all_declarations", lambda: [])
    return tmp_path / "sessions"


def meta(session_id, cwd="/work/a", updated=None, prompt="first prompt"):
    updated = time.time() if updated is None else updated
    return {"id": session_id, "started": 0.0, "cwd": cwd, "model": "m",
            "description": sessions.describe(prompt), "updated": updated,
            "history": [{"role": "user", "parts": [{"text": prompt}]}]}


def test_save_and_load_round_trip():
    sessions.save(meta("0a1b2c3d"))

    assert sessions.load("0a1b2c3d")["description"] == "first prompt"


def test_saved_file_is_private(isolated_sessions):
    sessions.save(meta("0a1b2c3d"))

    mode = stat.S_IMODE(os.stat(isolated_sessions / "0a1b2c3d.json").st_mode)
    assert mode == 0o600


def test_description_is_one_line_and_short():
    assert sessions.describe("fix\n  the   bug") == "fix the bug"
    assert len(sessions.describe("x" * 200)) == sessions.DESCRIPTION_CHARS


def test_invalid_ids_are_rejected(isolated_sessions):
    with pytest.raises(sessions.SessionError, match="Invalid session id"):
        sessions.load("../secrets")
    with pytest.raises(sessions.SessionError, match="Invalid session id"):
        sessions.save({**meta("0a1b2c3d"), "id": "../../x"})


def test_unknown_session_has_a_clear_message():
    with pytest.raises(sessions.SessionError, match="No saved session with id deadbeef"):
        sessions.load("deadbeef")


def test_unreadable_session_is_reported_not_raised(isolated_sessions):
    isolated_sessions.mkdir(parents=True)
    (isolated_sessions / "0a1b2c3d.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(sessions.SessionError, match="cannot be read"):
        sessions.load("0a1b2c3d")
    rows = sessions.list_sessions()
    assert rows[0]["id"] == "0a1b2c3d" and "unreadable" in rows[0]["description"]


def test_latest_for_directory_picks_newest_in_that_directory():
    now = time.time()
    sessions.save(meta("aaaaaaaa", cwd="/work/a", updated=now - 300))
    sessions.save(meta("bbbbbbbb", cwd="/work/a", updated=now - 100))
    sessions.save(meta("cccccccc", cwd="/work/b", updated=now - 10))

    assert sessions.latest_for_directory("/work/a")["id"] == "bbbbbbbb"
    assert sessions.latest_for_directory("/nowhere") is None


def test_delete_removes_the_file():
    sessions.save(meta("0a1b2c3d"))
    sessions.delete("0a1b2c3d")

    with pytest.raises(sessions.SessionError):
        sessions.load("0a1b2c3d")


def test_recent_turns_pairs_prompts_with_answers():
    history = [
        {"role": "user", "parts": [{"text": "one"}]},
        {"role": "model", "parts": [{"functionCall": {"name": "x", "args": {}}}]},
        {"role": "user", "parts": [{"functionResponse": {"name": "x", "response": {}}}]},
        {"role": "model", "parts": [{"text": "answer one"}]},
        {"role": "user", "parts": [{"text": "two"}]},
        {"role": "model", "parts": [{"text": "answer two"}]},
    ]
    assert sessions.recent_turns(history, count=2) == [("one", "answer one"), ("two", "answer two")]


# Agent behavior, using a fake model

def make_agent():
    agent = Agent.__new__(Agent)
    agent.model = "test-model"
    agent.api_key = "k"
    agent.system_instruction = "system"
    agent.history = []
    agent.session = None
    agent.prompt_token_count = 0
    agent.total_token_count = 0
    agent.model_limit = None
    agent.last_answer = ""
    agent._generate = lambda payload: (200, {"candidates": [{"content": {"role": "model", "parts": [{"text": "ok"}]}}]})
    return agent


def test_completed_turn_creates_and_updates_the_session_file(monkeypatch):
    monkeypatch.setattr(sessions, "new_session_id", lambda: "0a1b2c3d")
    agent = make_agent()

    agent.run_turn("explain the parser")
    agent.run_turn("and the lexer")

    data = sessions.load("0a1b2c3d")
    assert data["description"] == "explain the parser"
    assert len(data["history"]) == 4
    assert agent.session["id"] == "0a1b2c3d"


def test_failed_turn_is_not_saved(monkeypatch):
    agent = make_agent()

    def fail(payload):
        return 400, {"error": {"message": "bad"}}
    agent._generate = fail

    with pytest.raises(Exception):
        agent.run_turn("broken")
    assert agent.session is None
    assert sessions.list_sessions() == []


def test_restore_continues_the_same_file(monkeypatch):
    monkeypatch.setattr(sessions, "new_session_id", lambda: "0a1b2c3d")
    first = make_agent()
    first.run_turn("first")

    second = make_agent()
    second.restore(sessions.load("0a1b2c3d"))
    second.run_turn("second")

    data = sessions.load("0a1b2c3d")
    assert len(data["history"]) == 4
    assert data["description"] == "first"


def test_reset_keeps_the_file_but_discard_deletes_it(monkeypatch):
    monkeypatch.setattr(sessions, "new_session_id", lambda: "0a1b2c3d")
    agent = make_agent()
    agent.run_turn("keep me")

    agent.reset_chat()
    assert sessions.load("0a1b2c3d")  # still resumable

    agent.restore(sessions.load("0a1b2c3d"))
    agent.discard_session()
    with pytest.raises(sessions.SessionError):
        sessions.load("0a1b2c3d")
    assert agent.history == [] and agent.session is None


# Expiry

HOUR = 3600


def test_default_ttl_is_24_hours(monkeypatch):
    monkeypatch.delenv("SESSION_TTL_HOURS", raising=False)
    monkeypatch.setattr(sessions, "load_environment", lambda: None)
    assert sessions.ttl_seconds() == 24 * HOUR


def test_ttl_can_be_set_and_zero_turns_expiry_off(monkeypatch):
    monkeypatch.setattr(sessions, "load_environment", lambda: None)
    monkeypatch.setenv("SESSION_TTL_HOURS", "2")
    assert sessions.ttl_seconds() == 2 * HOUR
    monkeypatch.setenv("SESSION_TTL_HOURS", "0")
    assert sessions.ttl_seconds() == 0
    assert not sessions.is_expired({"updated": 0})


def test_invalid_ttl_falls_back_to_default(monkeypatch):
    monkeypatch.setattr(sessions, "load_environment", lambda: None)
    monkeypatch.setenv("SESSION_TTL_HOURS", "soon")
    assert sessions.ttl_seconds() == 24 * HOUR


def test_purge_deletes_only_expired_sessions(isolated_sessions):
    sessions.save(meta("aaaaaaaa", updated=time.time() - 25 * HOUR))
    sessions.save(meta("bbbbbbbb", updated=time.time() - HOUR))

    assert sessions.purge_expired() == 1
    assert not (isolated_sessions / "aaaaaaaa.json").exists()
    assert sessions.load("bbbbbbbb")["id"] == "bbbbbbbb"


def test_purge_leaves_unreadable_files_for_the_user(isolated_sessions):
    isolated_sessions.mkdir(parents=True)
    (isolated_sessions / "0a1b2c3d.json").write_text("{not json", encoding="utf-8")

    assert sessions.purge_expired() == 0
    assert (isolated_sessions / "0a1b2c3d.json").exists()


def test_expired_session_cannot_be_resumed_or_listed(isolated_sessions):
    sessions.save(meta("aaaaaaaa", cwd="/work/a", updated=time.time() - 25 * HOUR))

    with pytest.raises(sessions.SessionError, match="expired"):
        sessions.load("aaaaaaaa")
    assert sessions.list_sessions() == []
    assert sessions.latest_for_directory("/work/a") is None
