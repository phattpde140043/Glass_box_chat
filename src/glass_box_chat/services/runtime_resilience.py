from __future__ import annotations

import json
import re
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Literal


ErrorType = Literal["transient", "permanent", "system"]


@dataclass
class CacheEntry:
    value: dict[str, Any] | str
    expires_at: float
    version: str


@dataclass
class MemoryEntry:
    kind: str
    content: str
    created_at: float = field(default_factory=time.time)


class NodeCache:
    def __init__(self, ttl_seconds: float = 120.0, version: str = "v2") -> None:
        self._ttl_seconds = ttl_seconds
        self._version = version
        self._cache: dict[str, CacheEntry] = {}

    def build_key(
        self,
        node: Any,
        normalized_prompt: str,
        dependency_outputs: dict[str, Any],
        recent_memory: str,
    ) -> str:
        payload = {
            "skill": node.skill,
            "input": node.input,
            "normalized_prompt": normalized_prompt,
            "dependency_outputs": dependency_outputs,
            "recent_memory": recent_memory,
            "cache_version": self._version,
        }
        return json.dumps(payload, sort_keys=True, ensure_ascii=False)

    def get(self, key: str) -> dict[str, Any] | str | None:
        entry = self._cache.get(key)
        if entry is None:
            return None
        if entry.version != self._version or entry.expires_at <= time.time():
            self._cache.pop(key, None)
            return None
        return entry.value

    def set(self, key: str, value: dict[str, Any] | str) -> None:
        self._cache[key] = CacheEntry(
            value=value,
            expires_at=time.time() + self._ttl_seconds,
            version=self._version,
        )


class CircuitBreaker:
    def __init__(
        self,
        fail_threshold: int = 5,
        recovery_timeout_seconds: float = 15.0,
        half_open_max_calls: int = 1,
    ) -> None:
        self._fail_threshold = fail_threshold
        self._recovery_timeout_seconds = recovery_timeout_seconds
        self._half_open_max_calls = half_open_max_calls
        self._state: Literal["closed", "open", "half_open"] = "closed"
        self._consecutive_failures = 0
        self._opened_until = 0.0
        self._half_open_calls = 0

    def allow_request(self) -> bool:
        now = time.time()
        if self._state == "closed":
            return True
        if self._state == "open":
            if now >= self._opened_until:
                self._state = "half_open"
                self._half_open_calls = 0
            else:
                return False
        if self._state == "half_open":
            if self._half_open_calls >= self._half_open_max_calls:
                return False
            self._half_open_calls += 1
            return True
        return True

    def record_success(self) -> None:
        self._state = "closed"
        self._consecutive_failures = 0
        self._half_open_calls = 0
        self._opened_until = 0.0

    def record_failure(self) -> None:
        if self._state == "half_open":
            self._trip_open()
            return
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._fail_threshold:
            self._trip_open()

    def _trip_open(self) -> None:
        self._state = "open"
        self._opened_until = time.time() + self._recovery_timeout_seconds
        self._half_open_calls = 0

    def is_open(self) -> bool:
        return self._state == "open" and time.time() < self._opened_until

    def snapshot(self) -> dict[str, Any]:
        return {
            "state": self._state,
            "consecutive_failures": self._consecutive_failures,
            "opened_until": self._opened_until if self._state == "open" else None,
        }


class ShortTermMemoryStore:
    def __init__(self, max_entries: int = 12) -> None:
        self._max_entries = max_entries
        self._sessions: dict[str, deque[MemoryEntry]] = {}

    def remember(self, session_id: str, kind: str, content: str) -> None:
        cleaned = re.sub(r"\s+", " ", content).strip()
        if not cleaned:
            return
        session_memory = self._sessions.setdefault(session_id, deque(maxlen=self._max_entries))
        session_memory.append(MemoryEntry(kind=kind, content=cleaned[:600]))

    def snapshot(self, session_id: str, limit: int = 6) -> str:
        entries = list(self._sessions.get(session_id, deque()))[-limit:]
        if not entries:
            return ""
        return "\n".join(f"- {entry.kind}: {entry.content}" for entry in entries)

    def clear(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def size(self, session_id: str) -> int:
        return len(self._sessions.get(session_id, deque()))


def classify_error(error_text: str) -> ErrorType:
    lowered = error_text.lower()
    if any(token in lowered for token in ("timeout", "rate limit", "429", "tempor", "transient", "network", "connection", "unavailable", "overloaded", "reset")):
        return "transient"
    if any(token in lowered for token in ("invalid", "schema", "unsupported", "not found", "missing api key", "forbidden", "unauthorized", "400")):
        return "permanent"
    return "system"
