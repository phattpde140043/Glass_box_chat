from __future__ import annotations

import os
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from ..models.chat_models import TraceEvent
from ..utils.trace_payload_utils import build_trace_payload
from .trace_engine_protocol import TraceEngineProtocol


class MockOrchestratorSkillAgent(TraceEngineProtocol):
    """
    Placeholder orchestrator agent providing basic trace generation.
    Full skill-based orchestration with DAG planning, semantic routing, and LLM backends
    to be implemented in subsequent commits.
    """

    def __init__(self, model: str = "gemini-2.5-flash") -> None:
        self.model = model
        self._metrics = {
            "model": model,
            "runs": 0,
            "errors": 0,
            "avgTokens": 0,
            "lastRunDuration": 0.0,
        }

    async def run(self, prompt: str, session_id: str, session_label: str) -> list[TraceEvent]:
        return [event async for event in self.stream(prompt, session_id, session_label)]

    async def stream(self, prompt: str, session_id: str, session_label: str) -> AsyncIterator[TraceEvent]:
        """Generate mock trace events for debugging and testing."""
        start_time = time.time()
        self._metrics["runs"] += 1

        try:
            # Analysis phase
            yield TraceEvent(
                **build_trace_payload(
                    event="thinking",
                    detail=f"Analyzing input: {prompt[:50]}...",
                    agent="OrchestratorAgent",
                    session_id=session_id,
                    session_label=session_label,
                )
            )

            # Planning phase
            yield TraceEvent(
                **build_trace_payload(
                    event="thinking",
                    detail="Building execution plan with skill DAG",
                    agent="PlannerAgent",
                    session_id=session_id,
                    session_label=session_label,
                )
            )

            # Execution phase
            yield TraceEvent(
                **build_trace_payload(
                    event="tool_call",
                    detail="Routing to search skill",
                    agent="ExecutorAgent",
                    branch="research",
                    session_id=session_id,
                    session_label=session_label,
                )
            )

            yield TraceEvent(
                **build_trace_payload(
                    event="tool_result",
                    detail="Search completed with 5 results",
                    agent="SearchSkill",
                    branch="research",
                    session_id=session_id,
                    session_label=session_label,
                )
            )

            # Synthesis phase
            yield TraceEvent(
                **build_trace_payload(
                    event="thinking",
                    detail="Synthesizing results and generating final answer",
                    agent="SynthesisAgent",
                    session_id=session_id,
                    session_label=session_label,
                )
            )

            yield TraceEvent(
                **build_trace_payload(
                    event="done",
                    detail="Analysis complete",
                    agent="OrchestratorAgent",
                    session_id=session_id,
                    session_label=session_label,
                )
            )

            duration = time.time() - start_time
            self._metrics["lastRunDuration"] = duration

        except Exception as err:
            self._metrics["errors"] += 1
            raise

    def get_metrics(self) -> dict[str, Any]:
        return {
            "engine": "MockOrchestratorSkillAgent",
            "model": self.model,
            "state": self._metrics,
            "status": "placeholder",
            "note": "Full implementation with DAG planning and skill orchestration coming in next commit",
        }

    def build_final_answer(self, prompt: str) -> str:
        return f"Mock response to: {prompt}"

    def build_final_payload(self, prompt: str) -> dict[str, Any]:
        return {
            "type": "assistant_message",
            "content": self.build_final_answer(prompt),
            "sources": ["https://docs.example.com"],
            "sourceDetails": [
                {
                    "title": "Example Documentation",
                    "url": "https://docs.example.com",
                    "freshness": "today",
                }
            ],
        }
