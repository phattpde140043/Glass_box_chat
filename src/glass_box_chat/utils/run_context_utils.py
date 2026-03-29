import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class RunContext:
    session_id: str
    session_label: str
    message_id: str
    root_task_id: str


def build_run_context(next_session_index: int | None = None, session_id: str | None = None, message_id: str | None = None) -> RunContext:
    if not message_id:
        raise ValueError("message_id is required")

    if session_id is not None:
        return RunContext(
            session_id=session_id,
            session_label=f"Session {session_id[-8:]}",
            message_id=message_id,
            root_task_id=f"task-{uuid.uuid4()}",
        )
    if next_session_index is not None:
        return RunContext(
            session_id=f"session-{uuid.uuid4()}",
            session_label=f"Question {next_session_index}",
            message_id=message_id,
            root_task_id=f"task-{uuid.uuid4()}",
        )

    raise ValueError("Must provide either next_session_index or session_id")
