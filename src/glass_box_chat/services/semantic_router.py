from __future__ import annotations

import math
import re
from typing import Protocol

from .planner import needs_research_text
from .skill_core import RoutedSkill, SkillRegistry


class EmbeddingBackend(Protocol):
    async def embed(self, text: str) -> list[float]: ...


class HashedTokenEmbeddingBackend:
    """Bounded deterministic embedding to avoid unbounded vocabulary growth."""

    def __init__(self, dimension: int = 256) -> None:
        self._dimension = max(32, dimension)

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return [token for token in re.split(r"[^\wÀ-ỹ]+", text.lower()) if token]

    async def embed(self, text: str) -> list[float]:
        vector = [0.0] * self._dimension
        for token in self._tokenize(text):
            index = hash(token) % self._dimension
            vector[index] += 1.0
        return vector


class EmbeddingService:
    def __init__(self, backend: EmbeddingBackend | None = None) -> None:
        self._backend = backend or HashedTokenEmbeddingBackend()

    async def embed(self, text: str) -> list[float]:
        return await self._backend.embed(text)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    size = max(len(a), len(b))
    if len(a) < size:
        a = a + [0.0] * (size - len(a))
    if len(b) < size:
        b = b + [0.0] * (size - len(b))

    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(y * y for y in b))
    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0
    return dot / (mag_a * mag_b)


class SemanticRouter:
    def __init__(
        self,
        registry: SkillRegistry,
        embedding_service: EmbeddingService,
        threshold: float = 0.35,
        fallback_skill_name: str = "general_answer",
    ) -> None:
        self._registry = registry
        self._embedding_service = embedding_service
        self._skill_vectors: dict[str, list[float]] = {}
        self._threshold = threshold
        self._fallback_skill_name = fallback_skill_name

    async def init(self) -> None:
        for skill in self._registry.list_skills():
            text = " ".join([skill.metadata.description, *skill.metadata.examples])
            self._skill_vectors[skill.metadata.name] = await self._embedding_service.embed(text)

    async def route(self, task: dict[str, object]) -> RoutedSkill:
        task_text = str(task.get("description", ""))
        lowered = task_text.lower().strip()

        # Guardrail: only route to synthesizer for explicit synthesis-style tasks.
        synthesis_hints = (
            "synthesize",
            "tong hop",
            "tổng hợp",
            "merge outputs",
            "final answer",
            "ket luan",
            "kết luận",
        )
        explicit_synthesis = any(token in lowered for token in synthesis_hints)

        # Guardrail: lookup/search-style questions should not be sent directly to synthesizer.
        lookup_hints = (
            "lookup",
            "tra cứu",
            "tra cuu",
            "information search",
            "search",
            "find information",
            "tim thong tin",
            "tìm thông tin",
        )
        weather_lookup_hints = (
            "weather",
            "thời tiết",
            "thoi tiet",
            "forecast",
            "dự báo",
            "du bao",
            "nhiệt độ",
            "nhiet do",
            "mưa",
            "mua",
            "ngày mai",
            "ngay mai",
            "tomorrow",
        )
        requires_lookup = (
            needs_research_text(task_text)
            or any(token in lowered for token in lookup_hints)
            or any(token in lowered for token in weather_lookup_hints)
        )

        if requires_lookup and not explicit_synthesis:
            return RoutedSkill(
                skill_name="research",
                semantic_score=0.0,
                rule_score=0.6,
                priority_weight=0.24,
            )

        task_vector = await self._embedding_service.embed(task_text)

        best: RoutedSkill | None = None
        for skill in self._registry.list_skills():
            skill_name = skill.metadata.name
            if skill_name == "synthesizer" and not explicit_synthesis:
                continue
            semantic_score = cosine_similarity(task_vector, self._skill_vectors.get(skill_name, []))
            rule_score = 0.2 if skill.can_handle(task) else 0.0
            candidate = RoutedSkill(
                skill_name=skill_name,
                semantic_score=semantic_score,
                rule_score=rule_score,
                priority_weight=skill.metadata.priority_weight,
            )
            if best is None or candidate.final_score > best.final_score:
                best = candidate

        if best is None:
            raise RuntimeError("No skill available in registry.")

        if best.final_score < self._threshold:
            return RoutedSkill(
                skill_name=self._fallback_skill_name,
                semantic_score=0.0,
                rule_score=0.0,
                priority_weight=0.0,
                used_fallback=True,
            )
        return best
