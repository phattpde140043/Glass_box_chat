import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class RunContext:
    session_id: str
    session_label: str
    root_task_id: str


def build_run_context(next_session_index: int) -> RunContext:
    return RunContext(
        session_id=f"session-{uuid.uuid4()}",
        session_label=f"Question {next_session_index}",
        root_task_id=f"task-{uuid.uuid4()}",
    )
