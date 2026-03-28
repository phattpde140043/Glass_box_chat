from __future__ import annotations

from collections.abc import Callable

from .search_providers import SearchProvider
from .skill_core import SkillRegistry
from .skills import CodeExampleSkill, CompareSkill, FinanceSkill, GeneralAnswerSkill, PlanningSkill, ResearchSkill, SynthesizerSkill

RegistryFactory = Callable[[Callable[[str], str], SearchProvider], SkillRegistry]


def build_default_skill_registry(model_generate: Callable[[str], str], search_provider: SearchProvider) -> SkillRegistry:
    """Build the default skill registry without coupling to Orchestrator concrete type."""
    registry = SkillRegistry()
    registry.register(ResearchSkill(model_generate, search_provider))
    registry.register(FinanceSkill())
    registry.register(PlanningSkill(model_generate))
    registry.register(CompareSkill(model_generate))
    registry.register(CodeExampleSkill(model_generate))
    registry.register(GeneralAnswerSkill(model_generate))
    registry.register(SynthesizerSkill(model_generate))
    return registry
