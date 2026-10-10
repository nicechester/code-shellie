import json

import pytest

from code_shellie import skills
from code_shellie.completion import slash_completions
from code_shellie.core import Agent

@pytest.fixture
def home(tmp_path, monkeypatch):
    """Point HOME at a temp directory with two skills installed."""
    monkeypatch.setenv("HOME", str(tmp_path))
    for name, desc in (("python-test", "Run and write Python tests"), ("docs", "Write documentation")):
        folder = tmp_path / ".config" / "codesh" / "skills" / name
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text(f"description: {desc}\n\nBody of {name}.", encoding="utf-8")
    return tmp_path

def test_list_skills_reads_descriptions(home):
    assert skills.list_skills() == {
        "docs": "Write documentation",
        "python-test": "Run and write Python tests",
    }

def test_no_skills_directory_is_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert skills.list_skills() == {}
    assert skills.enabled_skills_prompt() == ""

def test_enable_and_disable_persist(home):
    assert skills.enable_skill("docs")
    assert skills.enabled_skills() == ["docs"]

    assert skills.disable_skill("docs")
    assert skills.enabled_skills() == []

def test_enable_unknown_skill_fails(home):
    assert not skills.enable_skill("nope")
    assert skills.enabled_skills() == []

def test_disable_not_enabled_fails(home):
    assert not skills.disable_skill("docs")

def test_enabled_skills_prompt_lists_only_enabled_by_description(home):
    skills.enable_skill("python-test")
    prompt = skills.enabled_skills_prompt()
    assert "- /python-test: Run and write Python tests" in prompt
    assert "Body of python-test." not in prompt
    assert "docs" not in prompt

    skills.disable_skill("python-test")
    assert skills.enabled_skills_prompt() == ""

def test_skill_instructions_returns_full_skill_md(home):
    assert skills.skill_instructions("docs") == "description: Write documentation\n\nBody of docs."
    assert skills.skill_instructions("nope") is None

def test_registry_records_description_and_path(home):
    skills.enable_skill("docs")
    registry = json.loads((home / ".config" / "codesh" / "skills.json").read_text(encoding="utf-8"))
    assert registry == {
        "docs": {
            "description": "Write documentation",
            "path": str(home / ".config" / "codesh" / "skills" / "docs" / "SKILL.md"),
        }
    }

def test_legacy_enabled_file_still_works(home):
    config = home / ".config" / "codesh"
    (config / "enabled_skills.json").write_text(json.dumps(["docs"]), encoding="utf-8")
    assert skills.enabled_skills() == ["docs"]
    assert "- /docs: Write documentation" in skills.enabled_skills_prompt()

    skills.disable_skill("docs")
    assert skills.enabled_skills() == []
    assert (config / "skills.json").is_file()

def test_agent_instruction_follows_enabled_skills(home):
    agent = Agent.__new__(Agent)  # skip __init__: it needs an API key and a live client
    agent._base_instruction = "base instruction"
    assert agent._build_instruction() == "base instruction"

    skills.enable_skill("docs")
    assert "- /docs: Write documentation" in agent._build_instruction()
    assert "Body of docs." not in agent._build_instruction()

    skills.disable_skill("docs")
    assert agent._build_instruction() == "base instruction"

def test_skill_names_complete_as_commands(home):
    assert slash_completions("/pyth") == ["/python-test"]

def test_skill_completion_stops_at_whitespace(home):
    assert slash_completions("/skill enable ") == []

def test_skill_request_includes_rules_and_arguments():
    request = skills.skill_request("tackle", "Step 1: find the issue.", " 34 ")
    assert request.startswith("Follow these /tackle skill instructions:\n\nStep 1: find the issue.")
    assert skills.SKILL_RULES in request
    assert request.endswith("Arguments: 34")

def test_skill_request_without_arguments():
    request = skills.skill_request("docs", "Write docs.")
    assert "Arguments:" not in request
    assert "Do not merge or create pull requests" in request
