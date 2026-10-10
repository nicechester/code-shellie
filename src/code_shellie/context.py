import os
from pathlib import Path

from .layout import load_layout
from .memory import load_lessons, memory_path

def load_contexts() -> str:
    """Load system and project contexts. Enabled skills are added by the agent."""
    context_parts = []

    # 1. System-wide context (~/.config/codesh/SYSTEM.md)
    sys_path = Path.home() / ".config" / "codesh" / "SYSTEM.md"
    if sys_path.exists():
        context_parts.append(f"## System Context\n{sys_path.read_text(encoding='utf-8')}")

    # 2. Project-wide context (.shellie/PROJECT.md or similar in cwd or parents)
    curr = Path.cwd()
    proj_path = None
    while curr != curr.parent:
        candidate = curr / ".shellie" / "PROJECT.md"
        if candidate.exists():
            proj_path = candidate
            break
        curr = curr.parent
    
    if proj_path and proj_path.exists():
        context_parts.append(f"## Project Context ({proj_path})\n{proj_path.read_text(encoding='utf-8')}")

    # 3. Lessons the agent saved in earlier sessions (.shellie/MEMORY.md)
    lessons = load_lessons()
    if lessons:
        context_parts.append(f"## Project Lessons ({memory_path()})\n{lessons}")

    # 4. File index of the git project, so the agent does not need list_directory calls to find its way around
    layout = load_layout()
    if layout:
        context_parts.append(f"## Project Layout\n{layout}")

    return "\n\n".join(context_parts)
