import asyncio

import pytest

from app.core.exceptions import ResourceNotFoundError
from app.schemas.model import ModelGenerationResponse, TokenUsage
from app.schemas.session import CandidateStatus
from app.services.session_store import SessionStore

MOCK = ModelGenerationResponse(text="[mock] echo: hi", model="mock-llm-v0")
CANDIDATE = ModelGenerationResponse(
    text="hello from candidate",
    model="openai-gpt-5-mini",
    usage=TokenUsage(prompt_tokens=1, completion_tokens=2, total_tokens=3),
    latency_ms=42.5,
)


@pytest.mark.asyncio
async def test_create_returns_pending_session():
    store = SessionStore()

    session_id = await store.create("hi", MOCK)
    record = await store.get(session_id)

    assert session_id
    assert record is not None
    assert record.session_id == session_id
    assert record.prompt == "hi"
    assert record.mock == MOCK
    assert record.candidate is None
    assert record.candidate_status == CandidateStatus.PENDING
    assert record.error is None
    assert record.created_at
    assert record.updated_at


@pytest.mark.asyncio
async def test_get_unknown_session_returns_none():
    store = SessionStore()

    assert await store.get("missing-id") is None


@pytest.mark.asyncio
async def test_set_candidate_ok():
    store = SessionStore()
    session_id = await store.create("hi", MOCK)

    await store.set_candidate(session_id, CANDIDATE, status=CandidateStatus.OK)
    record = await store.get(session_id)

    assert record is not None
    assert record.candidate == CANDIDATE
    assert record.candidate_status == CandidateStatus.OK
    assert record.error is None
    assert record.updated_at >= record.created_at


@pytest.mark.asyncio
async def test_set_candidate_failed():
    store = SessionStore()
    session_id = await store.create("hi", MOCK)

    await store.set_candidate(
        session_id, None, status=CandidateStatus.FAILED, error="timeout"
    )
    record = await store.get(session_id)

    assert record is not None
    assert record.candidate is None
    assert record.candidate_status == CandidateStatus.FAILED
    assert record.error == "timeout"


@pytest.mark.asyncio
async def test_set_candidate_unknown_session_raises():
    store = SessionStore()

    with pytest.raises(ResourceNotFoundError):
        await store.set_candidate(
            "missing-id", CANDIDATE, status=CandidateStatus.OK
        )


@pytest.mark.asyncio
async def test_get_returns_copy_not_live_reference():
    store = SessionStore()
    session_id = await store.create("hi", MOCK)

    first = await store.get(session_id)
    assert first is not None
    first.prompt = "mutated"

    second = await store.get(session_id)
    assert second is not None
    assert second.prompt == "hi"


@pytest.mark.asyncio
async def test_list_all_returns_newest_first():
    store = SessionStore()
    first_id = await store.create("first", MOCK)
    await asyncio.sleep(0.01)
    second_id = await store.create("second", MOCK)

    sessions = await store.list_all()

    assert len(sessions) == 2
    assert sessions[0].session_id == second_id
    assert sessions[1].session_id == first_id


@pytest.mark.asyncio
async def test_concurrent_set_candidate():
    """Multiple background tasks can update different sessions safely."""
    store = SessionStore()
    ids = [await store.create(f"prompt-{i}", MOCK) for i in range(5)]

    async def write_candidate(session_id: str, text: str) -> None:
        await store.set_candidate(
            session_id,
            CANDIDATE.model_copy(update={"text": text}),
            status=CandidateStatus.OK,
        )

    await asyncio.gather(
        *(write_candidate(sid, f"answer-{i}") for i, sid in enumerate(ids))
    )

    for i, session_id in enumerate(ids):
        record = await store.get(session_id)
        assert record is not None
        assert record.candidate_status == CandidateStatus.OK
        assert record.candidate is not None
        assert record.candidate.text == f"answer-{i}"
