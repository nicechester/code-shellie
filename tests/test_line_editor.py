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


def test_arrow_keys_are_ignored():
    ed = LineEditor()
    ed._process("a\x1b[")
    ed._process("A\x1bOB")
    assert ed.buf == "a"


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
