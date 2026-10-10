from code_shellie import line_editor
from code_shellie.line_editor import LineEditor


def test_typing_and_enter_submits():
    ed = LineEditor()
    assert ed._process("abc") is None
    assert ed.buf == "abc"
    assert ed._process("\r") == "abc"
    assert ed.buf == ""


def test_backspace_and_ctrl_u():
    ed = LineEditor()
    ed._process("ab\x7fc")
    assert ed.buf == "ac"
    ed._process("\x15xyz")
    assert ed.buf == "xyz"


def test_newlines_from_alt_enter_and_ctrl_j():
    ed = LineEditor()
    ed._process("a\x1b\rb\nc")
    assert ed.buf == "a\nb\nc"


def test_paste_keeps_newlines_and_does_not_submit():
    ed = LineEditor()
    assert ed._process("\x1b[200~line1\r\nline2\rline3\x1b[201~") is None
    assert ed.buf == "line1\nline2\nline3"


def test_paste_split_across_reads():
    ed = LineEditor()
    ed._process("\x1b[200~ab\x1b[20")
    ed._process("1~c")
    assert ed.buf == "abc"
    assert ed._process("\r") == "abc"


def test_left_and_right_edit_at_cursor():
    ed = LineEditor()
    ed._process("hi\x1b[D\x1b[Dx")
    assert ed.buf == "xhi"
    assert ed.cursor == 1
    ed._process("\x1bOC\x1bOC")  # SS3 form, two right moves clamp at the end
    assert ed.cursor == 3
    ed._process("\x1b[D\x7f")  # Backspace removes the character before the cursor
    assert ed.buf == "xi" and ed.cursor == 1


def test_delete_and_ctrl_d_remove_under_cursor():
    ed = LineEditor()
    ed._process("abc\x1b[D\x1b[D\x1b[3~")  # cursor on "b", Delete removes it
    assert ed.buf == "ac" and ed.cursor == 1
    ed._process("\x01\x04")  # Ctrl+A moves to start, Ctrl+D deletes under the cursor
    assert ed.buf == "c" and ed.cursor == 0


def test_home_end_and_ctrl_a_ctrl_e():
    ed = LineEditor()
    ed._process("mid")
    ed._process("\x1b[H")
    assert ed.cursor == 0
    ed._process("\x1b[F")
    assert ed.cursor == 3
    ed._process("\x01")
    assert ed.cursor == 0
    ed._process("\x05")
    assert ed.cursor == 3


def test_paste_inserts_at_cursor():
    ed = LineEditor()
    ed._process("ad\x1b[D")
    ed._process("\x1b[200~bc\x1b[201~")
    assert ed.buf == "abcd" and ed.cursor == 3


def test_tab_completes_before_cursor():
    seen = []

    def completer(text):
        seen.append(text)
        return (3, ["/clear"]) if text == "/cl" else (0, [])

    ed = LineEditor(completer=completer)
    ed.buf, ed.cursor = "/cl tail", 3
    ed._process("\t")
    assert seen == ["/cl"]  # only the text before the cursor is completed
    assert ed.buf == "/clear  tail"
    assert ed.cursor == len("/clear ")


def test_history_recall_and_draft_restore(tmp_path):
    ed = LineEditor(history_path=tmp_path / "history.jsonl")
    for text in ("one", "two"):
        ed._process(text + "\r")
    ed._process("dra")
    ed._process("\x1b[A")
    assert ed.buf == "two"
    ed._process("\x1b[A")
    assert ed.buf == "one"
    ed._process("\x1b[A")  # oldest reached, stays there
    assert ed.buf == "one"
    ed._process("\x1b[B\x1b[B")
    assert ed.buf == "dra"  # back past the newest restores the draft


def test_history_skips_empty_and_consecutive_duplicates(tmp_path):
    ed = LineEditor(history_path=tmp_path / "history.jsonl")
    ed._process("\r")
    ed._process("a\r")
    ed._process("a\r")
    ed._process("   \r")
    ed._process("b\r")
    assert ed.history == ["a", "b"]


def test_history_persists_and_is_capped(tmp_path, monkeypatch):
    monkeypatch.setattr("code_shellie.line_editor.MAX_HISTORY", 3)
    path = tmp_path / "config" / "history.jsonl"
    ed = LineEditor(history_path=path)
    for text in ("1", "2", "3", "4"):
        ed._process(text + "\r")
    assert path.read_text(encoding="utf-8").splitlines() == ['"2"', '"3"', '"4"']
    assert LineEditor(history_path=path).history == ["2", "3", "4"]


