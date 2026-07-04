"""Build mock-vs-candidate comparison payloads for finished sessions."""

import difflib

from app.schemas.evaluation import ComparisonMetrics, EvaluationComparison
from app.schemas.session import EvaluationSession


def build_text_diff(mock_text: str, candidate_text: str) -> str | None:
    """Return a git-style unified diff when texts differ, else ``None``."""
    if mock_text == candidate_text:
        return None

    diff_lines = difflib.unified_diff(
        mock_text.splitlines(),
        candidate_text.splitlines(),
        fromfile="mock",
        tofile="candidate",
        lineterm="",
    )
    return "\n".join(diff_lines)


def build_comparison(session: EvaluationSession) -> EvaluationComparison:
    """Compare mock and candidate outputs for a completed session."""
    if session.candidate is None:
        raise ValueError("session.candidate is required for comparison")

    mock_text = session.mock.text
    candidate_text = session.candidate.text
    usage = session.candidate.usage
    text_match = mock_text == candidate_text

    return EvaluationComparison(
        session_id=session.session_id,
        prompt=session.prompt,
        mock=session.mock,
        candidate=session.candidate,
        comparison=ComparisonMetrics(
            text_match=text_match,
            mock_length=len(mock_text),
            candidate_length=len(candidate_text),
            latency_ms=session.candidate.latency_ms,
            prompt_tokens=usage.prompt_tokens if usage else None,
            completion_tokens=usage.completion_tokens if usage else None,
            total_tokens=usage.total_tokens if usage else None,
            text_diff=build_text_diff(mock_text, candidate_text),
        ),
    )
