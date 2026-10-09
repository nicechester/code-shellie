import time

import pytest

from code_shellie import cli, sessions
from code_shellie.core import Agent


@pytest.fixture(autouse=True)
def isolated_sessions(monkeypatch, tmp_path):
    monkeypatch.setattr(sessions, "SESSIONS_DIR", tmp_path / "sessions")


def saved(cwd):
    sessions.save({
        "id": "0a1b2c3d", "started": time.time(), "cwd": cwd, "model": "m",
        "description": "remember zebra", "updated": time.time(),
        "history": [
            {"role": "user", "parts": [{"text": "remember zebra"}]},
            {"role": "model", "parts": [{"text": "OK"}]},
        ],
    })


def fresh_agent():
    agent = Agent.__new__(Agent)
    agent.history = []
    agent.session = None
    agent.prompt_token_count = 0
    agent.total_token_count = 0
    return agent


def test_resume_in_same_directory_has_no_warning(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    saved(str(tmp_path))
    agent = fresh_agent()

    cli.resume_session(agent, "0a1b2c3d")

    out = capsys.readouterr().out
    assert "Resumed session 0a1b2c3d" in out
    assert "started in" not in out
    assert agent.session["id"] == "0a1b2c3d"
    assert agent.history[0]["parts"][0]["text"] == "remember zebra"


def test_resume_from_another_directory_warns(tmp_path, monkeypatch, capsys):
    other = tmp_path / "elsewhere"
    other.mkdir()
    monkeypatch.chdir(other)
    saved(str(tmp_path / "original"))

    cli.resume_session(fresh_agent(), "0a1b2c3d")

    assert "this session was started in" in capsys.readouterr().out


def test_resume_unknown_id_exits_with_message(capsys):
    with pytest.raises(SystemExit) as info:
        cli.resume_session(fresh_agent(), "deadbeef")

    assert info.value.code == 1
    assert "No saved session with id deadbeef" in capsys.readouterr().out
