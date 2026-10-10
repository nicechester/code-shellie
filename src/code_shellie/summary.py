"""Project summary built from files the project already has (README, pyproject.toml, CLAUDE.md, module docstrings). No model calls."""
import ast
import re
from pathlib import Path
from typing import List

MAX_COMMAND_LINES = 12
MAX_CONVENTIONS = 15
MAX_MODULES = 40

# README sections whose code blocks say how to install, build, test, or run the project
COMMAND_HEADING = re.compile(r"install|test|run|build|usage|develop|quick start|getting started", re.I)
HEADING = re.compile(r"^#{1,6}\s+(.*)")
FENCE = re.compile(r"^\s*```")
SCRIPT_LINE = re.compile(r'^\s*([\w.-]+)\s*=\s*"([^"]+)"')
BULLET = re.compile(r"^\s*[-*]\s+(.*\S)")


def commands_from_readme(text: str) -> List[str]:
    """Shell lines from code blocks under install, build, test, usage, or run headings."""
    commands = []
    heading = ""
    in_fence = False
    for line in text.splitlines():
        if not in_fence:
            match = HEADING.match(line)
            if match:
                heading = match.group(1)
                continue
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        stripped = line.strip()
        if (in_fence and COMMAND_HEADING.search(heading) and stripped
                and not stripped.startswith("#") and not stripped.startswith("codesh>")):
            commands.append(stripped)
    return commands[:MAX_COMMAND_LINES]


def entry_points_from_pyproject(text: str) -> List[str]:
    """Console scripts from the [project.scripts] table, as 'name = module:function'."""
    entries = []
    in_scripts = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            in_scripts = stripped == "[project.scripts]"
            continue
        match = SCRIPT_LINE.match(line) if in_scripts else None
        if match:
            entries.append(f"{match.group(1)} = {match.group(2)}")
    return entries


def conventions_from_claude_md(text: str) -> List[str]:
    """Bullet points from CLAUDE.md, where a project writes down its rules."""
    bullets = []
    for line in text.splitlines():
        match = BULLET.match(line)
        if match:
            bullets.append(match.group(1))
    return bullets[:MAX_CONVENTIONS]


def module_summaries(root: Path, files: List[str]) -> List[str]:
    """'path: first line of its docstring' for each source module that has one (tests are skipped)."""
    lines = []
    for path in files:
        if not path.endswith(".py") or path.startswith("tests/"):
            continue
        try:
            tree = ast.parse((root / path).read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
            continue
        doc = ast.get_docstring(tree)
        if doc:
            lines.append(f"{path}: {doc.splitlines()[0].strip()}")
        if len(lines) >= MAX_MODULES:
            break
    return lines


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def build_summary(root: Path, files: List[str]) -> List[str]:
    """Summary sections as plain lines: entry points and commands, conventions, then modules."""
    readme = _read(root / "README.md")
    pyproject = _read(root / "pyproject.toml")
    claude_md = _read(root / "CLAUDE.md")

    lines = []

    entries = entry_points_from_pyproject(pyproject)
    commands = commands_from_readme(readme)
    lines.append("Commands and entry points:")
    if entries or commands:
        lines.extend(f"- entry point: {entry}" for entry in entries)
        lines.extend(f"- {command}" for command in commands)
    else:
        lines.append("- none found in README.md or pyproject.toml")

    lines.append("Conventions:")
    conventions = conventions_from_claude_md(claude_md) if claude_md else []
    if conventions:
        lines.extend(f"- {rule}" for rule in conventions)
    else:
        lines.append("- none written down (no CLAUDE.md)")

    modules = module_summaries(root, files)
    if modules:
        lines.append("Modules:")
        lines.extend(f"- {module}" for module in modules)
    return lines
