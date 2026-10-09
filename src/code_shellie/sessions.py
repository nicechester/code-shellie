"""Saved conversations: one JSON file per session under ~/.config/shellie-code/sessions/.

A session file holds the chat history plus what is needed to list and resume it. Files are
written with mode 0600, since they can contain file contents and command output.
"""
import json
import os
import re
import time
import uuid
from pathlib import Path

from .config import CONFIG_DIR, load_environment

SESSIONS_DIR = CONFIG_DIR / "sessions"
DESCRIPTION_CHARS = 60
DEFAULT_TTL_HOURS = 24
_ID_RE = re.compile(r"^[0-9a-f]{8}$")


class SessionError(Exception):
    pass


def new_session_id() -> str:
    return uuid.uuid4().hex[:8]


def describe(prompt: str) -> str:
    """One-line description of a session: its first prompt, with whitespace collapsed and cut short."""
    line = " ".join(prompt.split())
    if len(line) > DESCRIPTION_CHARS:
        line = line[:DESCRIPTION_CHARS - 3] + "..."
    return line


def _path(session_id: str) -> Path:
    if not _ID_RE.match(session_id):
        raise SessionError(f"Invalid session id '{session_id}'.")
    return SESSIONS_DIR / f"{session_id}.json"


def save(data: dict) -> None:
    """Write a session file atomically, with mode 0600."""
    path = _path(data["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def ttl_seconds() -> float:
    """How long a session may go without a turn before it expires. SESSION_TTL_HOURS, default 24.
    A value of 0 or less turns expiry off."""
    load_environment()
    raw = os.getenv("SESSION_TTL_HOURS", "")
    try:
        hours = float(raw) if raw else DEFAULT_TTL_HOURS
    except ValueError:
        hours = DEFAULT_TTL_HOURS
    return hours * 3600 if hours > 0 else 0


def is_expired(data: dict, now: float = None) -> bool:
    ttl = ttl_seconds()
    if ttl == 0:
        return False
    now = time.time() if now is None else now
    return now - data.get("updated", 0) > ttl


def _read(session_id: str) -> dict:
    """Read and validate a session file, whether or not it has expired."""
    path = _path(session_id)
    if not path.exists():
        raise SessionError(f"No saved session with id {session_id}. See codesh --sessions.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise SessionError(f"Session {session_id} cannot be read: {e}")
    if not isinstance(data, dict) or not isinstance(data.get("history"), list) or data.get("id") != session_id:
        raise SessionError(f"Session {session_id} is not a valid session file.")
    return data


def load(session_id: str) -> dict:
    """Read a session file for resuming. Raises SessionError with a message the user can act on."""
    data = _read(session_id)
    if is_expired(data):
        raise SessionError(f"Session {session_id} expired after {ttl_seconds() / 3600:g} hours without a turn.")
    return data


def purge_expired() -> int:
    """Delete expired session files. Unreadable files are left alone so the user can see them. Returns the count removed."""
    if not SESSIONS_DIR.is_dir():
        return 0
    removed = 0
    for path in SESSIONS_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and is_expired(data):
            path.unlink(missing_ok=True)
            removed += 1
    return removed


def delete(session_id: str) -> None:
    try:
        _path(session_id).unlink()
    except (FileNotFoundError, SessionError):
        pass


def list_sessions() -> list:
    """Saved sessions, most recently updated first. Unreadable files are listed with a note."""
    if not SESSIONS_DIR.is_dir():
        return []
    rows = []
    for path in SESSIONS_DIR.glob("*.json"):
        session_id = path.stem
        try:
            data = _read(session_id)
        except SessionError as e:
            rows.append({"id": session_id, "updated": 0, "cwd": "", "description": f"unreadable: {e}"})
            continue
        if not is_expired(data):
            rows.append(data)
    return sorted(rows, key=lambda d: d.get("updated", 0), reverse=True)


def latest_for_directory(cwd: str):
    """The most recently updated session that was started in cwd, or None."""
    for data in list_sessions():
        if data.get("cwd") == cwd and "history" in data:
            return data
    return None


def format_time(timestamp: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(timestamp)) if timestamp else "-"


def recent_turns(history: list, count: int = 3) -> list:
    """The last few (prompt, answer) pairs in a history, for showing what a resumed session was about."""
    pairs = []
    pending = None
    for message in history:
        if not isinstance(message, dict):
            continue
        texts = [p["text"] for p in message.get("parts", []) if isinstance(p, dict) and "text" in p]
        if message.get("role") == "user" and texts:
            pending = " ".join(texts)
        elif message.get("role") == "model" and texts and pending is not None:
            pairs.append((pending, " ".join(texts)))
            pending = None
    return pairs[-count:]
