"""TRS-20-07: model access through one protocol with one method."""

from __future__ import annotations

import logging
from typing import Protocol

import httpx

log = logging.getLogger(__name__)


class NarratorBackend(Protocol):
    model_version: str

    def generate(self, system: str, user: str, schema: dict) -> str:
        """Return the model's raw JSON text for `user` under `system`, constrained to `schema`."""


class BackendUnavailable(RuntimeError):
    pass


class GeminiBackend:
    """Gemini API, JSON response schema. The key travels in a header, never in a URL."""

    URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def __init__(self, api_key: str, model: str = "gemini-2.5-flash", timeout: float = 60.0):
        if not api_key:
            raise BackendUnavailable("GEMINI_API_KEY is not set")
        self._key = api_key
        self.model_version = model
        self._timeout = timeout

    def generate(self, system: str, user: str, schema: dict) -> str:
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"responseMimeType": "application/json", "responseSchema": schema, "temperature": 0.4},
        }
        try:
            r = httpx.post(self.URL.format(model=self.model_version), json=body,
                           headers={"x-goog-api-key": self._key}, timeout=self._timeout)
        except httpx.HTTPError as e:
            raise BackendUnavailable(type(e).__name__) from e
        if r.status_code != 200:
            raise BackendUnavailable(f"HTTP {r.status_code}: {r.text.replace(self._key, '<key>')[:300]}")
        try:
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, ValueError) as e:
            raise BackendUnavailable(f"unexpected response shape: {e}") from e


class FakeBackend:
    """Deterministic stand-in for tests: returns queued responses in order."""

    model_version = "fake"

    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.calls: list[str] = []

    def generate(self, system: str, user: str, schema: dict) -> str:
        self.calls.append(user)
        if not self.responses:
            raise BackendUnavailable("no more fake responses")
        return self.responses.pop(0)
