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
    _DISCLAIMER_PREFIXES = (
        "disclaimer:",
        "note:",
        "warning:",
        "additional note:",
    )

    @classmethod
    def _evidence_section_title(cls, analysis: AnalysisResult) -> str:
        _ = analysis
        return "Evidence used:"

    @classmethod
    def _source_label(cls, analysis: AnalysisResult) -> str:
        _ = analysis
        return "Source"

    @classmethod
    def _no_data_message(cls, analysis: AnalysisResult) -> str:
        _ = analysis
        return "I do not have enough verified information to answer that yet."

    @classmethod
    def _runtime_failure_message(cls, analysis: AnalysisResult) -> str:
        _ = analysis
        return (
            "I could not verify that request with the available local evidence. "
            "Please provide more context or try a query that the current data sources can support."
        )

    @classmethod
    def _low_coverage_notice(cls, analysis: AnalysisResult) -> str:
        _ = analysis
        return (
            "Disclaimer: this answer may be incomplete or provisional because the available evidence is limited, "
            "unverified, or conflicting; verify it with independent sources before using it for important decisions."
        )

    @classmethod
    def _conflict_notice(cls, analysis: AnalysisResult) -> str:
        return cls._low_coverage_notice(analysis)

    @classmethod
    def _cross_niche_notice(cls, analysis: AnalysisResult) -> str:
        return cls._low_coverage_notice(analysis)

    @classmethod
    def _looks_like_notice_paragraph(cls, paragraph: str) -> bool:
        normalized = paragraph.strip().lower()
        if not normalized:
            return False
        return any(normalized.startswith(prefix) for prefix in cls._DISCLAIMER_PREFIXES)

    @classmethod
    def _strip_leading_notice_paragraphs(cls, answer: str) -> tuple[str, bool]:
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", answer.strip()) if part.strip()]
        if not paragraphs:
            return answer.strip(), False

        stripped_any = False
        kept: list[str] = []
        skipping = True
        for paragraph in paragraphs:
            if skipping and cls._looks_like_notice_paragraph(paragraph):
                stripped_any = True
                continue
            skipping = False
            kept.append(paragraph)

        return "\n\n".join(kept) if kept else "", stripped_any

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

        if re.search(r"Evidence used\s*:|Sources used\s*:|References\s*:", answer, re.IGNORECASE):
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
        answer, had_existing_notice = self._strip_leading_notice_paragraphs(answer)
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
        
        needs_disclaimer = had_existing_notice or (
            not had_runtime_failure
            and (
                (coverage["coverageRatio"] < 0.5 and coverage["claimCount"] >= 1)
                or conflict["conflictScore"] >= 0.45
                or bool(cross_niche_contradictions)
            )
        )
        if needs_disclaimer:
            answer = f"{self._low_coverage_notice(analysis)}\n\n{answer}"
        
        # Append contradiction summary if present
        if contradiction_summary:
            answer = f"{answer}\n\n{contradiction_summary}"
        
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
