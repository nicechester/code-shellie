import json
from pathlib import Path

def _config_dir() -> Path:
    return Path.home() / ".config" / "codesh"

def _skill_file(name: str) -> Path:
    return _config_dir() / "skills" / name / "SKILL.md"

def _registry_file() -> Path:
    """JSON registry of enabled skills: name -> {"description", "path"}."""
    return _config_dir() / "skills.json"

def _legacy_enabled_file() -> Path:
    """Older list of enabled skill names, read only until skills.json exists."""
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
    """Map each installed skill name to its description. Skills live in ~/.config/codesh/skills/<name>/SKILL.md."""
    root = _config_dir() / "skills"
    skills = {}
    if not root.is_dir():
        return skills
    for folder in sorted(root.iterdir()):
        skill_md = folder / "SKILL.md"
        if folder.is_dir() and skill_md.is_file():
            skills[folder.name] = _description(folder.name, skill_md)
    return skills

def _load_registry() -> dict:
    """Enabled skills in the order they were enabled. Falls back to the legacy name list if skills.json is missing."""
    try:
        data = json.loads(_registry_file().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _legacy_registry()
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {name: entry for name, entry in data.items() if isinstance(entry, dict)}

def _legacy_registry() -> dict:
    try:
        names = json.loads(_legacy_enabled_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(names, list):
        return {}
    installed = list_skills()
    return {
        name: {"description": installed[name], "path": str(_skill_file(name))}
        for name in names
        if isinstance(name, str) and name in installed
    }

def _save_registry(registry: dict) -> None:
    path = _registry_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(registry, indent=2), encoding="utf-8")

def enabled_skills() -> list:
    """Names of enabled skills, in the order they were enabled."""
    return list(_load_registry())

def skill_instructions(name: str):
    """Full SKILL.md text of an installed skill, or None if it cannot be read."""
    try:
        return _skill_file(name).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

def enable_skill(name: str) -> bool:
    """Enable an installed skill. Returns False if no skill with that name is installed."""
    installed = list_skills()
    if name not in installed:
        return False
    registry = _load_registry()
    registry[name] = {"description": installed[name], "path": str(_skill_file(name))}
    _save_registry(registry)
    return True

def disable_skill(name: str) -> bool:
    """Disable a skill. Returns False if it was not enabled."""
    registry = _load_registry()
    if name not in registry:
        return False
    del registry[name]
    _save_registry(registry)
    return True

def enabled_skills_prompt() -> str:
    """System prompt section listing each enabled skill by name and description. Full instructions are sent with the turn that invokes the skill."""
    lines = []
    for name, entry in _load_registry().items():
        if not Path(entry.get("path", "")).is_file():
            continue
        lines.append(f"- /{name}: {entry.get('description', '')}")
    if not lines:
        return ""
    return (
        "## Enabled Skills\n"
        "When the user sends /<name>, the full instructions of that skill are included in the message.\n"
        + "\n".join(lines)
    )


# Added to every skill request. The skill's steps are the only work to do, and it stops where the skill says to.
SKILL_RULES = (
    "Rules for running a skill:\n"
    "- Follow the steps in order, and stop after the last one.\n"
    "- If a step asks for confirmation, show what you found, end your reply with the question, and make no more tool calls until the user answers.\n"
    "- Do not merge or create pull requests, push, or commit unless the user asks for that in this message.\n"
    "- Do not start other skills on your own.\n"
    "- If a step names an agent or tool that is not available, do that work yourself."
)


def skill_request(name: str, instructions: str, args: str = "") -> str:
    """The message sent to the model when a skill is run: its instructions, the rules, then any arguments."""
    request = f"Follow these /{name} skill instructions:\n\n{instructions}\n\n{SKILL_RULES}"
    if args.strip():
        request += f"\n\nArguments: {args.strip()}"
    return request
