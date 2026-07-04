"""Schemas for model inference requests and responses.

These normalize the OpenAI-compatible chat-completions call to DigitalOcean
Serverless Inference and the shape returned by both the mock and candidate
model clients.
"""

from typing import Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    """A single message in a chat-completions request."""

    role: Literal["user", "assistant", "system"] = "user"
    content: str = Field(..., min_length=1)


class ModelCompletionRequest(BaseModel):
    """Payload sent to ``POST /v1/chat/completions`` (DO Serverless Inference)."""

    model: str
    messages: list[ChatMessage] = Field(..., min_length=1)

    @classmethod
    def from_prompt(cls, model: str, prompt: str) -> "ModelCompletionRequest":
        return cls(model=model, messages=[ChatMessage(role="user", content=prompt)])

    def to_openai_kwargs(self) -> dict:
        return {
            "model": self.model,
            "messages": [m.model_dump() for m in self.messages],
        }


class TokenUsage(BaseModel):
    """Token counts from the inference provider."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ModelGenerationResponse(BaseModel):
    """Normalized response from any model client (mock or candidate)."""

    text: str
    model: str
    usage: TokenUsage | None = None
    latency_ms: float | None = None
