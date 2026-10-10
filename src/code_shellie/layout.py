"""The project summary and file index for the current git project: built without the model and cached outside the repo."""
import hashlib
import subprocess
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Optional

from .summary import build_summary
from .term import dim

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

def build_index(root: Path, commit: str, today: Optional[str] = None) -> str:
    """Project summary, then one line per directory listing its files (git's view: tracked and not ignored)."""
    out = _git(root, "ls-files", "-co", "--exclude-standard") or ""
    files = sorted(line for line in out.splitlines() if line)
    today = today or date.today().isoformat()

    by_dir = defaultdict(list)
    for path in files:
        parent, _, name = path.rpartition("/")
        by_dir[parent or "."].append(name)

    listing = []
    for directory in sorted(by_dir):
        names = by_dir[directory]
        shown = ", ".join(names[:MAX_FILES_PER_DIR])
        extra = len(names) - MAX_FILES_PER_DIR
        if extra > 0:
            shown += f", ... {extra} more"
        listing.append(f"{directory}/: {shown}")

    if len(listing) > MAX_LINES:
        hidden = len(listing) - (MAX_LINES - 1)
        listing = listing[:MAX_LINES - 1] + [f"... {hidden} more directories not listed"]

    lines = [f"Project layout (commit {commit}, generated {today}, {len(files)} files, paths relative to {root.name}/):"]
    lines.extend(build_summary(root, files))
    lines.append("Files:")
    lines.extend(listing)
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
        pass  # the summary still goes into this session's context; it is just not cached
    print(dim(f"Project summary regenerated at commit {commit[:7]}"))
    return text
