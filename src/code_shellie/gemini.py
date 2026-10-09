"""Gemini REST client. One request per call; the retry policy lives in core.py."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .http import http_get, http_post_h

API_BASE = "https://generativelanguage.googleapis.com/v1beta/models/"
REQUEST_TIMEOUT_SEC = 120


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
