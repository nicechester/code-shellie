"""The project summary and file index for the current git project: built without the model and cached outside the repo."""
import hashlib
import re
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

def _project_files(root: Path) -> Optional[list]:
    """Existing paths known to git, including untracked files but excluding ignored files."""
    out = _git(root, "ls-files", "-co", "--exclude-standard")
    if out is None:
        return None
    return sorted(
        line for line in out.splitlines()
        if line and ((root / line).exists() or (root / line).is_symlink())
    )


def _file_listing(files: list) -> list:
    """One bounded line per directory in the current working-tree file list."""
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
    return listing


def _refresh_file_list(cached: str, files: list) -> str:
    """Replace the cached file listing with git's current working-tree view."""
    lines = cached.splitlines()
    if not lines or "Files:" not in lines:
        return cached
    lines[0] = re.sub(r", [\d,]+ files,", f", {len(files):,} files,", lines[0], count=1)
    marker = lines.index("Files:")
    return "\n".join(lines[:marker + 1] + _file_listing(files))


def build_index(root: Path, commit: str, today: Optional[str] = None, files: Optional[list] = None) -> str:
    """Project summary, then a bounded per-directory listing of tracked and non-ignored untracked files."""
    files = (_project_files(root) or []) if files is None else files
    today = today or date.today().isoformat()

    lines = [f"Project layout (commit {commit}, generated {today}, {len(files)} files, paths relative to {root.name}/):"]
    lines.extend(build_summary(root, files))
    lines.append("Files:")
    lines.extend(_file_listing(files))
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

    files = _project_files(root)
    path = cache_path(root)
    try:
        if path.exists():
            cached = path.read_text(encoding="utf-8")
            if cached.startswith(f"Project layout (commit {commit},"):
                if files is None:
                    return cached.strip()
                return _refresh_file_list(cached, files).strip()
    except (OSError, UnicodeDecodeError):
        pass

    text = build_index(root, commit, files=files or [])
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    except OSError:
        pass  # the summary still goes into this session's context; it is just not cached
    print(dim(f"Project summary regenerated at commit {commit[:7]}"))
    return text
