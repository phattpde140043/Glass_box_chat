import uuid

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
) -> dict[str, str]:
    """Build a standardized trace payload shared by stream and mock engine flows."""
    return {
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
