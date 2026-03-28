from ..repositories.contracts import SessionQueryRepository
from ..utils.pagination_utils import clamp_limit, clamp_offset


class SessionQueryService:
    """Responsible for read-only queries on sessions, tasks, and events."""

    def __init__(self, repository: SessionQueryRepository) -> None:
        self._repository = repository

    def get_sessions(self, limit: int = 20) -> dict:
        safe_limit = clamp_limit(limit, 1, 100)
        sessions = self._repository.list_sessions(limit=safe_limit)
        return {
            "items": sessions,
            "count": len(sessions),
            "limit": safe_limit,
        }

    def get_session_detail(self, session_id: str, event_limit: int = 200, event_offset: int = 0) -> dict:
        safe_event_limit = clamp_limit(event_limit, 1, 500)
        safe_event_offset = clamp_offset(event_offset)
        tasks = self._repository.list_tasks_by_session(session_id=session_id)
        events = self._repository.list_events_by_session(
            session_id=session_id,
            limit=safe_event_limit,
            offset=safe_event_offset,
        )
        total_tasks = self._repository.count_tasks_by_session(session_id=session_id)
        total_events = self._repository.count_events_by_session(session_id=session_id)
        return {
            "sessionId": session_id,
            "tasks": tasks,
            "events": events,
            "taskCount": len(tasks),
            "taskTotal": total_tasks,
            "eventCount": len(events),
            "eventTotal": total_events,
            "eventLimit": safe_event_limit,
            "eventOffset": safe_event_offset,
        }

    def get_session_tasks(self, session_id: str) -> dict:
        tasks = self._repository.list_tasks_by_session(session_id=session_id)
        total_tasks = self._repository.count_tasks_by_session(session_id=session_id)
        return {
            "sessionId": session_id,
            "items": tasks,
            "count": len(tasks),
            "total": total_tasks,
        }

    def get_session_events(self, session_id: str, limit: int = 200, offset: int = 0) -> dict:
        safe_limit = clamp_limit(limit, 1, 500)
        safe_offset = clamp_offset(offset)
        events = self._repository.list_events_by_session(
            session_id=session_id,
            limit=safe_limit,
            offset=safe_offset,
        )
        total_events = self._repository.count_events_by_session(session_id=session_id)
        return {
            "sessionId": session_id,
            "items": events,
            "count": len(events),
            "total": total_events,
            "limit": safe_limit,
            "offset": safe_offset,
        }
