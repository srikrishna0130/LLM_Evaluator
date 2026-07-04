import pytest

from app.schemas.model import (
    ChatMessage,
    ModelCompletionRequest,
    ModelGenerationResponse,
    TokenUsage,
)
from app.schemas.session import CandidateStatus, EvaluationSession


def test_model_completion_request_from_prompt():
    req = ModelCompletionRequest.from_prompt("openai-gpt-5-mini", "hello")

    assert req.model == "openai-gpt-5-mini"
    assert req.messages == [ChatMessage(role="user", content="hello")]
    assert req.to_openai_kwargs() == {
        "model": "openai-gpt-5-mini",
        "messages": [{"role": "user", "content": "hello"}],
    }


def test_model_generation_response_mock_shape():
    """Mock responses use text + model only."""
    resp = ModelGenerationResponse(text="[mock] echo: hi", model="mock-llm-v0")

    assert resp.usage is None
    assert resp.latency_ms is None


def test_model_generation_response_candidate_shape():
    """Candidate responses include usage and latency."""
    resp = ModelGenerationResponse(
        text="hello",
        model="openai-gpt-5-mini",
        usage=TokenUsage(
            prompt_tokens=1, completion_tokens=2, total_tokens=3
        ),
        latency_ms=42.5,
    )

    assert resp.usage.total_tokens == 3
    assert resp.latency_ms == 42.5


def test_evaluation_session_defaults():
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    session = EvaluationSession(
        session_id="abc",
        prompt="hi",
        mock=ModelGenerationResponse(text="mock", model="mock-llm-v0"),
        created_at=now,
        updated_at=now,
    )

    assert session.candidate is None
    assert session.candidate_status == CandidateStatus.PENDING
    assert session.error is None
