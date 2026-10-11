"""AI providers behind one small interface.

The free default is Google Gemini (free tier). Setting LLM_PROVIDER=claude and an
ANTHROPIC_API_KEY switches to Claude with no other change. To add another provider,
implement `generate_json` and register it in `get_llm`.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Protocol

import requests

from .config import Settings

log = logging.getLogger(__name__)

DEFAULT_MODELS = {
    "gemini": "gemini-3.8-flash",
    "claude": "claude-opus-5-5",
}


class LLMError(RuntimeError):
    pass


class LLM(Protocol):
    name: str

    def generate_json(self, system: str, prompt: str, schema: dict) -> dict:
        """Return a JSON object that follows `schema`."""


class GeminiLLM:
    name = "gemini"
    URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    # The free tier sometimes stalls or is busy for a minute or two; these are worth another try.
    # Waits grow 10s, 20s, 30s, 40s, so a busy spell of up to ~100s is ridden out.
    RETRY_STATUS = {429, 500, 502, 503, 504}
    ATTEMPTS = 5

    def __init__(self, api_key: str, model: str | None = None, timeout: int = 90, retry_wait: float = 10):
        self.api_key = api_key
        self.model = model or DEFAULT_MODELS["gemini"]
        self.timeout = timeout
        self.retry_wait = retry_wait

    def _post(self, body: dict) -> requests.Response:
        for attempt in range(1, self.ATTEMPTS + 1):
            try:
                resp = requests.post(
                    self.URL.format(model=self.model),
                    headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
                    json=body,
                    timeout=self.timeout,
                )
                if resp.status_code not in self.RETRY_STATUS or attempt == self.ATTEMPTS:
                    return resp
                problem = f"status {resp.status_code}"
            except (requests.Timeout, requests.ConnectionError) as exc:
                if attempt == self.ATTEMPTS:
                    raise LLMError(f"Gemini did not respond after {self.ATTEMPTS} tries: {exc}") from exc
                problem = type(exc).__name__
            log.warning("Gemini attempt %d failed (%s); retrying.", attempt, problem)
            time.sleep(self.retry_wait * attempt)
        raise AssertionError("unreachable")

    def generate_json(self, system: str, prompt: str, schema: dict) -> dict:
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": f"{prompt}\n\nReply with only a JSON object matching this "
                            f"JSON Schema:\n{json.dumps(schema)}"
                        }
                    ],
                }
            ],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.8},
        }
        resp = self._post(body)
        if resp.status_code != 200:
            raise LLMError(f"Gemini returned {resp.status_code}: {resp.text[:300]}")
        try:
            text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(text)
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            raise LLMError(f"Gemini reply was not usable JSON: {resp.text[:300]}") from exc


class ClaudeLLM:
    name = "claude"

    def __init__(self, api_key: str, model: str | None = None):
        import anthropic

        self._anthropic = anthropic
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model or DEFAULT_MODELS["claude"]

    def generate_json(self, system: str, prompt: str, schema: dict) -> dict:
        anthropic = self._anthropic
        try:
            response = self.client.beta.messages.create(
                model=self.model,
                max_tokens=16000,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                output_config={
                    "effort": "medium",
                    "format": {"type": "json_schema", "schema": schema},
                },
                # If a request is declined, the API retries it on a recommended fallback model.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.APIStatusError as exc:
            raise LLMError(f"Claude returned {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError(f"Could not reach Claude: {exc}") from exc

        if response.stop_reason == "refusal":
            raise LLMError("Claude declined this request.")
        if response.stop_reason == "max_tokens":
            raise LLMError("Claude's reply was cut off.")
        text = next((b.text for b in response.content if b.type == "text"), None)
        if text is None:
            raise LLMError("Claude reply had no text.")
        return json.loads(text)


def get_llm(settings: Settings) -> LLM:
    provider = settings.llm_provider
    if provider == "gemini":
        if not settings.gemini_api_key:
            raise LLMError("GEMINI_API_KEY is not set.")
        return GeminiLLM(settings.gemini_api_key, settings.llm_model)
    if provider == "claude":
        if not settings.anthropic_api_key:
            raise LLMError("ANTHROPIC_API_KEY is not set.")
        return ClaudeLLM(settings.anthropic_api_key, settings.llm_model)
    raise LLMError(f"Unknown LLM_PROVIDER '{provider}'. Use 'gemini' or 'claude'.")
