from typing import Any

from ..sqlite_db import (
    TASK_STATE_COMPLETED,
    TASK_STATE_FAILED,
    TASK_STATE_QUEUED,
    TASK_STATE_RUNNING,
    TASK_STATE_WAITING,
    append_runtime_event,
    complete_runtime_session,
    complete_runtime_task,
    count_runtime_events_by_session,
    count_runtime_sessions,
    count_runtime_tasks_by_session,
    create_hitl_waiting,
    create_root_task,
    create_runtime_session,
    get_database_path,
    get_task_status,
    get_waiting_task_by_agent,
    list_runtime_events_by_session,
    list_runtime_sessions,
    list_runtime_tasks_by_session,
    resolve_hitl_waiting,
    transition_runtime_task,
)
from .contracts import HealthRepository, HitlRepository, RunRepository, SessionQueryRepository


class RuntimeRepository(HealthRepository, SessionQueryRepository, RunRepository, HitlRepository):
    def get_database_path(self):
        return get_database_path()

    def count_sessions(self) -> int:
        return count_runtime_sessions()

    def create_session(self, session_id: str, label: str) -> None:
        create_runtime_session(session_id=session_id, label=label)

    def create_root_task(self, task_id: str, session_id: str, prompt: str) -> None:
        create_root_task(task_id=task_id, session_id=session_id, prompt=prompt)

    def transition_task(self, task_id: str, target_status: str) -> None:
        transition_runtime_task(task_id=task_id, target_status=target_status)

    def complete_task(self, task_id: str, status: str, last_error: str | None = None) -> None:
        complete_runtime_task(task_id=task_id, status=status, last_error=last_error)

    def get_task_status(self, task_id: str) -> str | None:
        return get_task_status(task_id)

    def complete_session(self, session_id: str, status: str) -> None:
        complete_runtime_session(session_id=session_id, status=status)

    def append_event(
        self,
        event_id: str,
        session_id: str,
        task_id: str | None,
        agent_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        append_runtime_event(
            event_id=event_id,
            session_id=session_id,
            task_id=task_id,
            agent_id=agent_id,
            event_type=event_type,
            payload=payload,
        )

    def create_waiting_task(self, task_id: str, session_id: str, agent_id: str, question: str) -> None:
        create_hitl_waiting(task_id=task_id, session_id=session_id, agent_id=agent_id, question=question)

    def get_waiting_task_by_agent(self, agent_id: str) -> dict[str, str] | None:
        return get_waiting_task_by_agent(agent_id=agent_id)

    def resolve_waiting_task(self, task_id: str, answer: str) -> None:
        resolve_hitl_waiting(task_id=task_id, answer=answer)

    def list_sessions(self, limit: int) -> list[dict[str, str | None]]:
        return list_runtime_sessions(limit=limit)

    def list_tasks_by_session(self, session_id: str) -> list[dict[str, str | int | None]]:
        return list_runtime_tasks_by_session(session_id=session_id)

    def list_events_by_session(self, session_id: str, limit: int, offset: int) -> list[dict[str, str | None]]:
        return list_runtime_events_by_session(session_id=session_id, limit=limit, offset=offset)

    def count_tasks_by_session(self, session_id: str) -> int:
        return count_runtime_tasks_by_session(session_id=session_id)

    def count_events_by_session(self, session_id: str) -> int:
        return count_runtime_events_by_session(session_id=session_id)
