import pytest

from app.domain import ModelResponse
from app.llm import MockLLM
from app.scoring import HeuristicScorer, LLMJudgeScorer


@pytest.mark.asyncio
async def test_identical_responses_score_100():
    response = ModelResponse(text="same", model="model", latency_ms=1)

    score = await HeuristicScorer().score("prompt", response, response)

    assert score.score == 100
    assert score.exact_match is True


class _FakeJudge:
    async def generate(
        self, prompt, *, system=None, temperature=None
    ):
        assert temperature == 0
        return ModelResponse(
            text='```json\n{"score": 87, "reason": "Mostly equivalent."}\n```',
            model="judge",
            latency_ms=1,
        )

    async def close(self):
        return None


@pytest.mark.asyncio
async def test_llm_judge_adds_semantic_score_and_lexical_metrics():
    scorer = LLMJudgeScorer(_FakeJudge(), max_chars=1000)
    primary = ModelResponse(
        text="A virtual machine.", model="primary", latency_ms=1
    )
    candidate = ModelResponse(
        text="A cloud VM.", model="candidate", latency_ms=1
    )

    score = await scorer.score("What is it?", primary, candidate)

    assert score.score == 87
    assert score.scorer == "llm-judge:judge"
    assert score.reason == "Mostly equivalent."
    assert 0 <= score.text_similarity <= 1
