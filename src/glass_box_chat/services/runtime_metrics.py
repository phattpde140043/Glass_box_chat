from __future__ import annotations

import time
from typing import Any


class RuntimeMetrics:
    def __init__(self, llm_provider: str) -> None:
        self._metrics: dict[str, Any] = {
            "total_runs": 0,
            "total_nodes_executed": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "timeouts": 0,
            "retries": 0,
            "fallback_routes": 0,
            "avg_node_duration_ms": 0,
            "last_execution_mode": "sequential",
            "last_dag_node_count": 0,
            "llm_provider": llm_provider,
            "last_completed_at": None,
            "breaker_states": {},
            "breaker_details": {},
            "memory_entries": 0,
        }

    @property
    def state(self) -> dict[str, Any]:
        return self._metrics

    def mark_run_started(self, execution_mode: str, dag_node_count: int) -> None:
        self._metrics["total_runs"] += 1
        self._metrics["last_execution_mode"] = execution_mode
        self._metrics["last_dag_node_count"] = dag_node_count

    def update_memory_entries(self, memory_entries: int) -> None:
        self._metrics["memory_entries"] = memory_entries

    def record_execution_trace(self, execution_trace: list[dict[str, str]]) -> None:
        if not execution_trace:
            return

        self._metrics["total_nodes_executed"] += len(execution_trace)
        self._metrics["cache_hits"] += sum(1 for entry in execution_trace if entry.get("cache_hit") == "true")
        self._metrics["cache_misses"] += sum(1 for entry in execution_trace if entry.get("cache_hit") != "true")
        self._metrics["timeouts"] += sum(1 for entry in execution_trace if entry.get("output") == "timeout")
        self._metrics["fallback_routes"] += sum(1 for entry in execution_trace if entry.get("route_score") == "fallback")

        retry_count = 0
        durations: list[int] = []
        for entry in execution_trace:
            attempts_raw = entry.get("attempts", "0")
            duration_raw = entry.get("duration_ms", "0")
            try:
                retry_count += max(0, int(attempts_raw) - 1)
            except ValueError:
                pass
            try:
                durations.append(int(duration_raw))
            except ValueError:
                pass

        self._metrics["retries"] += retry_count
        if durations:
            self._metrics["avg_node_duration_ms"] = int(sum(durations) / len(durations))

    def mark_completed(self) -> None:
        self._metrics["last_completed_at"] = time.strftime("%H:%M:%S")

    def snapshot_with_breakers(
        self,
        breaker_states: dict[str, bool],
        breaker_details: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            **self._metrics,
            "breaker_states": dict(breaker_states),
            "breaker_details": breaker_details,
        }
