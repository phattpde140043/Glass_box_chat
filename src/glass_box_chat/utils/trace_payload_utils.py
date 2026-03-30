import uuid
from typing import Any

from .time_utils import now_hms


def build_trace_payload(
    *,
    event: str,
    detail: str,
    agent: str,
    session_id: str,
    session_label: str,
    message_id: str,
    branch: str = "main",
    mode: str = "sequential",
    metadata: dict[str, Any] | None = None,
    artifact: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a standardized trace payload shared by stream and mock engine flows."""
    payload = {
        "id": f"trace-{uuid.uuid4()}",
        "event": event,
        "detail": detail,
        "agent": agent,
        "branch": branch,
        "mode": mode,
        "createdAt": now_hms(),
        "sessionId": session_id,
        "sessionLabel": session_label,
        "messageId": message_id,
    }
    if metadata is not None:
        payload["metadata"] = metadata
    if artifact is not None:
        payload["artifact"] = artifact
    return payload
