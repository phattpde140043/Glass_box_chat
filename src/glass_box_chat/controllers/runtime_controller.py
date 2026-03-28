import asyncio
import os
import uuid
from typing import Any

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from ..distribution.task_distributor import TaskDistributor
from ..models.chat_models import ResumeRequest, RunRequest
from ..repositories.runtime_repository import RuntimeRepository
from ..services.agent_run_service import AgentRunService
from ..services.orchestrator_skill_agent import OrchestratorSkillAgent
from ..services.health_service import HealthService
from ..services.hitl_service import HitlService
from ..services.session_query_service import SessionQueryService
from ..services.test_stream_service import TestStreamService
from ..services.trace_engine_protocol import TraceEngineProtocol

router = APIRouter()

# Composition root: wire the dependency graph once at module import time.
_repository = RuntimeRepository()
_trace_engine: TraceEngineProtocol = OrchestratorSkillAgent()
_health = HealthService(_repository)
_session_query = SessionQueryService(_repository)
_agent_run = AgentRunService(_repository, _trace_engine)
_hitl = HitlService(_repository)
_test_stream = TestStreamService()
_task_distributor = TaskDistributor()


async def _run_task_handler(_: str, payload: dict[str, Any]) -> None:
    prompt = str(payload["prompt"])
    event_queue: asyncio.Queue[dict[str, str] | None] = payload["event_queue"]

    try:
        async for event in _agent_run.stream_run_agent(prompt):
            await event_queue.put(event)
    finally:
        await event_queue.put(None)


_task_distributor.register_handler("run:", _run_task_handler)


async def start_runtime_workers() -> None:
    configured = os.getenv("TASK_WORKER_COUNT", "1").strip()
    try:
        worker_count = max(1, int(configured))
    except ValueError:
        worker_count = 1

    await _task_distributor.start(worker_count=worker_count)


async def stop_runtime_workers() -> None:
    await _task_distributor.stop()


@router.get("/health")
async def health() -> dict[str, str]:
    return _health.get_health()


@router.get("/sessions")
async def get_sessions(limit: int = 20) -> dict:
    return _session_query.get_sessions(limit=limit)


@router.get("/sessions/{session_id}")
async def get_session_detail(session_id: str, event_limit: int = 200, event_offset: int = 0) -> dict:
    return _session_query.get_session_detail(session_id=session_id, event_limit=event_limit, event_offset=event_offset)


@router.get("/sessions/{session_id}/tasks")
async def get_session_tasks(session_id: str) -> dict:
    return _session_query.get_session_tasks(session_id=session_id)


@router.get("/sessions/{session_id}/events")
async def get_session_events(session_id: str, limit: int = 200, offset: int = 0) -> dict:
    return _session_query.get_session_events(session_id=session_id, limit=limit, offset=offset)


@router.post("/run")
async def run_agent(payload: RunRequest) -> EventSourceResponse:
    task_id = f"run:{uuid.uuid4()}"
    event_queue: asyncio.Queue[dict[str, str] | None] = asyncio.Queue()

    await _task_distributor.enqueue_task(
        task_id,
        {
            "prompt": payload.prompt,
            "event_queue": event_queue,
        },
    )

    async def stream_task_events():
        while True:
            event = await event_queue.get()
            if event is None:
                break

            yield event

    return EventSourceResponse(stream_task_events())


@router.get("/distribution/metrics")
async def get_distribution_metrics() -> dict[str, Any]:
    return _task_distributor.get_metrics()


@router.get("/runtime/metrics")
async def get_runtime_metrics() -> dict[str, Any]:
    return _trace_engine.get_metrics()


@router.post("/resume")
async def resume_agent(payload: ResumeRequest) -> dict[str, str]:
    return _hitl.resume_agent(agent_id=payload.agent_id, answer=payload.answer)


@router.get("/test-stream")
async def test_stream() -> EventSourceResponse:
    return EventSourceResponse(_test_stream.stream_test())
