import subprocess

from code_shellie import clipboard
from code_shellie.completion import SlashCompleter
from prompt_toolkit.document import Document

def test_copy_returns_none_without_clipboard_tool(monkeypatch):
    monkeypatch.setattr(clipboard.shutil, "which", lambda name: None)
    assert clipboard.copy_to_clipboard("hello") is None

def test_copy_uses_first_available_tool(monkeypatch):
    calls = []
    monkeypatch.setattr(clipboard.shutil, "which", lambda name: "/usr/bin/" + name if name == "xclip" else None)
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: calls.append((cmd, kw["input"])))

    assert clipboard.copy_to_clipboard("hello") == "xclip"
    assert calls == [(["xclip", "-selection", "clipboard"], "hello")]

def test_slash_completer_suggests_copy():
    completions = list(SlashCompleter().get_completions(Document("/cop"), None))
    assert [c.text for c in completions] == ["/copy"]
