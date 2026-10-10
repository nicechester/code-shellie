"""A file index of the current git project, built without the model and cached outside the repo."""
import hashlib
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Optional

MAX_LINES = 200
MAX_FILES_PER_DIR = 20
GIT_TIMEOUT_SEC = 5

def _git(cwd: Path, *args: str) -> Optional[str]:
    """Output of a git command run in cwd, or None if it fails or git is missing."""
    try:
        result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=GIT_TIMEOUT_SEC)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 else None

def project_root(cwd: Path) -> Optional[Path]:
    """Top of the git repository containing cwd, or None outside a repository."""
    out = _git(cwd, "rev-parse", "--show-toplevel")
    return Path(out.strip()) if out else None

def cache_path(root: Path) -> Path:
    """Where the index for this project lives: under ~/.config/codesh, keyed by the full path so clones with the same name do not collide."""
    digest = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:12]
    return Path.home() / ".config" / "codesh" / "code" / f"{root.name}-{digest}" / "index.txt"

def build_index(root: Path, commit: str) -> str:
    """One line per directory listing its files, from git's view of the project (tracked and not ignored)."""
    out = _git(root, "ls-files", "-co", "--exclude-standard") or ""
    files = sorted(line for line in out.splitlines() if line)

    by_dir = defaultdict(list)
    for path in files:
        parent, _, name = path.rpartition("/")
        by_dir[parent or "."].append(name)

    lines = [f"Project layout (commit {commit}, {len(files)} files, paths relative to {root.name}/):"]
    for directory in sorted(by_dir):
        names = by_dir[directory]
        shown = ", ".join(names[:MAX_FILES_PER_DIR])
        extra = len(names) - MAX_FILES_PER_DIR
        if extra > 0:
            shown += f", ... {extra} more"
        lines.append(f"{directory}/: {shown}")

    if len(lines) > MAX_LINES:
        hidden = len(lines) - (MAX_LINES - 1)
        lines = lines[:MAX_LINES - 1] + [f"... {hidden} more directories not listed"]
    return "\n".join(lines)

def load_layout(cwd: Optional[Path] = None) -> str:
    """The project's file index, rebuilt when HEAD has moved since it was made. '' outside git or with no commits."""
    cwd = cwd or Path.cwd()
    root = project_root(cwd)
    if root is None:
        return ""
    commit = (_git(root, "rev-parse", "HEAD") or "").strip()
    if not commit:
        return ""

    path = cache_path(root)
    try:
        if path.exists():
            cached = path.read_text(encoding="utf-8")
            if cached.startswith(f"Project layout (commit {commit},"):
                return cached.strip()
    except (OSError, UnicodeDecodeError):
        pass

    text = build_index(root, commit)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    except OSError:
        pass  # the index still goes into this session's context; it is just not cached
    return text
