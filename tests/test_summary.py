from code_shellie.summary import (
    MAX_COMMAND_LINES,
    MAX_CONVENTIONS,
    build_summary,
    commands_from_readme,
    conventions_from_claude_md,
    entry_points_from_pyproject,
    module_summaries,
)


def test_commands_come_from_code_blocks_under_command_headings():
    readme = """# Project

## Installation

```bash
./install.sh
```

## Architecture

```text
not a command
```

## Testing

```bash
# run the suite
venv/bin/pytest
codesh> not a shell line
```
"""
    assert commands_from_readme(readme) == ["./install.sh", "venv/bin/pytest"]


def test_command_list_is_capped():
    block = "\n".join(f"step {i}" for i in range(MAX_COMMAND_LINES + 5))
    readme = f"## Build\n\n```\n{block}\n```\n"
    assert len(commands_from_readme(readme)) == MAX_COMMAND_LINES


def test_entry_points_come_from_project_scripts_only():
    pyproject = """[project]
name = "x"
dependencies = []

[project.scripts]
codesh = "code_shellie.cli:main"

[tool.other]
name = "not an entry point"
"""
    assert entry_points_from_pyproject(pyproject) == ["codesh = code_shellie.cli:main"]


def test_conventions_are_the_bullets_in_claude_md():
    claude_md = "# Rules\n\n- Never commit without asking.\n* Use the venv.\nPlain text stays out.\n"
    assert conventions_from_claude_md(claude_md) == ["Never commit without asking.", "Use the venv."]


def test_convention_list_is_capped():
    claude_md = "\n".join(f"- rule {i}" for i in range(MAX_CONVENTIONS + 5))
    assert len(conventions_from_claude_md(claude_md)) == MAX_CONVENTIONS


def test_module_summaries_use_first_docstring_line_and_skip_tests(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "good.py").write_text('"""Does one thing.\n\nMore detail."""\nX = 1\n')
    (tmp_path / "pkg" / "bare.py").write_text("X = 1\n")
    (tmp_path / "pkg" / "broken.py").write_text("def (:\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text('"""A test."""\n')
    files = ["pkg/good.py", "pkg/bare.py", "pkg/broken.py", "tests/test_x.py", "README.md"]
    assert module_summaries(tmp_path, files) == ["pkg/good.py: Does one thing."]


def test_summary_with_no_files_says_so(tmp_path):
    lines = build_summary(tmp_path, [])
    assert "- none found in README.md or pyproject.toml" in lines
    assert "- none written down (no CLAUDE.md)" in lines
    assert "Modules:" not in lines


def test_summary_reads_the_project_files(tmp_path):
    (tmp_path / "README.md").write_text("## Quick start\n\n```bash\n./install.sh\n```\n")
    (tmp_path / "pyproject.toml").write_text('[project.scripts]\ncodesh = "app:main"\n')
    (tmp_path / "CLAUDE.md").write_text("- Do not commit unless asked.\n")
    lines = build_summary(tmp_path, [])
    assert "- entry point: codesh = app:main" in lines
    assert "- ./install.sh" in lines
    assert "- Do not commit unless asked." in lines
