from pathlib import Path
from typing import List, Tuple

from .skills import list_skills

MAX_SUGGESTIONS = 200

# Built-in slash commands handled in cli.py.
BASE_SLASH_COMMANDS = (
    "/help",
    "/setup",
    "/model",
    "/mcp",
    "/context",
    "/clear",
    "/reset",
    "/copy",
    "/sources",
    "/skills",
    "/skill",
    "/exit",
    "/quit",
)


def slash_completions(text: str) -> List[str]:
    """Slash commands and skill names that start with text, while text is a single word starting with "/"."""
    if not text.startswith("/") or any(c.isspace() for c in text):
        return []
    # Skills go first: the completion list shows only a few rows before scrolling
    names = [f"/{name}" for name in list_skills()] + list(BASE_SLASH_COMMANDS)
    return [c for c in dict.fromkeys(names) if c.startswith(text)]


def mention_completions(text: str) -> Tuple[int, List[str]]:
    """File and directory names after an "@" mention. Returns (characters to replace, candidates)."""
    at = text.rfind("@")
    if at == -1 or (at > 0 and not text[at - 1].isspace()):
        return 0, []
    partial = text[at + 1:]
    if any(c.isspace() for c in partial):
        return 0, []

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
        return 0, []

    candidates = []
    for entry in entries:
        if not entry.name.startswith(tail):
            continue
        if entry.name.startswith(".") and not tail.startswith("."):
            continue
        candidates.append(entry.name + ("/" if entry.is_dir() else ""))
        if len(candidates) >= MAX_SUGGESTIONS:
            break
    return len(tail), candidates


def complete(text: str) -> Tuple[int, List[str]]:
    """Completions for the end of the input: (characters to replace at the end, candidates)."""
    commands = slash_completions(text)
    if commands:
        return len(text), commands
    return mention_completions(text)
