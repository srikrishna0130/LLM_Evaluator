"""Instant stand-in "production" model.

Returns a canned response with no network I/O so the primary /evaluate call is
effectively instant. This is the baseline the shadow candidate is compared
against. It implements the async ``BaseModelClient`` contract for a uniform
interface, even though it does no real awaiting.
"""

from app.services.base import BaseModelClient


class MockModelClient(BaseModelClient):
    """A trivial, deterministic mock LLM used as the primary response."""

    MODEL_NAME = "mock-llm-v0"

    async def generate(self, prompt: str) -> dict:
        return {"text": f"[mock] echo: {prompt}", "model": self.MODEL_NAME}
