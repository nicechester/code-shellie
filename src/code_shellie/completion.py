from pathlib import Path

from prompt_toolkit.completion import Completer, Completion
from .skills import list_skills

MAX_SUGGESTIONS = 200

# Built-in slash commands handled in cli.py, with the description shown beside each suggestion.
BASE_SLASH_COMMANDS = {
    "/help": "Show available commands",
    "/setup": "Reconfigure Gemini API key and model",
    "/model": "Show or change the Gemini model",
    "/mcp": "Show configured MCP servers and their tools",
    "/context": "Show current context usage",
    "/clear": "Clear the terminal screen",
    "/reset": "Reset conversation history / chat session",
    "/copy": "Copy the last answer to the clipboard",
    "/skills": "List skills and whether each is enabled",
    "/skill": "Enable or disable a skill: /skill enable|disable <name>",
    "/exit": "Exit the REPL",
    "/quit": "Exit the REPL",
}

class SlashCompleter(Completer):
    """Suggests slash commands and skill names while the input is a single word starting with "/"."""

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.startswith("/") or any(c.isspace() for c in text):
            return

        # Skills go first: the completion menu shows only a few rows before scrolling
        skill_commands = {f"/{name}": f"skill: {desc}" for name, desc in list_skills().items()}
        slash_commands = {**skill_commands, **BASE_SLASH_COMMANDS}

        for command, description in slash_commands.items():
            if command.startswith(text):
                yield Completion(
                    command,
                    start_position=-len(text),
                    display=command,
                    display_meta=description,
                )

class MentionCompleter(Completer):
    """Suggests file and directory paths after an "@" in the REPL."""

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        at = text.rfind("@")
        if at == -1 or (at > 0 and not text[at - 1].isspace()):
            return
        partial = text[at + 1:]
        if any(c.isspace() for c in partial):
            return

        head, _, tail = partial.rpartition("/")
        if head:
            base = Path(head).expanduser()
        elif partial.startswith("/"):
            base = Path("/")
        else:
            base = Path(".")
        try:
            entries = sorted(base.iterdir(), key=lambda p: (not p.is_dir(), p.name))
        except OSError:
            return

        count = 0
        for entry in entries:
            if not entry.name.startswith(tail):
                continue
            if entry.name.startswith(".") and not tail.startswith("."):
                continue
            suffix = "/" if entry.is_dir() else ""
            yield Completion(
                entry.name + suffix,
                start_position=-len(tail),
                display=entry.name + suffix,
            )
            count += 1
            if count >= MAX_SUGGESTIONS:
                return
