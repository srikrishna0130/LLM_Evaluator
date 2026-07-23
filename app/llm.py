import time
from typing import Protocol

from openai import AsyncOpenAI

from app.config import Settings
from app.domain import ModelResponse, TokenUsage


class LLM(Protocol):
    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float | None = None,
    ) -> ModelResponse: ...

    async def close(self) -> None: ...


class MockLLM:
    def __init__(self, role: str, model: str) -> None:
        self._role = role
        self._model = model

    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float | None = None,
    ) -> ModelResponse:
        return ModelResponse(
            text=f"[{self._role}] {prompt}",
            model=self._model,
            latency_ms=0,
        )

    async def close(self) -> None:
        return None


class OpenAILLM:
    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str | None,
        timeout: float,
        max_retries: int,
    ) -> None:
        if not api_key:
            raise ValueError(f"An API key is required for model '{model}'.")
        self._model = model
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url or None,
            timeout=timeout,
            max_retries=max_retries,
        )

    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float | None = None,
    ) -> ModelResponse:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        started = time.perf_counter()
        request = {"model": self._model, "messages": messages}
        if temperature is not None:
            request["temperature"] = temperature
        response = await self._client.chat.completions.create(**request)
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        if not response.choices:
            raise RuntimeError(f"Model '{self._model}' returned no choices.")

        usage = response.usage
        return ModelResponse(
            text=response.choices[0].message.content or "",
            model=response.model or self._model,
            latency_ms=latency_ms,
            usage=(
                TokenUsage(
                    prompt_tokens=usage.prompt_tokens,
                    completion_tokens=usage.completion_tokens,
                    total_tokens=usage.total_tokens,
                )
                if usage
                else None
            ),
        )

    async def close(self) -> None:
        await self._client.close()


def build_llm(settings: Settings, role: str) -> LLM:
    if role == "primary":
        provider = settings.primary_provider
        model = settings.primary_model
        api_key = settings.primary_api_key
        base_url = settings.primary_base_url
    elif role == "candidate":
        provider = settings.candidate_provider
        model = settings.candidate_model
        api_key = settings.candidate_api_key
        base_url = settings.candidate_base_url
    else:
        raise ValueError(f"Unknown LLM role '{role}'.")

    if provider == "mock":
        return MockLLM(role, model)
    return OpenAILLM(
        model=model,
        api_key=api_key,
        base_url=base_url,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
    )
