from __future__ import annotations

import os
from typing import Protocol

import google.genai


class LLMBackend(Protocol):
    provider: str

    def generate(self, model: str, prompt: str) -> object: ...


class GeminiLLMBackend:
    provider = "gemini"

    def __init__(self, api_key: str) -> None:
        self._client = google.genai.Client(api_key=api_key)

    def generate(self, model: str, prompt: str) -> object:
        return self._client.models.generate_content(model=model, contents=prompt)


class ClaudeLLMBackend:
    provider = "claude"

    def __init__(self, api_key: str) -> None:
        try:
            import anthropic  # type: ignore[import-not-found]
        except ImportError as err:  # pragma: no cover - optional dependency
            raise RuntimeError("anthropic package is required for Claude backend.") from err
        self._client = anthropic.Anthropic(api_key=api_key)

    def generate(self, model: str, prompt: str) -> object:
        max_tokens = int(os.getenv("CLAUDE_MAX_TOKENS", "1024"))
        response = self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        contents = getattr(response, "content", None)
        if isinstance(contents, list):
            parts: list[str] = []
            for block in contents:
                text = getattr(block, "text", None)
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
            if parts:
                return "\n".join(parts)
        return response
