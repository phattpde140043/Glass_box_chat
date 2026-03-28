import uuid

from ..repositories.runtime_repository import (
    TASK_STATE_RUNNING,
)
from ..repositories.contracts import HitlRepository


class HitlService:
    """Responsible for handling Human-in-the-Loop (HITL) resume flows."""

    def __init__(self, repository: HitlRepository) -> None:
        self._repository = repository

    def resume_agent(self, agent_id: str, answer: str) -> dict[str, str]:
        waiting = self._repository.get_waiting_task_by_agent(agent_id=agent_id)
        if not waiting:
            return {
                "message": f"No waiting task found for {agent_id}",
                "status": "not_found",
            }

        task_id = waiting["taskId"]
        session_id = waiting["sessionId"]

        self._repository.resolve_waiting_task(task_id=task_id, answer=answer)
        self._repository.transition_task(task_id=task_id, target_status=TASK_STATE_RUNNING)
        self._repository.append_event(
            event_id=f"trace-{uuid.uuid4()}",
            session_id=session_id,
            task_id=task_id,
            agent_id=agent_id,
            event_type="resume",
            payload={
                "agentId": agent_id,
                "answer": answer,
                "detail": "Received human response and resumed task execution.",
            },
        )

        return {
            "message": f"Resumed {agent_id} with answer: {answer}",
            "status": "resumed",
            "sessionId": session_id,
            "taskId": task_id,
        }
