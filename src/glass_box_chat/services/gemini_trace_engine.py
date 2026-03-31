import asyncio
import os
from collections.abc import AsyncIterator
from typing import Any

import google.genai

from ..models.chat_models import TraceEvent
from ..utils.trace_payload_utils import build_trace_payload
from .trace_engine_protocol import TraceEngineProtocol


class GeminiTraceEngine(TraceEngineProtocol):
    """
    Real LLM-backed trace engine using Google Gemini API.
    Wraps Gemini API calls into a trace pipeline with thinking → tool_call → tool_result → done events.
    """

    def __init__(self, model: str = "gemini-2.5-flash"):
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable is not set.")

        # Keep explicit client initialization instead of relying on global env state.
        self._client = google.genai.Client(api_key=api_key)
        self.model = model
        self._cache: dict[str, str] = {}

    async def run(self, prompt: str, session_id: str, session_label: str, message_id: str) -> list[TraceEvent]:
        """
        Generate trace events by calling Gemini API.
        Pipeline: thinking → tool_call (generateContent) → tool_result (response) → done
        """
        events: list[TraceEvent] = []

        # 1. Thinking event
        events.append(
            TraceEvent(
                **build_trace_payload(
                    event="thinking",
                    detail=f"Sending a request to the Gemini API for analysis using model {self.model}.",
                    agent="GeminiLLM",
                    session_id=session_id,
                    session_label=session_label,
                    message_id=message_id,
                )
            )
        )

        # 2. Tool call event (API request)
        events.append(
            TraceEvent(
                **build_trace_payload(
                    event="tool_call",
                    detail=f"Calling {self.model}:generateContent with the prepared request payload.",
                    agent="GeminiLLM",
                    session_id=session_id,
                    session_label=session_label,
                    message_id=message_id,
                )
            )
        )

        # 3. Invoke Gemini in a thread pool (to avoid blocking)
        try:
            response = await asyncio.to_thread(
                self._call_gemini,
                prompt,
            )
            response_text = response
            self._cache[prompt] = response_text

        except Exception as err:
            response_text = f"Error: {err}"

        # 4. Tool result event (API response)
        events.append(
            TraceEvent(
                **build_trace_payload(
                    event="tool_result",
                    detail="Gemini returned a response payload. The content was stored for downstream consumption.",
                    agent="GeminiLLM",
                    session_id=session_id,
                    session_label=session_label,
                    message_id=message_id,
                )
            )
        )

        # 5. Done event
        events.append(
            TraceEvent(
                **build_trace_payload(
                    event="done",
                    detail="Gemini API call completed. Ready to send the result.",
                    agent="GeminiLLM",
                    session_id=session_id,
                    session_label=session_label,
                    message_id=message_id,
                )
            )
        )

        return events

    async def stream(self, prompt: str, session_id: str, session_label: str, message_id: str) -> AsyncIterator[TraceEvent]:
        for event in await self.run(prompt, session_id, session_label, message_id):
            yield event

    def _call_gemini(self, prompt: str) -> str:
        """Synchronous wrapper for Gemini API call."""
        try:
            response = self._client.models.generate_content(
                model=self.model,
                contents=prompt,
            )
            return self._extract_response_text(response)
        except Exception as err:
            raise RuntimeError(f"Gemini API error: {err}") from err

    def build_final_answer(self, prompt: str) -> str:
        """
        Return cached answer from prompt, or generate new one synchronously.
        """
        if prompt in self._cache:
            return self._cache[prompt]

        try:
            answer = self._call_gemini(prompt)
            self._cache[prompt] = answer
            return answer
        except Exception as err:
            return f"Error calling Gemini: {err}"

    def build_final_payload(self, prompt: str) -> dict[str, Any]:
        return {
            "type": "assistant_message",
            "content": self.build_final_answer(prompt),
        }

    def get_metrics(self) -> dict[str, Any]:
        return {
            "llm_provider": "gemini",
            "cache_size": len(self._cache),
        }

    def _extract_response_text(self, response) -> str:
        """
    +        Extract text content from Gemini response.
        google-genai returns response.text directly for simple cases.
        """
        # If response is already a string, return it
        if isinstance(response, str):
            return response

        # If response has text attribute (google-genai), use it
        if hasattr(response, "text"):
            text = response.text
            return text.strip() if text else "(empty response)"

        # If response is dict-like with content key
        if isinstance(response, dict) and "content" in response:
            parts = response.get("content", {}).get("parts", [])
            text_parts = [p.get("text", "") for p in parts if isinstance(p, dict)]
            return "\n".join(text_parts) or "(empty response)"

        return "(empty response)"