def test_history_write_errors_are_ignored(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("not a directory")
    ed = LineEditor(history_path=blocker / "history.jsonl")
    ed._process("ok\r")
    assert ed.history == ["ok"]


def test_history_file_with_bad_lines_is_tolerated(tmp_path):
    path = tmp_path / "history.jsonl"
    path.write_text('"good"\nnot json\n42\n"also good"\n', encoding="utf-8")
    assert LineEditor(history_path=path).history == ["good", "also good"]


def test_up_and_down_move_between_lines_before_history(tmp_path):
    ed = LineEditor(history_path=tmp_path / "history.jsonl")
    ed._process("old\r")
    ed._process("ab\ncdef")  # cursor at end of "cdef" (line 2, column 4)
    ed._process("\x1b[A")
    assert ed.buf == "ab\ncdef" and ed.cursor == 2  # column 4 clamped to the end of "ab"
    ed._process("\x1b[A")  # now on the first line: history
    assert ed.buf == "old"
    ed._process("\x1b[B")  # back to the draft, which is multi-line, cursor on its last line
    assert ed.buf == "ab\ncdef"


def test_render_places_cursor_at_editing_position(monkeypatch, capsys):
    monkeypatch.setenv("COLUMNS", "80")
    ed = LineEditor()
    ed.buf, ed.cursor = "ab", 1
    ed._render()
    # prompt "codesh> " is 8 visible columns, so the cursor sits at column 9 (1-based 10)
    assert capsys.readouterr().out.endswith("\r\x1b[10G")


def test_tab_completes_single_candidate():
    ed = LineEditor(completer=lambda text: (3, ["/clear"]) if text == "/cl" else (0, []))
    ed._process("/cl\t")
    assert ed.buf == "/clear "


def test_tab_extends_to_common_prefix(capsys):
    ed = LineEditor(completer=lambda text: (1, ["abc.py", "abd.py"]))
    ed._process("a\t")
    assert ed.buf == "ab"


def test_ctrl_o_calls_toggle(capsys):
    calls = []
    ed = LineEditor(on_toggle_view=lambda: calls.append(1) or "verbose")
    ed._process("\x0f")
    assert calls == [1]
    assert "Output view: verbose" in capsys.readouterr().out


def test_ctrl_c_and_ctrl_d(capsys):
    ed = LineEditor()
    ed._process("x")
    try:
        ed._process("\x03")
    except KeyboardInterrupt:
        pass
    else:
        raise AssertionError("Ctrl+C should raise KeyboardInterrupt")
    assert ed.buf == ""

    try:
        LineEditor()._process("\x04")
    except EOFError:
        pass
    else:
        raise AssertionError("Ctrl+D on an empty line should raise EOFError")


def test_partial_suffix():
    assert line_editor._partial_suffix("ab\x1b[20", "\x1b[201~") == 4
    assert line_editor._partial_suffix("ab", "\x1b[201~") == 0


def test_keys_on_a_real_pseudo_terminal(tmp_path):
    """Runs the editor on a pty, so termios, the raw key reads and the redraw path are all exercised."""
    import os
    import pty
    import subprocess
    import sys
    import time

    out = tmp_path / "results.txt"
    hist = tmp_path / "history.jsonl"
    child = (
        "from code_shellie.line_editor import LineEditor\n"
        f"ed = LineEditor(history_path={str(hist)!r})\n"
        "for _ in range(4):\n"
        f"    open({str(out)!r}, 'a').write(repr(ed.read()) + '\\n')\n"
    )
    master, slave = pty.openpty()
    proc = subprocess.Popen([sys.executable, "-c", child], stdin=slave, stdout=slave, stderr=slave, close_fds=True)
    os.close(slave)
    keys = [
        b"first\r",
        b"second\r",
        b"ac\x1b[Db\r",              # cursor moves left, so "b" goes between a and c
        b"\x1b[A\x1b[A\r",           # Up twice: "abc", then "second"
    ]
    try:
        for chunk in keys:
            time.sleep(0.3)
            os.write(master, chunk)
            time.sleep(0.1)
        # Drain the output so the child never blocks on a full pty buffer
        deadline = time.time() + 10
        while proc.poll() is None and time.time() < deadline:
            try:
                os.read(master, 4096)
            except OSError:
                break
        assert proc.wait(timeout=5) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
        os.close(master)

    assert out.read_text(encoding="utf-8").splitlines() == ["'first'", "'second'", "'abc'", "'second'"]
    assert hist.read_text(encoding="utf-8").splitlines() == ['"first"', '"second"', '"abc"', '"second"']
