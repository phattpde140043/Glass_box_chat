from collections.abc import AsyncIterator

from ..repositories.runtime_repository import (
    TASK_STATE_COMPLETED,
    TASK_STATE_FAILED,
    TASK_STATE_QUEUED,
    TASK_STATE_RUNNING,
    TASK_STATE_WAITING,
)
from ..repositories.contracts import RunRepository
from ..utils.async_utils import sleep_ms
from ..utils.run_context_utils import RunContext, build_run_context
from ..utils.sse_utils import sse_done, sse_error, sse_event
from ..utils.trace_payload_utils import build_trace_payload
from .trace_engine_protocol import AgentRunTraceEngineProtocol


class AgentRunService:
    """
    Responsible for orchestrating a single agent run:
    - creating the session and root task in the repository
    - delegating trace generation to an AgentRunTraceEngineProtocol implementation (DIP)
    - persisting events produced by the engine
    - streaming SSE to the caller
    """

    def __init__(self, repository: RunRepository, trace_engine: AgentRunTraceEngineProtocol) -> None:
        self._repository = repository
        self._trace_engine = trace_engine

    def _persist_trace_event(self, context: RunContext, payload_dict: dict) -> None:
        self._repository.append_event(
            event_id=payload_dict["id"],
            session_id=context.session_id,
            task_id=context.root_task_id,
            agent_id=payload_dict["agent"],
            event_type=payload_dict["event"],
            payload=payload_dict,
        )

    def _complete_success(self, context: RunContext) -> None:
        if self._repository.get_task_status(context.root_task_id) == TASK_STATE_WAITING:
            self._repository.transition_task(task_id=context.root_task_id, target_status=TASK_STATE_RUNNING)

        self._repository.transition_task(task_id=context.root_task_id, target_status=TASK_STATE_COMPLETED)
        self._repository.complete_task(task_id=context.root_task_id, status=TASK_STATE_COMPLETED)
        self._repository.complete_session(session_id=context.session_id, status="done")

    def _complete_failure(self, context: RunContext, error: Exception) -> None:
        try:
            self._repository.transition_task(task_id=context.root_task_id, target_status=TASK_STATE_FAILED)
        except ValueError:
            pass

        self._repository.complete_task(task_id=context.root_task_id, status=TASK_STATE_FAILED, last_error=str(error))
        self._repository.complete_session(session_id=context.session_id, status="failed")

    @staticmethod
    def _normalize_final_payload(final_payload: dict[str, object]) -> tuple[str, list[str] | None, list[dict[str, str]] | None]:
        final_content = str(final_payload.get("content", ""))

        final_sources = final_payload.get("sources")
        if isinstance(final_sources, list):
            normalized_sources = [str(source) for source in final_sources if str(source).strip()]
        else:
            normalized_sources = None

        final_source_details = final_payload.get("sourceDetails")
        normalized_source_details: list[dict[str, str]] | None = None
        if isinstance(final_source_details, list):
            normalized_details: list[dict[str, str]] = []
            for detail in final_source_details:
                if not isinstance(detail, dict):
                    continue
                title = str(detail.get("title", "")).strip()
                url = str(detail.get("url", "")).strip()
                freshness = str(detail.get("freshness", "")).strip()
                if not title or not url:
                    continue
                normalized_details.append(
                    {
                        "title": title,
                        "url": url,
                        "freshness": freshness or "unknown",
                    }
                )
            normalized_source_details = normalized_details or None

        return final_content, normalized_sources, normalized_source_details

    async def stream_run_agent(self, prompt: str, session_id: str | None = None, message_id: str | None = None) -> AsyncIterator[dict[str, str]]:
        if not session_id:
            raise ValueError("session_id is required")
        if not message_id:
            raise ValueError("message_id is required")

        context = build_run_context(session_id=session_id, message_id=message_id)
        self._repository.create_session(session_id=context.session_id, label=context.session_label)
        self._repository.create_root_task(task_id=context.root_task_id, session_id=context.session_id, prompt=prompt)
        self._repository.transition_task(task_id=context.root_task_id, target_status=TASK_STATE_QUEUED)
        self._repository.transition_task(task_id=context.root_task_id, target_status=TASK_STATE_RUNNING)

        try:
            start_payload = build_trace_payload(
                event="agent_start",
                detail="Received a new user message. Starting the runtime trace analysis session.",
                agent="CoordinatorAgent",
                session_id=context.session_id,
                session_label=context.session_label,
                message_id=context.message_id,
            )
            self._persist_trace_event(context, start_payload)
            yield sse_event("message", start_payload)

            await sleep_ms(200)

            async for event in self._trace_engine.stream(prompt, context.session_id, context.session_label, context.message_id):
                event_payload = event.model_dump()
                self._persist_trace_event(context, event_payload)

                if event_payload["event"] == "waiting":
                    self._repository.transition_task(task_id=context.root_task_id, target_status=TASK_STATE_WAITING)
                    self._repository.create_waiting_task(
                        task_id=context.root_task_id,
                        session_id=context.session_id,
                        agent_id=event_payload["agent"],
                        question=event_payload["detail"],
                    )

                yield sse_event("message", event_payload)
                await sleep_ms(100)

            final_payload = self._trace_engine.build_final_payload(prompt)
            final_content, normalized_sources, normalized_source_details = self._normalize_final_payload(final_payload)
            yield sse_done(final_content, normalized_sources, normalized_source_details)
            self._complete_success(context)

        except Exception as error:
            self._complete_failure(context, error)
            yield sse_error(str(error))
