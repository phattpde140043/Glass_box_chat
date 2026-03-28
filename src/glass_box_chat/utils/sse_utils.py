import json
from typing import Any


def sse_event(event: str, payload: dict[str, Any]) -> dict[str, str]:
    return {
        "event": event,
        "data": json.dumps(payload),
    }


def sse_done(
    content: str,
    sources: list[str] | None = None,
    source_details: list[dict[str, str]] | None = None,
) -> dict[str, str]:
    payload: dict[str, Any] = {
        "type": "assistant_message",
        "content": content,
    }
    if sources:
        payload["sources"] = sources
    if source_details:
        payload["sourceDetails"] = source_details
    return sse_event("done", payload)


def sse_error(message: str) -> dict[str, str]:
    return sse_event("error", {"error": message})
