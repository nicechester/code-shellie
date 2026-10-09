from code_shellie import markdown


def test_plain_text_is_unchanged_without_a_terminal():
    assert markdown.render("just words") == "just words"


def test_headings_lists_and_quotes_lose_their_markers():
    out = markdown.render("# Title\n- one\n2. two\n> note")
    assert out == "Title\n• one\n2. two\n│ note"


def test_inline_code_and_emphasis_drop_their_markers():
    assert markdown.render("use `pytest` and **bold** or *soft*") == "use pytest and bold or soft"


def test_fenced_code_is_indented_and_keeps_markers_inside():
    out = markdown.render("before\n```\n# not a heading\n- not a bullet\n```\nafter")
    assert out == "before\n    # not a heading\n    - not a bullet\nafter"


def test_rule_is_drawn():
    assert markdown.render("---") == "─" * 40
