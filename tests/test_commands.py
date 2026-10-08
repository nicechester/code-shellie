from code_shellie.core import Agent
from code_shellie.completion import SlashCompleter
from prompt_toolkit.document import Document

def test_slash_completer():
    completer = SlashCompleter()
    completions = list(completer.get_completions(Document("/cl"), None))
    assert len(completions) == 1
    assert completions[0].text == "/clear"

    completions = list(completer.get_completions(Document("/res"), None))
    assert len(completions) == 1
    assert completions[0].text == "/reset"
