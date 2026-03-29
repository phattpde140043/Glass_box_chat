from pydantic import BaseModel, Field, field_validator

from .chat_contract import (
    CHAT_PROMPT_MAX_LENGTH,
    CHAT_PROMPT_MIN_LENGTH,
    TRACE_BRANCHES,
    TRACE_EVENT_TYPES,
    TRACE_MODES,
)


class RunRequest(BaseModel):
    prompt: str = Field(min_length=CHAT_PROMPT_MIN_LENGTH, max_length=CHAT_PROMPT_MAX_LENGTH)
    sessionId: str = Field(min_length=1)
    messageId: str = Field(min_length=1)

    @field_validator("prompt")
    @classmethod
    def validate_prompt(cls, value: str) -> str:
        trimmed = value.strip()
        if len(trimmed) < CHAT_PROMPT_MIN_LENGTH:
            raise ValueError("prompt cannot be empty")
        return trimmed

    @field_validator("sessionId")
    @classmethod
    def validate_session_id(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("sessionId cannot be empty")
        return trimmed

    @field_validator("messageId")
    @classmethod
    def validate_message_id(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("messageId cannot be empty")
        return trimmed


class ResumeRequest(BaseModel):
    agent_id: str
    answer: str


class TraceEvent(BaseModel):
    id: str
    event: str
    detail: str
    agent: str
    branch: str
    mode: str
    createdAt: str
    sessionId: str
    sessionLabel: str
    messageId: str

    @field_validator("event")
    @classmethod
    def validate_event(cls, value: str) -> str:
        if value not in TRACE_EVENT_TYPES:
            raise ValueError(f"Unsupported event type: {value}")
        return value

    @field_validator("branch")
    @classmethod
    def validate_branch(cls, value: str) -> str:
        if value not in TRACE_BRANCHES:
            raise ValueError(f"Unsupported branch: {value}")
        return value

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, value: str) -> str:
        if value not in TRACE_MODES:
            raise ValueError(f"Unsupported mode: {value}")
        return value
