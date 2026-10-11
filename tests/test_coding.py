from code_shellie import core
from code_shellie.coding import CODING_GUIDANCE
from code_shellie.core import Agent


def test_system_instruction_includes_coding_guidance(monkeypatch):
    monkeypatch.setattr(core, "get_api_key", lambda: "test-key")
    monkeypatch.setattr(core, "get_model_name", lambda: "test-model")
    monkeypatch.setattr(core, "get_manager", lambda: None)
    monkeypatch.setattr(core, "load_contexts", lambda: "")
    monkeypatch.setattr(core, "enabled_skills_prompt", lambda: "")
    monkeypatch.setattr(core.gemini, "get_input_limit", lambda model, key: None)

    agent = Agent()

    assert CODING_GUIDANCE in agent.system_instruction


def test_coding_guidance_asks_for_single_responsibility_and_tests():
    assert "one responsibility" in CODING_GUIDANCE
    assert "tests" in CODING_GUIDANCE
