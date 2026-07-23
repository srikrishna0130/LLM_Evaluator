import json
import re
from collections import Counter
from difflib import SequenceMatcher
from typing import Protocol

from pydantic import BaseModel, Field

from app.config import Settings
from app.domain import ComparisonScore, ModelResponse
from app.llm import LLM, OpenAILLM


class Scorer(Protocol):
    async def score(
        self,
        prompt: str,
        primary: ModelResponse,
        candidate: ModelResponse,
    ) -> ComparisonScore: ...

    async def close(self) -> None: ...


def lexical_metrics(primary: str, candidate: str) -> dict[str, float | bool]:
    left = " ".join(primary.lower().split())
    right = " ".join(candidate.lower().split())
    left_tokens = re.findall(r"\w+", left)
    right_tokens = re.findall(r"\w+", right)
    shared = sum((Counter(left_tokens) & Counter(right_tokens)).values())

    if not left_tokens and not right_tokens:
        token_overlap = 1.0
    elif not left_tokens or not right_tokens:
        token_overlap = 0.0
    else:
        precision = shared / len(right_tokens)
        recall = shared / len(left_tokens)
        token_overlap = (
            2 * precision * recall / (precision + recall)
            if precision + recall
            else 0.0
        )

    longest = max(len(left), len(right))
    return {
        "exact_match": left == right,
        "text_similarity": SequenceMatcher(None, left, right).ratio(),
        "token_overlap": token_overlap,
        "length_ratio": min(len(left), len(right)) / longest if longest else 1.0,
    }


class HeuristicScorer:
    async def score(
        self,
        prompt: str,
        primary: ModelResponse,
        candidate: ModelResponse,
    ) -> ComparisonScore:
        metrics = lexical_metrics(primary.text, candidate.text)
        value = 100 * (
            0.55 * metrics["text_similarity"]
            + 0.35 * metrics["token_overlap"]
            + 0.10 * metrics["length_ratio"]
        )
        return ComparisonScore(
            score=round(value, 2),
            scorer="heuristic-v1",
            reason="Lexical similarity to the primary response.",
            **metrics,
        )

    async def close(self) -> None:
        return None


class _JudgeOutput(BaseModel):
    score: float = Field(ge=0, le=100)
    reason: str = Field(min_length=1, max_length=1000)


class LLMJudgeScorer:
    def __init__(self, judge: LLM, max_chars: int) -> None:
        self._judge = judge
        self._max_chars = max_chars

    async def score(
        self,
        prompt: str,
        primary: ModelResponse,
        candidate: ModelResponse,
    ) -> ComparisonScore:
        judge_prompt = (
            "User prompt:\n"
            f"{prompt[:self._max_chars]}\n\n"
            "Reference response:\n"
            f"{primary.text[:self._max_chars]}\n\n"
            "Candidate response:\n"
            f"{candidate.text[:self._max_chars]}\n\n"
            'Return JSON only: {"score": 0-100, "reason": "short reason"}.'
        )
        output = await self._judge.generate(
            judge_prompt,
            system=(
                "You are a strict response evaluator. Score correctness, "
                "relevance, and completeness against the reference."
            ),
            temperature=0,
        )
        parsed = self._parse_output(output.text)
        metrics = lexical_metrics(primary.text, candidate.text)
        return ComparisonScore(
            score=round(parsed.score, 2),
            scorer=f"llm-judge:{output.model}",
            reason=parsed.reason,
            **metrics,
        )

    async def close(self) -> None:
        await self._judge.close()

    @staticmethod
    def _parse_output(text: str) -> _JudgeOutput:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end < start:
            raise ValueError("Judge did not return a JSON object.")
        return _JudgeOutput.model_validate(json.loads(text[start : end + 1]))


def build_scorer(settings: Settings) -> Scorer:
    if settings.score_backend == "heuristic":
        return HeuristicScorer()
    if not settings.judge_model:
        raise ValueError("JUDGE_MODEL is required when SCORE_BACKEND=llm.")
    judge = OpenAILLM(
        model=settings.judge_model,
        api_key=settings.judge_api_key,
        base_url=settings.judge_base_url,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
    )
    return LLMJudgeScorer(judge, settings.judge_max_chars)
