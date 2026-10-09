from code_shellie import shell


def test_output_is_returned():
    assert shell.run_command("echo hi") == "hi"


def test_no_output_message():
    assert shell.run_command("true") == "[Command executed with no output]"


def test_stderr_and_exit_code_are_reported():
    out = shell.run_command("echo oops >&2; exit 3")
    assert "STDERR:\noops" in out
    assert "[Exit code: 3]" in out


def test_timeout_kills_the_command(monkeypatch):
    monkeypatch.setattr(shell, "TIMEOUT_SEC", 0.5)
    assert shell.run_command("sleep 5") == "Error: Command timed out after 0.5 seconds."


def test_api_key_is_not_passed_to_child(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "secret")
    assert shell.run_command('echo "${GEMINI_API_KEY:-none}"') == "none"


def test_long_output_is_truncated(monkeypatch):
    monkeypatch.setattr(shell, "OUTPUT_LIMIT", 10)
    out = shell.run_command("printf 'x%.0s' $(seq 1 50)")
    assert out.startswith("x" * 10)
    assert "truncated at 10 chars" in out
