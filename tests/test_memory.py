from code_shellie import memory
from code_shellie.context import load_contexts
from code_shellie.memory import MAX_ENTRIES, MAX_FACT_CHARS, load_lessons, memory_path, remember
from code_shellie.tools import TOOL_DECLARATIONS, TOOL_FUNCTIONS


def test_remember_creates_file_in_cwd_when_no_project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = remember("Run tests with venv/bin/pytest")
    assert result == "Saved to .shellie/MEMORY.md: Run tests with venv/bin/pytest"
    assert (tmp_path / ".shellie" / "MEMORY.md").read_text(encoding="utf-8") == "- Run tests with venv/bin/pytest\n"


def test_remember_appends_to_existing_lessons(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    remember("First lesson")
    remember("Second lesson")
    assert load_lessons() == "- First lesson\n- Second lesson"


def test_duplicate_is_not_saved_twice(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    remember("Use venv/bin/pytest")
    result = remember("  use   VENV/bin/pytest ")
    assert result.startswith("Already saved")
    assert load_lessons() == "- Use venv/bin/pytest"


def test_fact_is_kept_on_one_line(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    remember("line one\nline two")
    assert load_lessons() == "- line one line two"


def test_empty_and_long_facts_are_refused(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert remember("   ").startswith("Error")
    assert remember("x" * (MAX_FACT_CHARS + 1)).startswith("Error")
    assert not (tmp_path / ".shellie" / "MEMORY.md").exists()


def test_full_file_refuses_new_entries(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for i in range(MAX_ENTRIES):
        assert remember(f"lesson {i}").startswith("Saved")
    result = remember("one more")
    assert result.startswith("Error") and "full" in result
    assert len(load_lessons().splitlines()) == MAX_ENTRIES


def test_uses_nearest_project_above_cwd(tmp_path, monkeypatch):
    (tmp_path / ".shellie").mkdir()
    sub = tmp_path / "pkg" / "inner"
    sub.mkdir(parents=True)
    monkeypatch.chdir(sub)
    assert memory_path() == tmp_path / ".shellie" / "MEMORY.md"
    remember("Lesson from a subdirectory")
    assert (tmp_path / ".shellie" / "MEMORY.md").exists()


def test_lessons_are_in_startup_context(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert "Project Lessons" not in load_contexts()
    remember("Venv tools live in ./venv/bin")
    context = load_contexts()
    assert "## Project Lessons" in context
    assert "- Venv tools live in ./venv/bin" in context


def test_remember_is_registered_as_a_tool():
    assert TOOL_FUNCTIONS["remember"] is memory.remember
    declaration = next(d for d in TOOL_DECLARATIONS if d["name"] == "remember")
    assert declaration["parameters"]["required"] == ["fact"]
