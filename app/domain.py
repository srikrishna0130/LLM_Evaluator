from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, field_validator


class EvaluationStatus(str, Enum):
    QUEUED = "queued"
    SHADOW_RUNNING = "shadow_running"
    SCORE_QUEUED = "score_queued"
    SCORING = "scoring"
    COMPLETE = "complete"
    FAILED = "failed"


class JobKind(str, Enum):
    SHADOW = "shadow"
    SCORE = "score"


class TokenUsage(BaseModel):
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)


class ModelResponse(BaseModel):
    text: str
    model: str
    latency_ms: float = Field(ge=0)
    usage: TokenUsage | None = None


class ComparisonScore(BaseModel):
    score: float = Field(ge=0, le=100)
    scorer: str
    exact_match: bool
    text_similarity: float = Field(ge=0, le=1)
    token_overlap: float = Field(ge=0, le=1)
    length_ratio: float = Field(ge=0, le=1)
    reason: str | None = None


class Evaluation(BaseModel):
    id: str
    prompt: str
    primary: ModelResponse
    candidate: ModelResponse | None
    comparison: ComparisonScore | None
    status: EvaluationStatus
    error_stage: str | None
    error: str | None
    created_at: datetime
    updated_at: datetime


class EvaluateRequest(BaseModel):
    prompt: str = Field(min_length=1)

    @field_validator("prompt")
    @classmethod
    def reject_blank_prompt(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Prompt must contain non-whitespace characters.")
        return value


class EvaluateResponse(BaseModel):
    response: str
    model: str
    sampled: bool
    evaluation_id: str | None = None


class EvaluationStats(BaseModel):
    total: int
    completed: int
    failed: int
    average_score: float | None


class QueueJob(BaseModel):
    kind: JobKind
    evaluation_id: str
