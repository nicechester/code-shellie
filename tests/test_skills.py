import pytest
from prompt_toolkit.document import Document

from code_shellie import skills
from code_shellie.completion import SlashCompleter
from code_shellie.core import Agent

@pytest.fixture
def home(tmp_path, monkeypatch):
    """Point HOME at a temp directory with two skills installed."""
    monkeypatch.setenv("HOME", str(tmp_path))
    for name, desc in (("python-test", "Run and write Python tests"), ("docs", "Write documentation")):
        folder = tmp_path / ".config" / "shellie-code" / "skills" / name
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

def test_enabled_skills_prompt_includes_only_enabled(home):
    skills.enable_skill("python-test")
    prompt = skills.enabled_skills_prompt()
    assert "## Skill: /python-test" in prompt
    assert "Body of python-test." in prompt
    assert "docs" not in prompt

    skills.disable_skill("python-test")
    assert skills.enabled_skills_prompt() == ""

def test_agent_instruction_follows_enabled_skills(home):
    agent = Agent.__new__(Agent)  # skip __init__: it needs an API key and a live client
    agent._base_instruction = "base instruction"
    assert agent._build_instruction() == "base instruction"

    skills.enable_skill("docs")
    assert "Body of docs." in agent._build_instruction()

    skills.disable_skill("docs")
    assert agent._build_instruction() == "base instruction"

def test_skill_names_complete_as_commands(home):
    completions = [c.text for c in SlashCompleter().get_completions(Document("/pyth"), None)]
    assert completions == ["/python-test"]

def test_skill_completion_stops_at_whitespace(home):
    assert list(SlashCompleter().get_completions(Document("/skill enable "), None)) == []
