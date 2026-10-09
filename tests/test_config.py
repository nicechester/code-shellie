from code_shellie import config


def test_parse_dotenv_reads_keys_and_strips_quotes(tmp_path):
    path = tmp_path / ".env"
    path.write_text('# comment\nGEMINI_API_KEY="abc"\n\nGEMINI_MODEL=gemini-x\nNOEQUALS\n', encoding="utf-8")
    assert config.parse_dotenv(path) == {"GEMINI_API_KEY": "abc", "GEMINI_MODEL": "gemini-x"}


def test_parse_dotenv_missing_file_is_empty(tmp_path):
    assert config.parse_dotenv(tmp_path / "nope") == {}
