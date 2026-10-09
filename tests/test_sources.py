from code_shellie import gemini


class FakeResponse:
    def __init__(self, url):
        self.url = url

    def geturl(self):
        return self.url

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_resolve_url_follows_redirect(monkeypatch):
    monkeypatch.setattr(gemini.urllib.request, "urlopen",
                        lambda uri, timeout: FakeResponse("https://endoflife.date/nodejs"))

    assert gemini.resolve_url("https://vertexaisearch.cloud.google.com/redirect/x") == "https://endoflife.date/nodejs"


def test_resolve_url_keeps_original_when_unreachable(monkeypatch):
    def fail(uri, timeout):
        raise OSError("no network")
    monkeypatch.setattr(gemini.urllib.request, "urlopen", fail)

    assert gemini.resolve_url("https://vertexaisearch.cloud.google.com/redirect/x") == \
        "https://vertexaisearch.cloud.google.com/redirect/x"


def test_search_records_sources_for_sources_command(monkeypatch):
    body = {"candidates": [{
        "content": {"parts": [{"text": "answer"}]},
        "groundingMetadata": {"groundingChunks": [{"web": {"uri": "https://r.example/1", "title": "npmjs.com"}}]},
    }]}
    monkeypatch.setattr(gemini, "generate", lambda *a: (200, body))

    gemini.search("q", "m", "key")

    assert gemini.last_sources == [("npmjs.com", "https://r.example/1")]
