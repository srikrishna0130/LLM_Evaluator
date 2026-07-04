import logging

import pytest

from app.schemas.model import ModelGenerationResponse, TokenUsage
from app.services.base import BaseModelClient
from app.services.session_store import SessionStore
from app.services.shadow import run_shadow


class _FakeCandidate(BaseModelClient):
    async def generate(self, prompt: str) -> ModelGenerationResponse:
        return ModelGenerationResponse(
            text=f"candidate: {prompt}",
            model="fake",
            usage=TokenUsage(
                prompt_tokens=1, completion_tokens=2, total_tokens=3
            ),
            latency_ms=12.5,
        )


class _FailingCandidate(BaseModelClient):
    async def generate(self, prompt: str) -> ModelGenerationResponse:
        raise RuntimeError("inference down")


@pytest.mark.asyncio
async def test_run_shadow_logs_completion_and_mismatch(caplog):
    store = SessionStore()
    mock = ModelGenerationResponse(text="mock-only", model="mock-llm-v0")
    session_id = await store.create("hi", mock)

    with caplog.at_level(logging.INFO):
        await run_shadow(_FakeCandidate(), store, session_id, "hi")

    assert any("shadow completed" in r.message for r in caplog.records)
    assert any(
        "shadow output mismatch" in r.message for r in caplog.records
    )
    session = await store.get(session_id)
    assert session is not None
    assert session.candidate_status.value == "ok"


@pytest.mark.asyncio
async def test_run_shadow_failure_marks_session_failed(caplog):
    store = SessionStore()
    mock = ModelGenerationResponse(text="mock", model="mock-llm-v0")
    session_id = await store.create("hi", mock)

    with caplog.at_level(logging.ERROR):
        await run_shadow(_FailingCandidate(), store, session_id, "hi")

    assert any("shadow failed" in r.message for r in caplog.records)
    session = await store.get(session_id)
    assert session is not None
    assert session.candidate_status.value == "failed"
    assert session.error == "inference down"
