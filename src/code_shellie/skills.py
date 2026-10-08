import json
from pathlib import Path

def _config_dir() -> Path:
    return Path.home() / ".config" / "shellie-code"

def _skill_file(name: str) -> Path:
    return _config_dir() / "skills" / name / "SKILL.md"

def _enabled_file() -> Path:
    return _config_dir() / "enabled_skills.json"

def _description(name: str, skill_md: Path) -> str:
    """Use the `description:` line from SKILL.md if there is one."""
    try:
        for line in skill_md.read_text(encoding="utf-8").splitlines():
            if line.startswith("description:"):
                return line.split(":", 1)[1].strip()
    except (OSError, UnicodeDecodeError):
        pass
    return f"Run /{name} workflow"

def list_skills() -> dict:
    """Map each installed skill name to its description. Skills live in ~/.config/shellie-code/skills/<name>/SKILL.md."""
    root = _config_dir() / "skills"
    skills = {}
    if not root.is_dir():
        return skills
    for folder in sorted(root.iterdir()):
        skill_md = folder / "SKILL.md"
        if folder.is_dir() and skill_md.is_file():
            skills[folder.name] = _description(folder.name, skill_md)
    return skills

def enabled_skills() -> list:
    """Names of enabled skills, in the order they were enabled."""
    try:
        names = json.loads(_enabled_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(names, list):
        return []
    return [name for name in names if isinstance(name, str)]

def _save_enabled(names: list) -> None:
    path = _enabled_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    unique = list(dict.fromkeys(names))
    path.write_text(json.dumps(unique, indent=2), encoding="utf-8")

def enable_skill(name: str) -> bool:
    """Enable an installed skill. Returns False if no skill with that name is installed."""
    if name not in list_skills():
        return False
    _save_enabled(enabled_skills() + [name])
    return True

def disable_skill(name: str) -> bool:
    """Disable a skill. Returns False if it was not enabled."""
    current = enabled_skills()
    if name not in current:
        return False
    _save_enabled([n for n in current if n != name])
    return True

def enabled_skills_prompt() -> str:
    """System prompt section with the instructions of each enabled skill that is still installed."""
    installed = list_skills()
    parts = []
    for name in enabled_skills():
        if name not in installed:
            continue
        try:
            content = _skill_file(name).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        parts.append(f"## Skill: /{name}\n{content}")
    if not parts:
        return ""
    return "## Enabled Skills\n" + "\n\n".join(parts)
