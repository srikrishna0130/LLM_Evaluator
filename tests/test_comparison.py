from datetime import datetime, timezone

from app.schemas.model import ModelGenerationResponse, TokenUsage
from app.schemas.session import CandidateStatus, EvaluationSession
from app.services.comparison import build_comparison, build_text_diff


def test_build_text_diff_identical_returns_none():
    assert build_text_diff("same text", "same text") is None


def test_build_text_diff_git_style_unified_diff():
    diff = build_text_diff("line one\nline two", "line one\nline changed")

    assert diff is not None
    assert "--- mock" in diff
    assert "+++ candidate" in diff
    assert "-line two" in diff
    assert "+line changed" in diff


def test_build_text_diff_multiline():
    mock = "alpha\nbeta\ngamma"
    candidate = "alpha\nBETA\ngamma"
    diff = build_text_diff(mock, candidate)

    assert diff is not None
    assert "-beta" in diff
    assert "+BETA" in diff
    assert "alpha" in diff  # unchanged context line


def test_build_comparison_includes_text_diff_when_different():
    now = datetime.now(timezone.utc)
    session = EvaluationSession(
        session_id="abc",
        prompt="hello",
        mock=ModelGenerationResponse(
            text="[mock] echo: hello", model="mock-llm-v0"
        ),
        candidate=ModelGenerationResponse(
            text="real answer",
            model="openai-gpt-5-mini",
            usage=TokenUsage(
                prompt_tokens=3, completion_tokens=7, total_tokens=10
            ),
            latency_ms=250.0,
        ),
        candidate_status=CandidateStatus.OK,
        created_at=now,
        updated_at=now,
    )

    result = build_comparison(session)

    assert result.comparison.text_match is False
    assert result.comparison.text_diff is not None
    assert "--- mock" in result.comparison.text_diff
    assert "+++ candidate" in result.comparison.text_diff
    assert "-[mock] echo: hello" in result.comparison.text_diff
    assert "+real answer" in result.comparison.text_diff
    assert result.comparison.mock_length == len("[mock] echo: hello")
    assert result.comparison.candidate_length == len("real answer")
    assert result.comparison.latency_ms == 250.0
    assert result.comparison.total_tokens == 10


def test_build_comparison_text_diff_none_when_identical():
    now = datetime.now(timezone.utc)
    text = "identical response"
    session = EvaluationSession(
        session_id="abc",
        prompt="hello",
        mock=ModelGenerationResponse(text=text, model="mock-llm-v0"),
        candidate=ModelGenerationResponse(
            text=text,
            model="openai-gpt-5-mini",
            usage=TokenUsage(
                prompt_tokens=1, completion_tokens=1, total_tokens=2
            ),
            latency_ms=50.0,
        ),
        candidate_status=CandidateStatus.OK,
        created_at=now,
        updated_at=now,
    )

    result = build_comparison(session)

    assert result.comparison.text_match is True
    assert result.comparison.text_diff is None
