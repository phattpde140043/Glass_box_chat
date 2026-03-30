"""
Parallel Execution Orchestrator: Determines when to run multiple execution paths in parallel.

Role: Decides when to use hybrid_parallel strategy
      Triggers multi-path execution for uncertainty-driven scenarios
      Coordinates with FusionSkill for result merging

Enhancement over original AmbiguityDetector:
- Not just intent ambiguity
- Also execution strategy risk (hallucination_risk, missing_data_risk)
- Intelligently triggers parallel paths based on confidence gaps

Placement: AFTER MetaReasoningAgent, BEFORE Planner
"""

from dataclasses import dataclass
from typing import Optional, Callable
from pydantic import BaseModel


class ParallelExecutionConfig(BaseModel):
    """Configuration for parallel execution."""
    enable_parallel: bool  # Should we run multiple paths?
    primary_path_skills: list[str]  # Main execution path
    parallel_path_skills: list[str]  # Parallel path
    fusion_skill: str = "FusionSkill"  # Merge results
    merge_strategy: str = "weighted"  # How to merge: weighted | voting | confidence_first
    fusion_confidence: float = 0.5  # Confidence threshold for fusion


class ParallelExecutionOrchestrator:
    """
    Orchestrator for parallel execution paths.
    
    Upgrades AmbiguityDetector to handle:
    1. Intent ambiguity (original)
    2. Execution strategy uncertainty (new)
    
    Example scenarios:
    - High hallucination risk → Run (reasoning + research) in parallel
    - High missing_data risk → Run (direct + research) in parallel
    - Multiple valid execution strategies → Run all, merge results
    """
    
    def __init__(self, call_model: Optional[Callable] = None):
        """
        Args:
            call_model: Optional LLM for advanced reasoning about parallel paths
        """
        self._call_model = call_model
    
    def should_enable_parallel_execution(
        self,
        meta_reasoning: dict,  # From MetaReasoningAgent {strategy, risk, confidence, ...}
        analysis: dict,  # From InputAnalyzer
        confidence_threshold: float = 0.6,
    ) -> ParallelExecutionConfig:
        """
        Decide if parallel execution should be enabled.
        
        Args:
            meta_reasoning: From MetaReasoningAgent result
            analysis: From InputAnalyzer
            confidence_threshold: If strategy_confidence < threshold, consider parallel
        
        Returns:
            ParallelExecutionConfig with paths to execute
        """
        
        strategy = meta_reasoning.get("strategy", "direct")  # From MetaReasoningAgent
        strategy_confidence = meta_reasoning.get("confidence", 0.5)
        risk = meta_reasoning.get("risk", {})
        
        # Unpack risk scores
        hallucination_risk = risk.get("hallucination", 0.0)
        missing_data_risk = risk.get("missing_data", 0.0)
        weak_reasoning_risk = risk.get("weak_reasoning", 0.0)
        
        # Decision logic for parallel execution
        
        # Case 1: Strategy Low Confidence → Run alternatives in parallel
        if strategy_confidence < confidence_threshold:
            return self._build_parallel_config_low_confidence(
                strategy, hallucination_risk, missing_data_risk
            )
        
        # Case 2: High Hallucination Risk → Research validates reasoning
        if hallucination_risk > 0.6:
            return self._build_parallel_config_hallucination_risk()
        
        # Case 3: High Missing Data Risk → Combine direct answer with research
        if missing_data_risk > 0.6:
            return self._build_parallel_config_missing_data_risk()
        
        # Case 4: Intent ambiguity (original case)
        intent_candidates = analysis.get("intent_candidates", [])
        if len(intent_candidates) > 1:
            candidate_confidences = [c.get("confidence", 0.0) for c in intent_candidates]
            confidence_gap = max(candidate_confidences) - (min(candidate_confidences) if len(candidate_confidences) > 1 else 0)
            
            # Close confidence gap → multiple valid intents
            if confidence_gap < 0.2 and len(intent_candidates) >= 2:
                return self._build_parallel_config_intent_ambiguity(intent_candidates)
        
        # Default: No parallel execution needed
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
        """Build config when strategy confidence is low."""
        
        if missing_data_risk > hallucination_risk:
            # Risk is missing data → run (direct + research)
            return ParallelExecutionConfig(
                enable_parallel=True,
                primary_path_skills=["GeneralAnswerSkill"],  # Reasoning
                parallel_path_skills=["ResearchSkill"],  # External data
                merge_strategy="weighted",
            )
        else:
            # Risk is hallucination → researched answer is more trustworthy
            return ParallelExecutionConfig(
                enable_parallel=True,
                primary_path_skills=["ResearchSkill"],  # Verified data
                parallel_path_skills=["GeneralAnswerSkill"],  # Cross-reference
                merge_strategy="confidence_first",
            )
    
    def _build_parallel_config_hallucination_risk(self) -> ParallelExecutionConfig:
        """Build config for high hallucination risk."""
        return ParallelExecutionConfig(
            enable_parallel=True,
            primary_path_skills=["ResearchSkill"],  # External verification
            parallel_path_skills=["GeneralAnswerSkill"],  # LLM reasoning
            merge_strategy="weighted",
            fusion_confidence=0.8,  # Require high confidence to merge
        )
    
    def _build_parallel_config_missing_data_risk(self) -> ParallelExecutionConfig:
        """Build config for high missing data risk."""
        return ParallelExecutionConfig(
            enable_parallel=True,
            primary_path_skills=["GeneralAnswerSkill"],  # Start with reasoning
            parallel_path_skills=["ResearchSkill"],  # Supplement with data
            merge_strategy="weighted",
        )
    
    def _build_parallel_config_intent_ambiguity(
        self,
        intent_candidates: list[dict],
    ) -> ParallelExecutionConfig:
        """Build config for ambiguous intents."""
        
        # For each candidate, determine which skill to route to
        intents = [c.get("intent", "") for c in intent_candidates[:2]]
        
        primary_intent = intents[0] if intents else "analysis"
        parallel_intent = intents[1] if len(intents) > 1 else None
        
        primary_skills = self._get_skills_for_intent(primary_intent)
        parallel_skills = self._get_skills_for_intent(parallel_intent) if parallel_intent else []
        
        return ParallelExecutionConfig(
            enable_parallel=True,
            primary_path_skills=primary_skills,
            parallel_path_skills=parallel_skills,
            merge_strategy="voting",  # FusionSkill votes on best answer
        )
    
    def _get_primary_skills(self, strategy: str) -> list[str]:
        """Get primary skills for given strategy."""
        if strategy == "direct":
            return ["GeneralAnswerSkill"]
        elif strategy == "research_first":
            return ["ResearchSkill"]
        else:  # hybrid_parallel
            return ["GeneralAnswerSkill", "ResearchSkill"]
    
    def _get_skills_for_intent(self, intent: str) -> list[str]:
        """Route intent to appropriate skills."""
        intent_lower = intent.lower()
        
        if "market_price" in intent_lower or "finance" in intent_lower:
            return ["FinanceSkill"]
        elif "research" in intent_lower or "search" in intent_lower:
            return ["ResearchSkill"]
        elif "compare" in intent_lower or "difference" in intent_lower:
            return ["CompareSkill"]
        elif "code" in intent_lower or "example" in intent_lower:
            return ["CodeExampleSkill"]
        elif "plan" in intent_lower or "decompose" in intent_lower:
            return ["PlanningSkill"]
        elif "analysis" in intent_lower:
            return ["AnalysisSkill"]
        else:
            return ["GeneralAnswerSkill"]
    
    def convert_to_parallel_dag(
        self,
        config: ParallelExecutionConfig,
        single_path_dag: list[dict],  # Original DAG from Planner
    ) -> list[dict]:
        """
        Convert single-path DAG to parallel execution DAG.
        
        Example:
        Input (single path):
            [node1(skill=ResearchSkill), node2(skill=SynthesizerSkill)]
        
        Output (parallel):
            [
                node1(skill=ResearchSkill),              # Path A
                node1_parallel(skill=GeneralAnswerSkill), # Path B (same input)
                node2(skill=FusionSkill, depends_on=[node1, node1_parallel])
            ]
        
        Args:
            config: ParallelExecutionConfig with paths
            single_path_dag: Original DAG nodes
        
        Returns:
            Modified DAG with parallel paths
        """
        
        if not config.enable_parallel:
            return single_path_dag
        
        parallel_dag = []
        parallel_task_ids = []
        
        # For each primary path skill node, add parallel variant
        for node in single_path_dag:
            parallel_dag.append(node)
            
            skill = node.get("skill", "")
            if skill in config.primary_path_skills and config.parallel_path_skills:
                # Create parallel variant node
                parallel_node = {
                    "id": f"{node.get('id', 'task')}_parallel",
                    "skill": config.parallel_path_skills[0],  # Use first parallel skill
                    "input": node.get("input"),  # Same input
                    "depends_on": node.get("depends_on", []),  # Same dependencies
                }
                parallel_dag.append(parallel_node)
                parallel_task_ids.append(parallel_node["id"])
        
        # Add FusionSkill at end if we have parallel paths
        if parallel_task_ids:
            # Find final node
            final_node = parallel_dag[-1]
            final_node_id = final_node.get("id", "final")
            
            # Insert fusion before final synthesis
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
                "depends_on": [final_node_id] + parallel_task_ids,
            }
            
            parallel_dag.append(fusion_node)
        
        return parallel_dag
