import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from ..utils.sse_utils import sse_error

TaskHandler = Callable[[str, dict[str, Any]], Awaitable[None]]


class TaskDistributor:
    """FIFO task distributor with prefix-based handler routing."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()
        self._handlers: dict[str, TaskHandler] = {}
        self._workers: list[asyncio.Task[None]] = []
        self._is_running = False
        self._configured_worker_count = 0
        self._inflight = 0
        self._enqueued_count = 0
        self._processed_count = 0
        self._failed_count = 0
        self._missing_handler_count = 0

    def register_handler(self, task_prefix: str, handler: TaskHandler) -> None:
        self._handlers[task_prefix] = handler

    async def enqueue_task(self, task_id: str, payload: dict[str, Any]) -> None:
        self._enqueued_count += 1
        await self._queue.put((task_id, payload))

    async def start(self, worker_count: int = 1) -> None:
        if self._is_running:
            return

        self._is_running = True
        self._configured_worker_count = max(1, worker_count)
        self._workers = [asyncio.create_task(self._worker_loop()) for _ in range(self._configured_worker_count)]

    async def stop(self) -> None:
        if not self._is_running:
            return

        self._is_running = False

        for _ in self._workers:
            await self._queue.put(("__stop__", {}))

        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()

    async def _worker_loop(self) -> None:
        while True:
            task_id, payload = await self._queue.get()

            if task_id == "__stop__":
                self._queue.task_done()
                break

            handler = self._resolve_handler(task_id)
            event_queue = payload.get("event_queue")

            if handler is None:
                self._missing_handler_count += 1
                if event_queue is not None:
                    await event_queue.put(sse_error(f"No handler found for task: {task_id}"))
                    await event_queue.put(None)
                self._queue.task_done()
                continue

            self._inflight += 1
            try:
                await handler(task_id, payload)
                self._processed_count += 1
            except Exception as error:
                self._failed_count += 1
                if event_queue is not None:
                    await event_queue.put(sse_error(str(error)))
                    await event_queue.put(None)
            finally:
                self._inflight -= 1
                self._queue.task_done()

    def _resolve_handler(self, task_id: str) -> TaskHandler | None:
        for prefix in sorted(self._handlers.keys(), key=len, reverse=True):
            if task_id.startswith(prefix):
                return self._handlers[prefix]

        return None

    def get_metrics(self) -> dict[str, Any]:
        return {
            "isRunning": self._is_running,
            "configuredWorkers": self._configured_worker_count,
            "activeWorkers": len(self._workers),
            "registeredPrefixes": sorted(self._handlers.keys()),
            "queueDepth": self._queue.qsize(),
            "inflight": self._inflight,
            "enqueued": self._enqueued_count,
            "processed": self._processed_count,
            "failed": self._failed_count,
            "missingHandler": self._missing_handler_count,
        }
