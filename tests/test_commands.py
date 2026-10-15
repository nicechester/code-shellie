from code_shellie.completion import complete, slash_completions


def test_slash_completer():
    assert slash_completions("/cl") == ["/clear"]
    assert slash_completions("/res") == ["/reset"]
    assert slash_completions("/up") == ["/update"]


def test_mention_completer_lists_paths(tmp_path, monkeypatch):
    (tmp_path / "notes.md").write_text("x")
    (tmp_path / "docs").mkdir()
    monkeypatch.chdir(tmp_path)

    assert complete("look at @no") == (2, ["notes.md"])
    assert complete("look at @doc") == (3, ["docs/"])


def test_mention_needs_whitespace_before_at(tmp_path, monkeypatch):
    (tmp_path / "notes.md").write_text("x")
    monkeypatch.chdir(tmp_path)

    assert complete("user@no") == (0, [])
