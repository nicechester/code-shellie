"""Project lessons the agent saves to .shellie/MEMORY.md and reads back in later sessions."""
from pathlib import Path

MEMORY_NAME = "MEMORY.md"
MAX_ENTRIES = 100
MAX_FACT_CHARS = 300

MEMORY_GUIDANCE = (
    "Use the remember tool to save a project lesson that you have confirmed and that a later session would "
    "otherwise have to rediscover, such as where a tool lives or a command that only works after a fix. "
    "Do not save guesses, temporary state, or anything already written in the code or docs. "
    "If remember reports that the file is full, merge or remove old entries first."
)

def memory_path() -> Path:
    """The MEMORY.md of the nearest directory at or above cwd that has a .shellie folder, else one in cwd."""
    curr = Path.cwd()
    for candidate in [curr, *curr.parents]:
        if (candidate / ".shellie").is_dir():
            return candidate / ".shellie" / MEMORY_NAME
    return curr / ".shellie" / MEMORY_NAME

def _shown(path: Path) -> str:
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        return str(path)

def load_lessons() -> str:
    """Saved lessons as text for the system prompt, or '' if there are none."""
    path = memory_path()
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()

def remember(fact: str) -> str:
    """Save one confirmed project lesson to .shellie/MEMORY.md. Duplicates and a full file are refused."""
    fact = " ".join(str(fact).split())  # one line per entry
    if not fact:
        return "Error: the fact is empty."
    if len(fact) > MAX_FACT_CHARS:
        return f"Error: the fact is longer than {MAX_FACT_CHARS} characters. Shorten it and try again."

    path = memory_path()
    lines = []
    if path.exists():
        lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    known = {line[2:].casefold() if line.startswith("- ") else line.casefold() for line in lines}
    if fact.casefold() in known:
        return f"Already saved in {_shown(path)}: {fact}"
    if len(lines) >= MAX_ENTRIES:
        return (
            f"Error: {_shown(path)} is full ({MAX_ENTRIES} entries). Rewrite it with write_file, "
            "merging or removing old entries, then try again."
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join([*lines, f"- {fact}"]) + "\n", encoding="utf-8")
    return f"Saved to {_shown(path)}: {fact}"
