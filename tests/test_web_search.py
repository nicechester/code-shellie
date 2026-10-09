from code_shellie import gemini, tools


def test_search_sends_grounding_request_and_returns_answer(monkeypatch):
    sent = {}

    def fake_post(url, payload, headers=None, timeout=60):
        sent.update(url=url, payload=payload, headers=headers)
        return {"candidates": [{"content": {"parts": [{"text": "Python 3.13 was released in October 2024."}]}}]}, 200, {}

    monkeypatch.setattr(gemini, "http_post_h", fake_post)

    answer = gemini.search("when was python 3.13 released", "gemma-4-26b-a4b-it", "key")

    assert answer == "Python 3.13 was released in October 2024."
    assert sent["url"].endswith("/models/gemma-4-26b-a4b-it:generateContent")
    assert sent["payload"] == {
        "contents": [{"parts": [{"text": "when was python 3.13 released"}]}],
        "tools": [{"google_search": {}}],
    }
    assert sent["headers"] == {"x-goog-api-key": "key"}


def test_search_error_status_is_returned_as_text(monkeypatch):
    monkeypatch.setattr(gemini, "http_post_h", lambda *a, **k: ({"error": "quota"}, 429, {}))

    assert gemini.search("anything", "m", "key") == "Web search failed (HTTP 429)"


def test_tool_uses_configured_search_model(monkeypatch):
    calls = []
    monkeypatch.setenv("SEARCH_MODEL", "custom-search-model")
    monkeypatch.setenv("GEMINI_API_KEY", "key")
    monkeypatch.setattr(tools, "gemini_search", lambda q, m, k: calls.append((q, m, k)) or "answer")

    assert tools.execute_tool("execute_web_search", {"query": "docs"}) == "answer"
    assert calls == [("docs", "custom-search-model", "key")]


def test_search_model_defaults_to_shellie_model(monkeypatch):
    monkeypatch.delenv("SEARCH_MODEL", raising=False)
    from code_shellie import config
    monkeypatch.setattr(config, "load_environment", lambda: None)
    assert config.get_search_model() == "gemma-4-26b-a4b-it"


def test_search_is_declared_to_the_model():
    names = [d["name"] for d in tools.TOOL_DECLARATIONS]
    assert "execute_web_search" in names


def test_search_retries_server_errors_with_backoff(monkeypatch):
    sleeps = []
    responses = [(500, {"error": "busy"}), (503, {"error": "busy"}),
                 (200, {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]})]
    monkeypatch.setattr(gemini, "generate", lambda *a: responses.pop(0))
    monkeypatch.setattr(gemini.time, "sleep", lambda s: sleeps.append(s))

    assert gemini.search("q", "m", "key") == "ok"
    assert sleeps == [1, 2]


def test_search_gives_up_after_backoff_schedule(monkeypatch):
    sleeps = []
    calls = []
    monkeypatch.setattr(gemini, "generate", lambda *a: calls.append(1) or (500, {"error": "down"}))
    monkeypatch.setattr(gemini.time, "sleep", lambda s: sleeps.append(s))

    assert gemini.search("q", "m", "key") == "Web search failed (HTTP 500)"
    assert sleeps == [1, 2, 4]
    assert len(calls) == 4


def test_search_does_not_retry_client_errors(monkeypatch):
    calls = []
    monkeypatch.setattr(gemini, "generate", lambda *a: calls.append(1) or (404, {"error": "gone"}))
    monkeypatch.setattr(gemini.time, "sleep", lambda s: None)

    assert gemini.search("q", "m", "key") == "Web search failed (HTTP 404)"
    assert len(calls) == 1


def test_search_appends_deduplicated_sources(monkeypatch):
    body = {"candidates": [{
        "content": {"parts": [{"text": "Toy Story 5 passed $1.1B."}]},
        "groundingMetadata": {"groundingChunks": [
            {"web": {"uri": "https://a.example/x", "title": "Box Office A"}},
            {"web": {"uri": "https://b.example/y", "title": "Box Office B"}},
            {"web": {"uri": "https://a.example/x", "title": "Box Office A"}},
            {"retrieved_context": {"uri": "ignored"}},
        ]},
    }]}
    monkeypatch.setattr(gemini, "generate", lambda *a: (200, body))

    assert gemini.search("q", "m", "key") == (
        "Toy Story 5 passed $1.1B.\n\nSources:\n"
        "[1] Box Office A - https://a.example/x\n"
        "[2] Box Office B - https://b.example/y"
    )


def test_search_without_grounding_has_no_sources(monkeypatch):
    body = {"candidates": [{"content": {"parts": [{"text": "plain answer"}]}}]}
    monkeypatch.setattr(gemini, "generate", lambda *a: (200, body))

    assert gemini.search("q", "m", "key") == "plain answer"
