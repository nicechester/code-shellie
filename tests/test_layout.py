import os
import subprocess

import pytest

from code_shellie import layout
from code_shellie.context import load_contexts
from code_shellie.layout import build_index, cache_path, load_layout


def _git(cwd, *args):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, env=env)


def _commit_all(repo, message):
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A git project with a fake home, so the cache does not touch the real ~/.shellie."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    project = tmp_path / "project"
    (project / "src" / "pkg").mkdir(parents=True)
    (project / "src" / "pkg" / "core.py").write_text("x = 1\n")
    (project / "src" / "pkg" / "tools.py").write_text("y = 2\n")
    (project / "README.md").write_text("# readme\n")
    (project / ".gitignore").write_text("build/\n")
    (project / "build").mkdir()
    (project / "build" / "out.txt").write_text("ignored\n")
    _git(project, "init", "-q")
    _commit_all(project, "init")
    monkeypatch.chdir(project)
    return project


def test_index_lists_files_by_directory_and_skips_ignored(repo):
    text = load_layout()
    assert text.startswith(f"Project layout (commit ")
    assert "./: .gitignore, README.md" in text
    assert "src/pkg/: core.py, tools.py" in text
    assert "build" not in text


def test_index_is_cached_outside_the_repo(repo):
    load_layout()
    path = cache_path(repo)
    assert path.exists()
    assert repo not in path.parents
    assert not any(p.name == "index.txt" for p in repo.rglob("*"))


def test_cached_index_is_reused_while_head_is_unchanged(repo, monkeypatch):
    load_layout()

    def fail(*args, **kwargs):
        raise AssertionError("index should not be rebuilt")

    monkeypatch.setattr(layout, "build_index", fail)
    assert "src/pkg/: core.py, tools.py" in load_layout()


def test_index_is_rebuilt_after_a_new_commit(repo):
    load_layout()
    (repo / "src" / "pkg" / "new_module.py").write_text("z = 3\n")
    _commit_all(repo, "add module")
    assert "new_module.py" in load_layout()


def test_outside_git_there_is_no_index(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    assert load_layout() == ""


def test_long_directories_are_truncated(repo, monkeypatch):
    monkeypatch.setattr(layout, "MAX_FILES_PER_DIR", 2)
    text = build_index(repo, "abc")
    assert "src/pkg/: core.py, tools.py" in text  # exactly at the limit: not truncated
    for i in range(3):
        (repo / "src" / "pkg" / f"extra{i}.py").write_text("")
    text = build_index(repo, "abc")
    assert "src/pkg/: core.py, extra0.py, ... 3 more" in text


def test_total_lines_are_capped(repo, monkeypatch):
    monkeypatch.setattr(layout, "MAX_LINES", 1)
    lines = build_index(repo, "abc").splitlines()
    listing = lines[lines.index("Files:") + 1:]
    assert len(listing) == 1
    assert listing[-1].startswith("... ") and "more directories" in listing[-1]


def test_header_records_commit_and_date(repo):
    header = build_index(repo, "abc123", today="2026-10-10").splitlines()[0]
    assert header.startswith("Project layout (commit abc123, generated 2026-10-10,")


def test_regeneration_is_announced_once_per_commit(repo, capsys):
    load_layout()
    assert "Project summary regenerated at commit" in capsys.readouterr().out
    load_layout()  # cache hit: nothing rebuilt, nothing announced
    assert capsys.readouterr().out == ""
    (repo / "notes.txt").write_text("x\n")
    _commit_all(repo, "add notes")
    load_layout()
    assert "Project summary regenerated" in capsys.readouterr().out


def test_startup_context_includes_layout(repo):
    context = load_contexts()
    assert "## Project Layout" in context
    assert "src/pkg/: core.py, tools.py" in context
