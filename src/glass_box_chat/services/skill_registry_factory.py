from __future__ import annotations

from collections.abc import Callable

from .search_providers import SearchProvider
from .skill_core import SkillRegistry
from .skills import (
    AnalysisSkill,
    CodeExampleSkill,
    CompareSkill,
    FinanceSkill,
    FusionSkill,
    GeneralAnswerSkill,
    GeoIntentSkill,
    ItineraryPlannerSkill,
    LocalDiscoverySkill,
    PlaceVerificationSkill,
    PlanningSkill,
    ResearchSkill,
    ReviewConsensusSkill,
    SynthesizerSkill,
)

RegistryFactory = Callable[[Callable[[str], str], SearchProvider], SkillRegistry]


def build_default_skill_registry(model_generate: Callable[[str], str], search_provider: SearchProvider) -> SkillRegistry:
    """Build the default skill registry without coupling to Orchestrator concrete type."""
    registry = SkillRegistry()
    registry.register(ResearchSkill(model_generate, search_provider))
    registry.register(GeoIntentSkill())
    registry.register(LocalDiscoverySkill(model_generate, search_provider))
    registry.register(PlaceVerificationSkill())
    registry.register(ReviewConsensusSkill())
    registry.register(ItineraryPlannerSkill(model_generate))
    registry.register(FinanceSkill())
    registry.register(AnalysisSkill(model_generate))
    registry.register(PlanningSkill(model_generate))
    registry.register(CompareSkill(model_generate))
    registry.register(CodeExampleSkill(model_generate))
    registry.register(GeneralAnswerSkill(model_generate))
    registry.register(SynthesizerSkill(model_generate))
    registry.register(FusionSkill(model_generate))
    return registry
