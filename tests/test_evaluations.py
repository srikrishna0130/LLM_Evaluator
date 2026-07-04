import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.schemas.model import ModelGenerationResponse, TokenUsage
from app.services.base import BaseModelClient
from app.services.mock_model import MockModelClient
from app.services.session_store import SessionStore


class FakeCandidateModel(BaseModelClient):
    """Test double that never hits the network."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    async def generate(self, prompt: str) -> ModelGenerationResponse:
        if self.fail:
            raise RuntimeError("candidate unavailable")
        return ModelGenerationResponse(
            text=f"candidate answer: {prompt}",
            model="fake-candidate",
            usage=TokenUsage(
                prompt_tokens=5, completion_tokens=10, total_tokens=15
            ),
            latency_ms=100.0,
        )


@pytest.fixture
def evaluation_app():
    app.state.mock_model = MockModelClient()
    app.state.candidate_model = FakeCandidateModel()
    app.state.sessions = SessionStore()
    return app


@pytest.fixture
async def client(evaluation_app):
    transport = ASGITransport(app=evaluation_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_evaluate_returns_mock_immediately(client):
    response = await client.post(
        "/api/v1/evaluate", json={"prompt": "hello"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["response"] == "[mock] echo: hello"
    assert body["session_id"]


@pytest.mark.asyncio
async def test_evaluate_then_get_session_shows_both_outputs(client):
    created = await client.post("/api/v1/evaluate", json={"prompt": "hello"})
    session_id = created.json()["session_id"]

    fetched = await client.get(f"/api/v1/evaluations/{session_id}")

    assert fetched.status_code == 200
    body = fetched.json()
    assert body["prompt"] == "hello"
    assert body["mock"]["text"] == "[mock] echo: hello"
    assert body["candidate"]["text"] == "candidate answer: hello"
    assert body["candidate_status"] == "ok"


@pytest.mark.asyncio
async def test_list_evaluations(client):
    first = await client.post("/api/v1/evaluate", json={"prompt": "one"})
    second = await client.post("/api/v1/evaluate", json={"prompt": "two"})

    response = await client.get("/api/v1/evaluations")

    assert response.status_code == 200
    sessions = response.json()
    assert len(sessions) == 2
    ids = {s["session_id"] for s in sessions}
    assert first.json()["session_id"] in ids
    assert second.json()["session_id"] in ids


@pytest.mark.asyncio
async def test_get_comparison_for_finished_session(client):
    created = await client.post("/api/v1/evaluate", json={"prompt": "hello"})
    session_id = created.json()["session_id"]

    response = await client.get(
        f"/api/v1/evaluations/{session_id}/comparison"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == session_id
    assert body["mock"]["text"] == "[mock] echo: hello"
    assert body["candidate"]["text"] == "candidate answer: hello"
    assert body["comparison"]["text_match"] is False
    assert body["comparison"]["text_diff"] is not None
    assert "--- mock" in body["comparison"]["text_diff"]
    assert "+++ candidate" in body["comparison"]["text_diff"]
    assert body["comparison"]["mock_length"] == len("[mock] echo: hello")
    assert body["comparison"]["candidate_length"] == len("candidate answer: hello")
    assert body["comparison"]["latency_ms"] == 100.0
    assert body["comparison"]["total_tokens"] == 15


@pytest.mark.asyncio
async def test_get_comparison_pending_returns_409(client, evaluation_app):
    session_id = await evaluation_app.state.sessions.create(
        "hello",
        ModelGenerationResponse(text="mock", model="mock-llm-v0"),
    )

    response = await client.get(
        f"/api/v1/evaluations/{session_id}/comparison"
    )

    assert response.status_code == 409
    assert response.json()["detail"]["candidate_status"] == "pending"


@pytest.mark.asyncio
async def test_get_unknown_session_returns_404(client):
    response = await client.get("/api/v1/evaluations/does-not-exist")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_candidate_failure_does_not_break_evaluate(client, evaluation_app):
    evaluation_app.state.candidate_model = FakeCandidateModel(fail=True)

    response = await client.post("/api/v1/evaluate", json={"prompt": "hello"})

    assert response.status_code == 200
    session_id = response.json()["session_id"]

    fetched = await client.get(f"/api/v1/evaluations/{session_id}")
    body = fetched.json()
    assert body["candidate_status"] == "failed"
    assert body["error"] == "candidate unavailable"
    assert body["candidate"] is None
