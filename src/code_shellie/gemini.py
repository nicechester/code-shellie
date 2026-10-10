"""Gemini REST client. One request per call; the retry policy lives in core.py."""
from __future__ import annotations

import time
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from .http import http_get, http_post_h

API_BASE = "https://generativelanguage.googleapis.com/v1beta/models/"
REQUEST_TIMEOUT_SEC = 120
SEARCH_5XX_BACKOFF_SEC = (1, 2, 4)  # same schedule as the chat path in core.py

# (title, uri) pairs from the most recent search, as Google returned them (redirect links)
last_sources: List[Tuple[str, str]] = []


class GeminiError(Exception):
    """The API refused a request, or retries are exhausted. Carries the HTTP status and the error message."""

    def __init__(self, code: int, message: str, body: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.body = body or {}


class Reply:
    """A parsed model turn: visible text, function calls as (name, args), and the raw content to keep in history."""

    def __init__(self, text: str, function_calls: List[Tuple[str, Dict[str, Any]]],
                 content: Dict[str, Any], prompt_tokens: int, total_tokens: int):
        self.text = text
        self.function_calls = function_calls
        self.content = content
        self.prompt_tokens = prompt_tokens
        self.total_tokens = total_tokens


def generate(model: str, api_key: str, payload: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    """POST one generateContent request. Returns (status, body); status 0 means a transport failure."""
    url = API_BASE + model + ":generateContent"
    body, status, _headers = http_post_h(
        url, payload, headers={"x-goog-api-key": api_key}, timeout=REQUEST_TIMEOUT_SEC
    )
    return status, body


def count_tokens(model: str, api_key: str, payload: Dict[str, Any]) -> Optional[int]:
    """Input tokens that a request with this payload would use, or None if the count cannot be fetched."""
    url = API_BASE + model + ":countTokens"
    body, status, _headers = http_post_h(url, payload, headers={"x-goog-api-key": api_key}, timeout=REQUEST_TIMEOUT_SEC)
    if status != 200 or not isinstance(body, dict) or body.get("totalTokens") is None:
        return None
    return int(body["totalTokens"])


def search(query: str, model: str, api_key: str) -> str:
    """Answer a query with Google Search grounding, as a separate request that does not touch the chat history.

    Returns the answer text, or "Web search failed (HTTP <status>)" on a non-200 response.
    """
    payload = {
        "contents": [{"parts": [{"text": query}]}],
        "tools": [{"google_search": {}}],
    }
    status, body = generate(model, api_key, payload)
    for delay in SEARCH_5XX_BACKOFF_SEC:
        if status < 500:
            break
        time.sleep(delay)
        status, body = generate(model, api_key, payload)
    if status != 200:
        return f"Web search failed (HTTP {status})"
    answer = parse_response(body).text or "(no result)"
    sources = _grounding_sources(body)
    last_sources[:] = sources
    if sources:
        answer += "\n\nSources:\n" + "\n".join(f"[{i}] {title} - {uri}" for i, (title, uri) in enumerate(sources, 1))
    return answer


def _grounding_sources(body: Dict[str, Any]) -> List[Tuple[str, str]]:
    """Unique (title, uri) pairs from the grounding metadata of the first candidate, in order."""
    candidates = body.get("candidates") or []
    candidate = candidates[0] if candidates and isinstance(candidates[0], dict) else {}
    metadata = candidate.get("groundingMetadata") or {}
    seen = []
    for chunk in metadata.get("groundingChunks") or []:
        web = chunk.get("web") if isinstance(chunk, dict) else None
        if not web or not web.get("uri"):
            continue
        pair = (web.get("title") or web["uri"], web["uri"])
        if pair not in seen:
            seen.append(pair)
    return seen


def get_input_limit(model: str, api_key: str) -> Optional[int]:
    """The model's input token limit, or None if it cannot be fetched."""
    body, status = http_get(API_BASE + model, headers={"x-goog-api-key": api_key})
    if status != 200:
        return None
    limit = body.get("inputTokenLimit")
    return int(limit) if limit else None


def error_message(body: Dict[str, Any], status: int) -> str:
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict) and error.get("message"):
        return str(error["message"])
    if isinstance(error, str) and error:
        return error
    return f"HTTP {status}"


def parse_response(body: Dict[str, Any]) -> Reply:
    """Extract text, function calls and usage from a generateContent response. Never raises on odd shapes."""
    usage = body.get("usageMetadata") or {}
    prompt_tokens = int(usage.get("promptTokenCount") or 0)
    total_tokens = int(usage.get("totalTokenCount") or 0)

    candidates = body.get("candidates") or []
    candidate = candidates[0] if candidates and isinstance(candidates[0], dict) else {}
    content = candidate.get("content") if isinstance(candidate.get("content"), dict) else {}
    parts = content.get("parts") if isinstance(content.get("parts"), list) else []

    text_chunks = []
    function_calls = []
    for part in parts:
        if not isinstance(part, dict) or part.get("thought"):
            continue
        if "functionCall" in part:
            call = part.get("functionCall") or {}
            function_calls.append((call.get("name", ""), call.get("args") or {}))
        elif "text" in part:
            text_chunks.append(part.get("text") or "")
    return Reply("".join(text_chunks), function_calls, content, prompt_tokens, total_tokens)


def resolve_url(uri: str, timeout: int = 10) -> str:
    """Follow a grounding redirect to the page it points at. Returns the original link if it cannot be followed."""
    try:
        with urllib.request.urlopen(uri, timeout=timeout) as res:
            return res.geturl()
    except Exception:
        return uri
