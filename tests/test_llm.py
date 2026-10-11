import json

import pytest

from agent import llm
from agent.config import Settings


class Resp:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body
        self.text = json.dumps(body)

    def json(self):
        return self._body


def test_gemini_parses_json_reply(monkeypatch):
    sent = {}

    def fake_post(url, headers, json, timeout):
        sent.update(url=url, headers=headers, body=json)
        return Resp(200, {"candidates": [{"content": {"parts": [{"text": '{"topic": "x"}'}]}}]})

    monkeypatch.setattr(llm.requests, "post", fake_post)
    out = llm.GeminiLLM("key").generate_json("sys", "prompt", {"type": "object"})
    assert out == {"topic": "x"}
    assert "gemini-3.8-flash" in sent["url"]
    assert sent["headers"]["x-goog-api-key"] == "key"
    assert sent["body"]["generationConfig"]["responseMimeType"] == "application/json"


def test_gemini_error_is_readable(monkeypatch):
    monkeypatch.setattr(llm.requests, "post", lambda *a, **k: Resp(400, {"error": "bad request"}))
    with pytest.raises(llm.LLMError, match="400"):
        llm.GeminiLLM("key", retry_wait=0).generate_json("s", "p", {})


def test_gemini_retries_timeouts_and_busy_replies(monkeypatch):
    replies = [
        llm.requests.Timeout("read timed out"),
        Resp(503, {"error": "busy"}),
        Resp(200, {"candidates": [{"content": {"parts": [{"text": '{"ok": 1}'}]}}]}),
    ]

    def fake_post(*a, **k):
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(llm.requests, "post", fake_post)
    assert llm.GeminiLLM("key", retry_wait=0).generate_json("s", "p", {}) == {"ok": 1}


def test_gemini_gives_up_after_five_timeouts(monkeypatch):
    def always_slow(*a, **k):
        raise llm.requests.Timeout("read timed out")

    monkeypatch.setattr(llm.requests, "post", always_slow)
    with pytest.raises(llm.LLMError, match="5 tries"):
        llm.GeminiLLM("key", retry_wait=0).generate_json("s", "p", {})


def test_get_llm_picks_provider_and_requires_key():
    assert isinstance(llm.get_llm(Settings(gemini_api_key="k")), llm.GeminiLLM)
    assert isinstance(llm.get_llm(Settings(llm_provider="claude", anthropic_api_key="k")), llm.ClaudeLLM)
    with pytest.raises(llm.LLMError, match="GEMINI_API_KEY"):
        llm.get_llm(Settings())
    with pytest.raises(llm.LLMError, match="Unknown"):
        llm.get_llm(Settings(llm_provider="other"))


def test_claude_uses_structured_output(monkeypatch):
    claude = llm.ClaudeLLM("key")
    captured = {}

    class Block:
        type = "text"
        text = '{"topic": "y"}'

    class Message:
        stop_reason = "end_turn"
        content = [Block()]

    def fake_create(**kwargs):
        captured.update(kwargs)
        return Message()

    monkeypatch.setattr(claude.client.beta.messages, "create", fake_create)
    assert claude.generate_json("sys", "p", {"type": "object"}) == {"topic": "y"}
    assert captured["model"] == "claude-opus-5-5"
    assert captured["output_config"]["format"]["type"] == "json_schema"
    assert captured["fallbacks"] == "default"


def test_settings_from_env():
    s = Settings.from_env({"LLM_PROVIDER": " Claude ", "LINKEDIN_TOKEN_EXPIRES_ON": "2026-12-01"})
    assert s.llm_provider == "claude"
    assert s.linkedin_token_expires_on.isoformat() == "2026-12-01"
    assert not s.linkedin_configured
