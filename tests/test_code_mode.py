import pytest

from code_shellie import code_mode, config, tools


@pytest.fixture(autouse=True)
def isolated_workdir(monkeypatch, tmp_path):
    # Scripts run in the working directory, so each test gets its own, with no user .env file read
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "ENV_PATH", tmp_path / "no-such.env")
    monkeypatch.delenv("CODE_MODE", raising=False)


def test_script_output_is_returned(tmp_path):
    (tmp_path / "a.txt").write_text("alpha\nneedle here\n", encoding="utf-8")
    output = tools.run_script("for f, n, line in grep('needle'):\n    print(f, n, line)")
    assert output == "a.txt 2 needle here"


def test_grep_returns_file_line_and_text(tmp_path):
    (tmp_path / "a.txt").write_text("alpha\nneedle here\n", encoding="utf-8")
    output = tools.run_script("print(grep('needle'))")
    assert "('a.txt', 2, 'needle here')" in output


def test_script_without_output_says_so():
    assert tools.run_script("x = 1") == "[Script ran with no output]"


def test_edit_replaces_text(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\ny = 1\n", encoding="utf-8")
    output = tools.run_script("print(edit('a.py', 'x = 1', 'x = 2'))")
    assert output == "1"
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "x = 2\ny = 1\n"


def test_edit_with_missing_text_fails_and_leaves_file_unchanged(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    output = tools.run_script("edit('a.py', 'nothing here', 'y')")
    assert output.startswith("Error: script failed:")
    assert "not found" in output
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "x = 1\n"


def test_edit_with_ambiguous_text_fails_and_leaves_file_unchanged(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\nx = 1\n", encoding="utf-8")
    output = tools.run_script("edit('a.py', 'x = 1', 'x = 2')")
    assert output.startswith("Error: script failed:")
    assert "expected 1" in output
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "x = 1\nx = 1\n"


def test_edit_with_count_none_replaces_all(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\nx = 1\n", encoding="utf-8")
    output = tools.run_script("print(edit('a.py', 'x = 1', 'x = 2', count=None))")
    assert output == "2"
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "x = 2\nx = 2\n"


def test_failure_shows_script_line_and_keeps_output_before_it():
    output = tools.run_script("print('step one')\nraise ValueError('boom')")
    assert output.startswith("Error: script failed:")
    assert 'File "<script>", line 2' in output
    assert "ValueError: boom" in output
    assert "Output before the failure:\nstep one" in output


def test_write_records_contents_before_the_first_write(tmp_path):
    (tmp_path / "old.txt").write_text("before", encoding="utf-8")
    output, edits = code_mode.run(
        "write('old.txt', 'after')\nwrite('old.txt', 'again')\nwrite('new/new.txt', 'hi')"
    )
    assert output == "[Script ran with no output]"
    assert edits == {
        str(tmp_path / "old.txt"): "before",
        str(tmp_path / "new" / "new.txt"): None,
    }
    assert (tmp_path / "old.txt").read_text(encoding="utf-8") == "again"


def test_edit_records_contents_before_the_write(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    _, edits = code_mode.run("edit('a.py', 'x = 1', 'x = 2')")
    assert edits == {str(tmp_path / "a.py"): "x = 1\n"}


def test_edits_are_kept_when_the_script_fails_later(tmp_path):
    output, edits = code_mode.run("write('a.txt', 'hi')\nraise RuntimeError('late')")
    assert output.startswith("Error: script failed:")
    assert edits == {str(tmp_path / "a.txt"): None}
    assert (tmp_path / "a.txt").exists()


def test_output_over_the_cap_is_truncated(monkeypatch):
    monkeypatch.setattr(code_mode, "SCRIPT_OUTPUT_LIMIT", 50)
    output = tools.run_script("print('x' * 200)")
    assert output.startswith("x" * 50)
    assert output.endswith("... (output truncated; print less, e.g. counts or only matching lines)")
    assert len(output) < 200


def test_infinite_loop_times_out(monkeypatch):
    monkeypatch.setattr(code_mode, "TIMEOUT_SEC", 1)
    assert tools.run_script("while True:\n    pass") == "Error: script timed out after 1 seconds."


def test_api_key_is_not_visible_to_script(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "secret")
    assert tools.run_script("import os\nprint(os.environ.get('GEMINI_API_KEY', 'none'))") == "none"


def test_hidden_and_skipped_dirs_are_excluded(tmp_path):
    (tmp_path / "keep").mkdir()
    (tmp_path / "keep" / "a.txt").write_text("needle", encoding="utf-8")
    for folder in (".hidden", "venv", "node_modules", "__pycache__"):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / "b.txt").write_text("needle", encoding="utf-8")

    found = tools.run_script("print(find())")
    assert "keep/a.txt" in found
    assert "venv" not in found and "node_modules" not in found
    assert ".hidden" not in found and "__pycache__" not in found

    hits = tools.run_script("print(grep('needle'))")
    assert "keep/a.txt" in hits
    assert "venv" not in hits and "node_modules" not in hits
    assert ".hidden" not in hits and "__pycache__" not in hits


def test_ls_marks_directories_and_skips_hidden_entries(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "README.md").write_text("", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    assert tools.run_script("print(ls())") == "['src/', 'README.md']"


def _manager_without_tools():
    class Manager:
        def declarations(self):
            return []

        def has_tool(self, name):
            return False

    return Manager()


def test_run_script_is_declared_by_default(monkeypatch):
    monkeypatch.setattr(tools, "get_manager", _manager_without_tools)
    names = [declaration["name"] for declaration in tools.all_declarations()]
    assert "run_script" in names


def test_run_script_is_not_declared_when_code_mode_is_off(monkeypatch):
    monkeypatch.setattr(tools, "get_manager", _manager_without_tools)
    monkeypatch.setenv("CODE_MODE", "off")
    names = [declaration["name"] for declaration in tools.all_declarations()]
    assert "run_script" not in names


@pytest.mark.parametrize("value, enabled", [("off", False), ("0", False), ("FALSE", False), ("on", True), ("", True)])
def test_code_mode_setting(monkeypatch, value, enabled):
    monkeypatch.setenv("CODE_MODE", value)
    assert config.get_code_mode() is enabled
