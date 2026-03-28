from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class SkillContext:
    input: dict[str, object]
    normalized_prompt: str
    dependency_outputs: dict[str, Any]
    recent_memory: str = ""
    selected_tool: object | None = None  # Optional tool hint (Tool protocol instance)


@dataclass
class SkillResult:
    success: bool
    data: dict[str, Any] | str | None = None
    error: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass
class SkillMetadata:
    name: str
    description: str
    examples: list[str]
    priority_weight: float = 0.0
    input_schema: dict[str, Any] | None = None


class SkillAgent(Protocol):
    metadata: SkillMetadata

    def can_handle(self, input_data: dict[str, object]) -> bool: ...

    async def execute(self, context: SkillContext) -> SkillResult: ...


@dataclass
class DAGNode:
    id: str
    skill: str
    input: dict[str, object]
    depends_on: list[str]
    branch: str = "main"
    priority: int = 0


@dataclass
class RoutedSkill:
    skill_name: str
    semantic_score: float
    rule_score: float
    priority_weight: float
    used_fallback: bool = False

    @property
    def final_score(self) -> float:
        return self.semantic_score + self.rule_score + self.priority_weight


@dataclass
class ExecutionUpdate:
    node: DAGNode
    result: SkillResult
    skill_name: str


class SkillRegistry:
    def __init__(self) -> None:
        self._skills: dict[str, SkillAgent] = {}

    def register(self, skill: SkillAgent) -> None:
        self._skills[skill.metadata.name] = skill

    def get(self, name: str) -> SkillAgent | None:
        return self._skills.get(name)

    def list_skills(self) -> list[SkillAgent]:
        return list(self._skills.values())

    def get_claude_tools(self) -> list[dict[str, Any]]:
        return [ClaudeToolAdapter.to_tool_schema(skill.metadata) for skill in self.list_skills()]


class ClaudeToolAdapter:
    @staticmethod
    def to_tool_schema(metadata: SkillMetadata) -> dict[str, Any]:
        default_schema: dict[str, Any] = {
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "Task description for this skill.",
                }
            },
            "required": ["description"],
            "additionalProperties": True,
        }
        return {
            "name": metadata.name,
            "description": metadata.description,
            "input_schema": metadata.input_schema or default_schema,
        }
