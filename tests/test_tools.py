from code_shellie import tools


def test_read_file_returns_whole_file_for_single_path(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text("one\ntwo\nthree\n", encoding="utf-8")

    assert tools.read_file(str(path)) == "one\ntwo\nthree\n"


def test_read_file_line_range(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")

    assert tools.read_file(str(path), start_line=2, end_line=3) == "two\nthree"


def test_read_file_batch_with_ranges_and_missing_file(tmp_path):
    a = tmp_path / "a.txt"
    a.write_text("a1\na2\na3\n", encoding="utf-8")

    result = tools.read_file(files=[
        {"file_path": str(a), "start_line": 2},
        {"file_path": str(tmp_path / "nope.txt")},
    ])

    assert f"=== {a} (lines 2-end) ===\na2\na3" in result
    assert "does not exist" in result


def test_read_file_needs_a_path():
    assert tools.read_file().startswith("Error")


def test_search_files_returns_matches_for_each_pattern(tmp_path):
    (tmp_path / "a.py").write_text("def alpha():\n    pass\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("beta = 1\n", encoding="utf-8")
    (tmp_path / ".hidden").mkdir()
    (tmp_path / ".hidden" / "c.py").write_text("alpha hidden\n", encoding="utf-8")

    result = tools.search_files(["def \\w+", "gamma"], path=str(tmp_path))

    assert f"{tmp_path / 'a.py'}:1: def alpha():" in result
    assert "alpha hidden" not in result
    assert "=== gamma (0 matches) ===\n(no matches)" in result


def test_search_files_rejects_bad_pattern(tmp_path):
    assert tools.search_files(["("], path=str(tmp_path)).startswith("Error: invalid pattern")


def test_list_directory_depth(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text("", encoding="utf-8")

    shallow = tools.list_directory(str(tmp_path))
    deep = tools.list_directory(str(tmp_path), depth=2)

    assert "pkg" in shallow and "mod.py" not in shallow
    assert "  📄 mod.py" in deep


def test_run_shell_command_batch_labels_each_result():
    result = tools.run_shell_command(commands=["echo one", "echo two"])

    assert "$ echo one\none" in result
    assert "$ echo two\ntwo" in result


def test_run_shell_command_needs_a_command():
    assert tools.run_shell_command().startswith("Error")
