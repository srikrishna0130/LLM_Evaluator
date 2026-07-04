"""HTTP request/response schemas for the evaluation API."""

from pydantic import BaseModel, Field

from app.schemas.model import ModelGenerationResponse
from app.schemas.session import EvaluationSession


class EvaluateRequest(BaseModel):
    prompt: str = Field(..., min_length=1)


class EvaluateResponse(BaseModel):
    session_id: str
    response: str


class ComparisonMetrics(BaseModel):
    text_match: bool
    mock_length: int
    candidate_length: int
    latency_ms: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    text_diff: str | None = None


class EvaluationComparison(BaseModel):
    session_id: str
    prompt: str
    mock: ModelGenerationResponse
    candidate: ModelGenerationResponse
    comparison: ComparisonMetrics


# Re-export for route response models
__all__ = [
    "EvaluateRequest",
    "EvaluateResponse",
    "EvaluationComparison",
    "ComparisonMetrics",
    "EvaluationSession",
]
