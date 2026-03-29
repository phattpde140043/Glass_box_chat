"""
Parallel Execution Orchestrator: Determines when to run multiple execution paths in parallel.
"""

from typing import Callable, Optional

from pydantic import BaseModel


class ParallelExecutionConfig(BaseModel):
    enable_parallel: bool
    primary_path_skills: list[str]
    parallel_path_skills: list[str]
    fusion_skill: str = "FusionSkill"
    merge_strategy: str = "weighted"
    fusion_confidence: float = 0.5


class ParallelExecutionOrchestrator:
    def __init__(self, call_model: Optional[Callable] = None):
        self._call_model = call_model

    def should_enable_parallel_execution(
        self,
        meta_reasoning: dict,
        analysis: dict,
        confidence_threshold: float = 0.6,
    ) -> ParallelExecutionConfig:
        strategy = meta_reasoning.get("strategy", "direct")
        strategy_confidence = meta_reasoning.get("confidence", 0.5)
        risk = meta_reasoning.get("risk", {})

        hallucination_risk = risk.get("hallucination", 0.0)
        missing_data_risk = risk.get("missing_data", 0.0)

        if strategy_confidence < confidence_threshold:
            return self._build_parallel_config_low_confidence(strategy, hallucination_risk, missing_data_risk)
        if hallucination_risk > 0.6:
            return self._build_parallel_config_hallucination_risk()
        if missing_data_risk > 0.6:
            return self._build_parallel_config_missing_data_risk()

        intent_candidates = analysis.get("intent_candidates", [])
        if len(intent_candidates) > 1:
            candidate_confidences = [candidate.get("confidence", 0.0) for candidate in intent_candidates]
            confidence_gap = max(candidate_confidences) - (min(candidate_confidences) if len(candidate_confidences) > 1 else 0)
            if confidence_gap < 0.2 and len(intent_candidates) >= 2:
                return self._build_parallel_config_intent_ambiguity(intent_candidates)

        return ParallelExecutionConfig(
            enable_parallel=False,
            primary_path_skills=self._get_primary_skills(strategy),
            parallel_path_skills=[],
        )

    def _build_parallel_config_low_confidence(
        self,
        strategy: str,
        hallucination_risk: float,
        missing_data_risk: float,
    ) -> ParallelExecutionConfig:
        if missing_data_risk > hallucination_risk:
            return ParallelExecutionConfig(
                enable_parallel=True,
                primary_path_skills=["GeneralAnswerSkill"],
                parallel_path_skills=["ResearchSkill"],
                merge_strategy="weighted",
            )

        return ParallelExecutionConfig(
            enable_parallel=True,
            primary_path_skills=["ResearchSkill"],
            parallel_path_skills=["GeneralAnswerSkill"],
            merge_strategy="confidence_first",
        )

    def _build_parallel_config_hallucination_risk(self) -> ParallelExecutionConfig:
        return ParallelExecutionConfig(
            enable_parallel=True,
            primary_path_skills=["ResearchSkill"],
            parallel_path_skills=["GeneralAnswerSkill"],
            merge_strategy="weighted",
            fusion_confidence=0.8,
        )

    def _build_parallel_config_missing_data_risk(self) -> ParallelExecutionConfig:
        return ParallelExecutionConfig(
            enable_parallel=True,
            primary_path_skills=["GeneralAnswerSkill"],
            parallel_path_skills=["ResearchSkill"],
            merge_strategy="weighted",
        )

    def _build_parallel_config_intent_ambiguity(self, intent_candidates: list[dict]) -> ParallelExecutionConfig:
        intents = [candidate.get("intent", "") for candidate in intent_candidates[:2]]
        primary_intent = intents[0] if intents else "analysis"
        parallel_intent = intents[1] if len(intents) > 1 else None

        primary_skills = self._get_skills_for_intent(primary_intent)
        parallel_skills = self._get_skills_for_intent(parallel_intent) if parallel_intent else []

        return ParallelExecutionConfig(
            enable_parallel=True,
            primary_path_skills=primary_skills,
            parallel_path_skills=parallel_skills,
            merge_strategy="voting",
        )

    def _get_primary_skills(self, strategy: str) -> list[str]:
        if strategy == "direct":
            return ["GeneralAnswerSkill"]
        if strategy == "research_first":
            return ["ResearchSkill"]
        return ["GeneralAnswerSkill", "ResearchSkill"]

    def _get_skills_for_intent(self, intent: str | None) -> list[str]:
        intent_lower = (intent or "").lower()
        if "market_price" in intent_lower or "finance" in intent_lower:
            return ["FinanceSkill"]
        if "research" in intent_lower or "search" in intent_lower:
            return ["ResearchSkill"]
        if "compare" in intent_lower or "difference" in intent_lower:
            return ["CompareSkill"]
        if "code" in intent_lower or "example" in intent_lower:
            return ["CodeExampleSkill"]
        if "plan" in intent_lower or "decompose" in intent_lower:
            return ["PlanningSkill"]
        if "analysis" in intent_lower:
            return ["AnalysisSkill"]
        return ["GeneralAnswerSkill"]

    def convert_to_parallel_dag(
        self,
        config: ParallelExecutionConfig,
        single_path_dag: list[dict],
    ) -> list[dict]:
        if not config.enable_parallel:
            return single_path_dag

        parallel_dag: list[dict] = []
        parallel_task_ids: list[str] = []

        for node in single_path_dag:
            parallel_dag.append(node)
            skill = node.get("skill", "")
            if skill in config.primary_path_skills and config.parallel_path_skills:
                parallel_node = {
                    "id": f"{node.get('id', 'task')}_parallel",
                    "skill": config.parallel_path_skills[0],
                    "input": node.get("input"),
                    "depends_on": node.get("depends_on", []),
                }
                parallel_dag.append(parallel_node)
                parallel_task_ids.append(parallel_node["id"])

        if parallel_task_ids:
            final_node = parallel_dag[-1]
            final_node_id = final_node.get("id", "final")
            fusion_node = {
                "id": "fusion",
                "skill": config.fusion_skill,
                "input": {
                    "paths": [
                        {"name": "primary", "result_key": final_node_id},
                        {"name": "parallel", "result_key": parallel_task_ids[0] if parallel_task_ids else None},
                    ],
                    "merge_strategy": config.merge_strategy,
                },
                "depends_on": [final_node_id, *parallel_task_ids],
            }
            parallel_dag.append(fusion_node)

        return parallel_dag
