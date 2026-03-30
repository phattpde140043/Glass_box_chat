from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolInput:
    """Standardized input for all tools."""
    query: str
    timeout_seconds: float = 5.0
    limit: int = 5
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolOutput:
    """Standardized output for all tools."""
    success: bool
    content: str
    source_url: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.5
    latency_ms: int = 0
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class Tool(Protocol):
    """Contract for all tool implementations."""
    
    name: str
    description: str
    timeout_seconds: float
    max_retries: int
    
    async def execute(self, tool_input: ToolInput) -> ToolOutput: ...


class BaseTool:
    """Base class for tool implementations with common retry/timeout logic."""
    
    def __init__(
        self,
        name: str,
        description: str,
        timeout_seconds: float = 5.0,
        max_retries: int = 2,
    ) -> None:
        self.name = name
        self.description = description
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
    
    async def execute_with_retry(
        self,
        tool_input: ToolInput,
        execute_fn: Any,  # async callable
    ) -> ToolOutput:
        """Execute with exponential backoff retry logic."""
        import asyncio
        
        started_at = time.perf_counter()
        last_error = None
        
        for attempt in range(self.max_retries + 1):
            try:
                result = await asyncio.wait_for(
                    execute_fn(tool_input),
                    timeout=tool_input.timeout_seconds,
                )
                latency_ms = int((time.perf_counter() - started_at) * 1000)
                result.latency_ms = latency_ms
                result.metadata["attempts"] = attempt + 1
                return result
            except asyncio.TimeoutError:
                last_error = f"timeout after {tool_input.timeout_seconds}s"
            except Exception as e:
                last_error = str(e)
            
            if attempt < self.max_retries:
                backoff_seconds = 2 ** attempt
                await asyncio.sleep(backoff_seconds)
        
        return ToolOutput(
            success=False,
            content="",
            error=last_error or "unknown error",
            latency_ms=int((time.perf_counter() - started_at) * 1000),
            metadata={"attempts": self.max_retries + 1},
        )
