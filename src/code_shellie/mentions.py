import re
from pathlib import Path

from .term import dim

# "@" must start the input or follow whitespace, so emails like user@host are not mentions.
MENTION_RE = re.compile(r"(?<!\S)@(\S+)")
TRAILING_PUNCT = ".,;:!?)\"'"
MAX_CHARS = 100_000

def _resolve(raw: str) -> tuple:
    for candidate in (raw, raw.rstrip(TRAILING_PUNCT)):
        if candidate and Path(candidate).expanduser().exists():
            return candidate, Path(candidate).expanduser()
    return None

def _render(raw: str, path: Path) -> str:
    if path.is_dir():
        body = "\n".join(
            sorted(p.name + ("/" if p.is_dir() else "") for p in path.iterdir() if not p.name.startswith("."))
        )
    else:
        try:
            body = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as e:
            return f'<file path="{raw}">\n[not readable as text: {e}]\n</file>'
    if len(body) > MAX_CHARS:
        body = body[:MAX_CHARS] + "\n[truncated]"
    return f'<file path="{raw}">\n{body}\n</file>'

def expand_mentions(text: str) -> str:
    """Append the contents of each existing @path mentioned in text."""
    attachments = []
    seen = set()
    for match in MENTION_RE.finditer(text):
        resolved = _resolve(match.group(1))
        if resolved is None:
            continue
        raw, path = resolved
        if raw in seen:
            continue
        seen.add(raw)
        print(dim(f"Attached {raw}"))
        attachments.append(_render(raw, path))
    if not attachments:
        return text
    return text + "\n\n" + "\n\n".join(attachments)
