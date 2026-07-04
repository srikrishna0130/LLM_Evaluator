"""Evaluation session schemas stored by the session store."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from app.schemas.model import ModelGenerationResponse


class CandidateStatus(str, Enum):
    PENDING = "pending"
    OK = "ok"
    FAILED = "failed"


class EvaluationSession(BaseModel):
    """A single shadow-evaluation session (mock + candidate outputs)."""

    session_id: str
    prompt: str
    mock: ModelGenerationResponse
    candidate: ModelGenerationResponse | None = None
    candidate_status: CandidateStatus = CandidateStatus.PENDING
    error: str | None = None
    created_at: datetime
    updated_at: datetime = Field(...)
