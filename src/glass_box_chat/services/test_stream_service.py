from collections.abc import AsyncIterator

from ..utils.async_utils import sleep_ms
from ..utils.sse_utils import sse_done, sse_event
from ..utils.time_utils import now_hms


class TestStreamService:
    """Responsible for the debug SSE stream endpoint. No external dependencies."""

    async def stream_test(self) -> AsyncIterator[dict[str, str]]:
        for index in range(3):
            yield sse_event(
                "message",
                {
                    "id": f"test-{index}",
                    "event": "thinking",
                    "detail": f"Test event {index}",
                    "agent": "TestAgent",
                    "branch": "main",
                    "mode": "sequential",
                    "createdAt": now_hms(),
                    "sessionId": "test-session",
                    "sessionLabel": "Test",
                },
            )
            await sleep_ms(200)

        yield sse_done("Test completed!")
