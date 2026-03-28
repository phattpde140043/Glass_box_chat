from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable

from ..models.chat_models import TraceEvent


@runtime_checkable
class ExecutionTraceEngineProtocol(Protocol):
    """Execution contract for engines that produce trace events."""

    async def stream(self, prompt: str, session_id: str, session_label: str) -> AsyncIterator[TraceEvent]: ...

    async def run(self, prompt: str, session_id: str, session_label: str) -> list[TraceEvent]: ...


@runtime_checkable
class FinalResponseProtocol(Protocol):
    """Final answer/payload rendering contract."""

    def build_final_answer(self, prompt: str) -> str: ...

    def build_final_payload(self, prompt: str) -> dict[str, Any]: ...


@runtime_checkable
class MetricsProviderProtocol(Protocol):
    """Metrics snapshot contract."""

    def get_metrics(self) -> dict[str, Any]: ...


@runtime_checkable
class AgentRunTraceEngineProtocol(ExecutionTraceEngineProtocol, FinalResponseProtocol, Protocol):
    """Minimal protocol needed by AgentRunService."""


@runtime_checkable
class TraceEngineProtocol(ExecutionTraceEngineProtocol, FinalResponseProtocol, MetricsProviderProtocol, Protocol):
    """Backward-compatible composite contract used by controllers/runtime wiring."""
