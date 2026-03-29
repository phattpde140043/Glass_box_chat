import asyncio
from collections.abc import AsyncIterator
from typing import Any

from ..models.chat_models import TraceEvent
from ..utils.async_utils import sleep_ms
from ..utils.trace_payload_utils import build_trace_payload
from .trace_engine_protocol import TraceEngineProtocol


class MockTraceEngine(TraceEngineProtocol):
    """
    Responsible for generating a simulated agent trace pipeline.
    Pure logic – no repository calls, no side effects.
    """

    def _extract_issues(self, prompt: str) -> list[str]:
        keywords = ["cải thiện", "vấn đề", "tối ưu", "lỗi", "nguy hiểm", "minh họa"]
        issues: list[str] = []
        words = prompt.lower().split()

        for index, word in enumerate(words):
            for keyword in keywords:
                if keyword in word:
                    issue = " ".join(words[index : min(index + 3, len(words))])
                    if issue not in issues:
                        issues.append(issue)

        if not issues:
            issues = ["tổng quát"] * min(len(prompt.split()) // 5 + 1, 3)

        return issues[:3]

    async def _simulate_branch(
        self,
        issue: str,
        branch: str,
        mode: str,
        session_id: str,
        session_label: str,
        message_id: str,
    ) -> list[TraceEvent]:
        events: list[TraceEvent] = []

        events.append(
            TraceEvent(
                **build_trace_payload(
                    event="tool_call",
                    detail=f"Gọi AgentAnalyzer cho vấn đề {branch}: {issue}. Dự kiến bóc tách ý 1, ý 2, ý 3.",
                    agent="AgentAnalyzer",
                    branch=branch,
                    mode=mode,
                    session_id=session_id,
                    session_label=session_label,
                    message_id=message_id,
                )
            )
        )
        await sleep_ms(220 if mode == "parallel" else 380)

        events.append(
            TraceEvent(
                **build_trace_payload(
                    event="tool_result",
                    detail=f"AgentAnalyzer({branch}) trả về: ý 1 là khái niệm cốt lõi, ý 2 là phạm vi áp dụng, ý 3 là rủi ro cần kiểm soát.",
                    agent="AgentAnalyzer",
                    branch=branch,
                    mode=mode,
                    session_id=session_id,
                    session_label=session_label,
                    message_id=message_id,
                )
            )
        )
        await sleep_ms(220 if mode == "parallel" else 380)

        events.append(
            TraceEvent(
                **build_trace_payload(
                    event="tool_call",
                    detail=f"Tiếp tục gọi SearchWebAgent để xác minh thông tin cho vấn đề {branch}. Đang searching các nguồn liên quan...",
                    agent="SearchWebAgent",
                    branch=branch,
                    mode=mode,
                    session_id=session_id,
                    session_label=session_label,
                    message_id=message_id,
                )
            )
        )
        await sleep_ms(260 if mode == "parallel" else 420)

        events.append(
            TraceEvent(
                **build_trace_payload(
                    event="tool_result",
                    detail=f"SearchWebAgent({branch}) tìm được 3 ý chính và 2 ví dụ thực tế để hỗ trợ phần tổng hợp cuối cùng.",
                    agent="SearchWebAgent",
                    branch=branch,
                    mode=mode,
                    session_id=session_id,
                    session_label=session_label,
                    message_id=message_id,
                )
            )
        )

        return events

    async def stream(self, prompt: str, session_id: str, session_label: str, message_id: str) -> AsyncIterator[TraceEvent]:
        issues = self._extract_issues(prompt)
        mode = "parallel" if len(issues) >= 3 else "sequential"

        yield TraceEvent(
            **build_trace_payload(
                event="thinking",
                detail=f"Tôi đang phân tích câu hỏi của bạn. Người dùng đang hỏi {len(issues)} vấn đề: {' | '.join(issues)}. Ưu tiên làm rõ vấn đề đầu tiên trước.",
                agent="CoordinatorAgent",
                mode=mode,
                session_id=session_id,
                session_label=session_label,
                message_id=message_id,
            )
        )
        await sleep_ms(260)

        yield TraceEvent(
            **build_trace_payload(
                event="thinking",
                detail=f"Kế hoạch xử lý: {'chạy song song A/B/C nếu tài nguyên cho phép' if mode == 'parallel' else 'xử lý tuần tự từng vấn đề'}.",
                agent="CoordinatorAgent",
                mode=mode,
                session_id=session_id,
                session_label=session_label,
                message_id=message_id,
            )
        )

        branch_labels = ["A", "B", "C"]
        branch_coroutines = [
            self._simulate_branch(issue, branch_labels[index], mode, session_id, session_label, message_id)
            for index, issue in enumerate(issues)
        ]

        if mode == "parallel":
            results = await asyncio.gather(*branch_coroutines)
            for result in results:
                for event in result:
                    yield event
        else:
            for coro in branch_coroutines:
                for event in await coro:
                    yield event

        yield TraceEvent(
            **build_trace_payload(
                event="waiting",
                detail="Đang đợi AgentSummarizer tổng hợp tất cả kết quả từ các nhánh vấn đề.",
                agent="AgentSummarizer",
                mode=mode,
                session_id=session_id,
                session_label=session_label,
                message_id=message_id,
            )
        )
        await sleep_ms(260)

        yield TraceEvent(
            **build_trace_payload(
                event="done",
                detail="Đã hoàn tất vòng phân tích mock. Sẵn sàng gửi kết quả tổng hợp về khung chat.",
                agent="CoordinatorAgent",
                mode=mode,
                session_id=session_id,
                session_label=session_label,
                message_id=message_id,
            )
        )

    async def run(self, prompt: str, session_id: str, session_label: str, message_id: str) -> list[TraceEvent]:
        return [event async for event in self.stream(prompt, session_id, session_label, message_id)]

    def build_final_answer(self, prompt: str) -> str:
        final_answers = {
            "cải thiện": "Cải thiện được thực hiện qua việc tối ưu hóa các quy trình hiện tại, áp dụng công nghệ mới, và đánh giá lại các rủi ro tiềm ẩn.",
            "tối ưu": "Tối ưu hóa cần xem xét chi phí-lợi ích, thời gian thực hiện, và tác động dài hạn trên toàn hệ thống.",
            "lỗi": "Lỗi được phát hiện thông qua kiểm tra đa lớp, từ unit test đến integration test, kèm theo phân tích root cause chi tiết.",
            "nguy hiểm": "Nguy hiểm tiềm ẩn nên được kiểm soát bằng các biện pháp phòng chống proactive, bao gồm giám sát liên tục.",
            "tổng quát": "Câu hỏi của bạn đã được phân tích kỹ lưỡng qua các bước: phân tích, xác minh thông tin, và tổng hợp kết quả.",
        }

        answer = final_answers["tổng quát"]
        for key, value in final_answers.items():
            if key in prompt.lower():
                answer = value
                break

        return answer

    def build_final_payload(self, prompt: str) -> dict[str, Any]:
        return {
            "type": "assistant_message",
            "content": self.build_final_answer(prompt),
        }
