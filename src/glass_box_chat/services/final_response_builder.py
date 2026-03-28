from __future__ import annotations

from typing import Any

from .planner import AnalysisResult
from .result_formatting import (
    collect_source_details_from_results,
    collect_sources_from_results,
    render_result_for_user,
    sanitize_text_for_plain_ui,
)


class FinalResponseBuilder:
    def select_final_answer(self, results: dict[str, Any], analysis: AnalysisResult) -> str:
        if "synthesis" in results:
            return render_result_for_user(results["synthesis"])

        ordered_task_ids = [task["id"] for task in analysis["sub_tasks"]]
        outputs = [render_result_for_user(results[task_id]) for task_id in ordered_task_ids if task_id in results]
        if not outputs:
            return "Tôi chưa có đủ dữ liệu để trả lời."
        if len(outputs) == 1:
            return outputs[0]
        return "\n\n".join(outputs)

    def build_payload_from_results(self, results: dict[str, Any], analysis: AnalysisResult) -> tuple[str, dict[str, Any]]:
        answer = sanitize_text_for_plain_ui(self.select_final_answer(results, analysis))
        payload: dict[str, Any] = {
            "type": "assistant_message",
            "content": answer,
        }

        sources = collect_sources_from_results(results)
        if sources:
            payload["sources"] = sources

        source_details = collect_source_details_from_results(results)
        if source_details:
            payload["sourceDetails"] = source_details

        return answer, payload
