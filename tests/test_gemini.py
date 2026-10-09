from code_shellie import gemini


def test_parse_text_and_function_calls_and_usage():
    body = {
        "candidates": [{"content": {"role": "model", "parts": [
            {"text": "thinking", "thought": True},
            {"text": "Let me look. "},
            {"functionCall": {"name": "read_file", "args": {"file_path": "a"}}},
        ]}}],
        "usageMetadata": {"promptTokenCount": 120, "totalTokenCount": 150},
    }
    reply = gemini.parse_response(body)

    assert reply.text == "Let me look. "
    assert reply.function_calls == [("read_file", {"file_path": "a"})]
    assert reply.prompt_tokens == 120
    assert reply.total_tokens == 150
    assert reply.content == body["candidates"][0]["content"]


def test_parse_blocked_reply_is_empty():
    reply = gemini.parse_response({"promptFeedback": {"blockReason": "SAFETY"}})
    assert reply.text == ""
    assert reply.function_calls == []
    assert reply.content == {}


def test_error_message_variants():
    assert gemini.error_message({"error": {"message": "quota gone"}}, 429) == "quota gone"
    assert gemini.error_message({}, 500) == "HTTP 500"
