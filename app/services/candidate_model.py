"""Shadow candidate model backed by DigitalOcean Serverless Inference.

Wraps an ``AsyncOpenAI`` client behind a small, mockable async class so the
background shadow task (and tests) can depend on a narrow ``generate`` API
rather than the SDK directly.
"""

import time

from openai import AsyncOpenAI

from app.core.config import settings
from app.services.base import BaseModelClient


class CandidateModelClient(BaseModelClient):
    """Async client for the DO serverless inference candidate model."""

    def __init__(self) -> None:
        self._client = AsyncOpenAI(
            base_url=settings.CANDIDATE_BASE_URL,
            api_key=settings.MODEL_ACCESS_KEY,
            timeout=settings.CANDIDATE_TIMEOUT_S,
            max_retries=settings.CANDIDATE_MAX_RETRIES,
        )

    async def generate(self, prompt: str) -> dict:
        start = time.perf_counter()
        resp = await self._client.chat.completions.create(
            model=settings.CANDIDATE_MODEL,
            messages=[{"role": "user", "content": prompt}],
        )
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        return {
            "text": resp.choices[0].message.content,
            "model": resp.model,
            "usage": resp.usage.model_dump() if resp.usage else None,
            "latency_ms": latency_ms,
        }

    async def aclose(self) -> None:
        """Close the underlying HTTP connection pool (called on shutdown)."""
        await self._client.close()
