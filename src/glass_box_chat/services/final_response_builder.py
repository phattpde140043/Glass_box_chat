from __future__ import annotations

import re
from typing import Any

from .planner import AnalysisResult
from .result_formatting import (
    compute_claim_evidence_coverage,
    compute_reasoning_conflict_score,
    create_claim_evidence_mapping,
    detect_source_contradictions,
    compute_pairwise_conflict_matrix,
    summarize_contradictions,
    categorize_evidence_by_niche,
    compute_niche_coverage,
    compute_adaptive_weights,
    compute_claim_niche_breakdown,
    detect_cross_niche_contradictions,
    merge_niche_results,
    generate_niche_summary,
    collect_reasoning_evidence_from_results,
    collect_source_details_from_results,
    collect_sources_from_results,
    render_result_for_user,
    sanitize_text_for_plain_ui,
)


class FinalResponseBuilder:
    @staticmethod
    def _is_english_prompt(analysis: AnalysisResult) -> bool:
        prompt = str(analysis.get("normalized_prompt") or analysis.get("original_prompt") or "").strip()
        if not prompt:
            return False

        # Vietnamese uses distinctive Unicode diacritic characters; their presence is definitive
        if re.search(
            r"[àáảãạăắặằẳẵâấậầẩẫèéẻẽẹêếệềểễìíỉĩịòóỏõọôốộồổỗơớợờởỡùúủũụưứựừửữỳýỷỹỵđ]",
            prompt,
            re.IGNORECASE,
        ):
            return False

        # No Unicode diacritics — check for transliterated Vietnamese marker words
        tokens = [t for t in re.split(r"[^a-z']+", prompt.lower()) if t]
        vietnamese_markers = {
            "toi", "ngay", "mai", "du", "bao", "thoi", "tiet", "nhan",
            "dinh", "phan", "tich", "gia", "thi", "truong",
        }
        vietnamese_score = sum(1 for token in tokens if token in vietnamese_markers)
        # No Vietnamese signals at all → treat as English
        return vietnamese_score == 0

    @classmethod
    def _evidence_section_title(cls, analysis: AnalysisResult) -> str:
        return "Evidence used:" if cls._is_english_prompt(analysis) else "Dan chung da su dung:"

    @classmethod
    def _source_label(cls, analysis: AnalysisResult) -> str:
        return "Source" if cls._is_english_prompt(analysis) else "Nguon"

    @classmethod
    def _no_data_message(cls, analysis: AnalysisResult) -> str:
        if cls._is_english_prompt(analysis):
            return "I do not have enough verified information to answer that yet."
        return "Tôi chưa có đủ dữ liệu để trả lời."

    @classmethod
    def _runtime_failure_message(cls, analysis: AnalysisResult) -> str:
        if cls._is_english_prompt(analysis):
            return (
                "I could not verify that request with the available local evidence. "
                "Please provide more context or try a query that the current data sources can support."
            )
        return (
            "Tôi chưa thể xác minh yêu cầu này bằng dữ liệu hiện có trong hệ thống. "
            "Hãy cung cấp thêm ngữ cảnh hoặc thử một truy vấn phù hợp hơn với nguồn dữ liệu hiện tại."
        )

    @classmethod
    def _low_coverage_notice(cls, analysis: AnalysisResult) -> str:
        if cls._is_english_prompt(analysis):
            return (
                "Note: some conclusions in this answer have not yet been fully cross-checked against the collected evidence. "
                "Please verify with independent sources before using it for important decisions."
            )
        return (
            "Luu y: mot so ket luan trong cau tra loi hien chua duoc doi chieu day du voi dan chung da thu thap. "
            "Can xac minh them voi nguon doc lap neu dung cho quyet dinh quan trong."
        )

    @classmethod
    def _conflict_notice(cls, analysis: AnalysisResult) -> str:
        if cls._is_english_prompt(analysis):
            return "Note: the input data shows conflicting signals across sources, so the conclusion is presented cautiously."
        return "Luu y: du lieu dau vao co dau hieu xung dot giua cac nguon, vi vay ket luan duoc trinh bay o muc than trong."

    @classmethod
    def _cross_niche_notice(cls, analysis: AnalysisResult) -> str:
        if cls._is_english_prompt(analysis):
            return (
                "Additional note: there are cross-niche conflicts between quantitative and analytical sources, "
                "so this should be cross-checked before making a decision."
            )
        return (
            "Luu y bo sung: co xung dot cheo giua nguon dinh luong va nguon phan tich, can doi chieu them truoc khi ra quyet dinh."
        )

    @staticmethod
    def _is_error_output(text: str) -> bool:
        normalized = text.strip()
        return normalized.startswith("ERROR:") or normalized.startswith("Error:")

    @staticmethod
    def _append_evidence_section(answer: str, evidence_ledger: list[dict[str, str]], analysis: AnalysisResult) -> str:
        if not evidence_ledger:
            return answer

        section_title = FinalResponseBuilder._evidence_section_title(analysis)
        source_label = FinalResponseBuilder._source_label(analysis)
        lines = [section_title]
        for idx, item in enumerate(evidence_ledger[:6], start=1):
            claim = str(item.get("claim", "")).strip()
            source = str(item.get("source", "")).strip()
            if not source:
                continue
            if claim:
                lines.append(f"- [{idx}] {claim} | {source_label}: {source}")
            else:
                lines.append(f"- [{idx}] {source_label}: {source}")

        if len(lines) == 1:
            return answer

        # Avoid appending if any evidence/source section is already present in the answer.
        # Matches patterns like "Evidence used:", "Dan chung da su dung:", "Dẫn chứng đã sử dụng:".
        if re.search(r"Evidence used\s*:|Sources used\s*:|References\s*:|Dan chung|Dẫn chứng", answer, re.IGNORECASE):
            return answer
        if section_title in answer:
            return answer
        return f"{answer}\n\n" + "\n".join(lines)

    def select_final_answer(self, results: dict[str, Any], analysis: AnalysisResult) -> tuple[str, bool]:
        # Both standard synthesis and ambiguity-fusion pipelines use a dedicated terminal node.
        for terminal_key in ("synthesis", "fusion"):
            if terminal_key in results:
                rendered = render_result_for_user(results[terminal_key])
                if self._is_error_output(rendered):
                    return self._runtime_failure_message(analysis), True
                return rendered, False

        ordered_task_ids = [task["id"] for task in analysis["sub_tasks"]]
        outputs: list[str] = []
        had_runtime_failure = False
        for task_id in ordered_task_ids:
            if task_id not in results:
                continue
            rendered = render_result_for_user(results[task_id])
            if self._is_error_output(rendered):
                had_runtime_failure = True
                continue
            outputs.append(rendered)
        if not outputs:
            if had_runtime_failure:
                return self._runtime_failure_message(analysis), True
            return self._no_data_message(analysis), False
        if len(outputs) == 1:
            return outputs[0], had_runtime_failure
        return "\n\n".join(outputs), had_runtime_failure

    def build_payload_from_results(self, results: dict[str, Any], analysis: AnalysisResult) -> tuple[str, dict[str, Any]]:
        evidence_ledger = collect_reasoning_evidence_from_results(results)
        selected_answer, had_runtime_failure = self.select_final_answer(results, analysis)
        answer = sanitize_text_for_plain_ui(selected_answer)
        answer = self._append_evidence_section(answer, evidence_ledger, analysis)
        coverage = compute_claim_evidence_coverage(answer, evidence_ledger)
        conflict = compute_reasoning_conflict_score(results)
        claim_mapping = create_claim_evidence_mapping(results, answer)
        
        # Detect source contradictions (Phase 7)
        contradictions = detect_source_contradictions(results)
        conflict_matrix = compute_pairwise_conflict_matrix(contradictions)
        contradiction_summary = summarize_contradictions(contradictions)
        
        # Dual-niche analysis (Phase 8)
        evidence_by_niche = categorize_evidence_by_niche(evidence_ledger, results)
        niche_coverage = compute_niche_coverage(answer, evidence_by_niche)
        
        # Get niche source counts for adaptive weighting
        niche_counts = {
            "quantitative": niche_coverage["quantitative"]["sourceCount"],
            "qualitative": niche_coverage["qualitative"]["sourceCount"],
        }
        adaptive_weights = compute_adaptive_weights(answer, niche_counts)

        # Compute merged coverage considering both niches
        merged_coverage = merge_niche_results(coverage["coverageRatio"], coverage["coverageRatio"], adaptive_weights)

        claim_niche_breakdown = compute_claim_niche_breakdown(claim_mapping, evidence_by_niche)
        cross_niche_contradictions = detect_cross_niche_contradictions(contradictions, evidence_by_niche)
        
        niche_summary = generate_niche_summary(niche_coverage)
        
        if evidence_ledger and not had_runtime_failure and coverage["coverageRatio"] < 0.5 and coverage["claimCount"] >= 1:
            answer = f"{self._low_coverage_notice(analysis)}\n\n{answer}"
        if evidence_ledger and not had_runtime_failure and conflict["conflictScore"] >= 0.45:
            answer = f"{self._conflict_notice(analysis)}\n\n{answer}"
        
        # Append contradiction summary if present
        if contradiction_summary:
            answer = f"{answer}\n\n{contradiction_summary}"

        if cross_niche_contradictions:
            answer = f"{answer}\n\n{self._cross_niche_notice(analysis)}"
        
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

        if evidence_ledger:
            payload["evidenceLedger"] = evidence_ledger

        payload["reasoningQuality"] = {
            "claimCount": coverage["claimCount"],
            "coveredClaimCount": coverage["coveredClaimCount"],
            "coverageRatio": coverage["coverageRatio"],
            "uncoveredClaims": coverage["uncoveredClaims"],
            "sourceAnchoredClaimCount": coverage["sourceAnchoredClaimCount"],
            "conflictScore": conflict["conflictScore"],
            "maxConflictCount": conflict["maxConflictCount"],
            "lowQualityAnalysisCount": conflict["lowQualityAnalysisCount"],
            "claimMappingDict": claim_mapping,
            "sourceContradictions": contradictions,
            "conflictMatrix": conflict_matrix,
            "dualNiche": {
                "quantitative": niche_coverage["quantitative"],
                "qualitative": niche_coverage["qualitative"],
                "niche_balance": niche_coverage["niche_balance"],
                "summary": niche_summary,
                "adaptive_weights": adaptive_weights,
                "merged_coverage": merged_coverage,
                "claimLevelNiche": claim_niche_breakdown,
                "crossNicheContradictionCount": len(cross_niche_contradictions),
            },
            "crossNicheContradictions": cross_niche_contradictions,
        }

        return answer, payload
