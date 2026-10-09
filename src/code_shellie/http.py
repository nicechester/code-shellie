"""JSON HTTP helpers on urllib (stdlib only)."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Dict, Optional, Tuple


def http_post_h(
    url: str, payload: dict, headers: Optional[Dict[str, str]] = None, timeout: int = 60
) -> Tuple[dict, int, Dict[str, str]]:
    """POST a JSON payload and return (response_dict, status_code, response_headers).

    Response headers have lowercased keys. On an HTTP error the body is parsed
    as JSON when possible, otherwise wrapped as {"error": body}. A transport
    failure (no response at all) returns ({"error": message}, 0, {}).
    """
    try:
        headers = dict(headers or {})
        headers["Content-Type"] = "application/json"
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST"
        )
        with urllib.request.urlopen(req, timeout=timeout) as res:
            body = res.read().decode("utf-8", errors="replace")
            resp_headers = {k.lower(): v for k, v in res.headers.items()}
            return _parse_json(body), res.status, resp_headers
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        resp_headers = {k.lower(): v for k, v in e.headers.items()} if e.headers else {}
        data = _parse_json(body)
        if not data:
            data = {"error": body}
        return data, e.code, resp_headers
    except Exception as e:
        return {"error": str(e)}, 0, {}


def http_get(url: str, headers: Optional[Dict[str, str]] = None, timeout: int = 35) -> Tuple[dict, int]:
    """GET a JSON resource and return (response_dict, status_code). Errors as in http_post_h."""
    try:
        req = urllib.request.Request(url, headers=dict(headers or {}), method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return _parse_json(res.read().decode("utf-8", errors="replace")), res.status
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        data = _parse_json(body) or {"error": body}
        return data, e.code
    except Exception as e:
        return {"error": str(e)}, 0


def _parse_json(body: str) -> dict:
    if not body:
        return {}
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}
