import os
from pathlib import Path

def load_contexts() -> str:
    """Load system, project, and session contexts."""
    context_parts = []

    # 1. System-wide context (~/.config/shellie-code/SYSTEM.md)
    sys_path = Path.home() / ".config" / "shellie-code" / "SYSTEM.md"
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

    return "\n\n".join(context_parts)
