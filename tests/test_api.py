import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest.mark.asyncio
async def test_dashboard_and_assets_are_served(client):
    dashboard = await client.get("/")
    stylesheet = await client.get("/static/app.css")
    script = await client.get("/static/app.js")

    assert dashboard.status_code == 200
    assert dashboard.headers["content-type"].startswith("text/html")
    assert "<title>LLM Evaluator</title>" in dashboard.text
    assert stylesheet.status_code == 200
    assert "--accent: #245c46" in stylesheet.text
    assert "width: calc(100% - 20px)" in stylesheet.text
    assert script.status_code == 200
    assert 'request("/api/v1/evaluate"' in script.text
    assert "const text = await response.text()" in script.text
    assert "result.hidden = true" in script.text
    assert "Retrying…" in script.text
    assert "pollGeneration" in script.text
    assert "if (response.sampled)" in script.text


@pytest.mark.asyncio
async def test_primary_response_is_returned_and_sampled(client):
    response = await client.post(
        "/api/v1/evaluate", json={"prompt": "hello"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "response": "[primary] hello",
        "model": "primary-mock",
        "sampled": True,
        "evaluation_id": body["evaluation_id"],
    }

    stored = await client.get(
        f"/api/v1/evaluations/{body['evaluation_id']}"
    )
    assert stored.status_code == 200
    assert stored.json()["status"] == "queued"
    assert stored.json()["candidate"] is None


@pytest.mark.asyncio
async def test_unsampled_response_creates_no_evaluation(settings):
    app = create_app(settings.model_copy(update={"sample_rate": 0}))
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/evaluate", json={"prompt": "hello"}
            )
            evaluations = await client.get("/api/v1/evaluations")

    assert response.json()["sampled"] is False
    assert response.json()["evaluation_id"] is None
    assert evaluations.json() == []


@pytest.mark.asyncio
async def test_prompt_limit_is_enforced(settings):
    app = create_app(settings.model_copy(update={"max_prompt_chars": 3}))
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/evaluate", json={"prompt": "long"}
            )

    assert response.status_code == 413


@pytest.mark.asyncio
async def test_blank_prompt_is_rejected(client):
    response = await client.post(
        "/api/v1/evaluate", json={"prompt": "   "}
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_health_metrics_and_missing_evaluation(client):
    health = await client.get("/api/v1/health")
    metrics = await client.get("/api/v1/metrics")
    missing = await client.get("/api/v1/evaluations/missing")

    assert health.json() == {"status": "ok"}
    assert metrics.json() == {
        "total": 0,
        "completed": 0,
        "failed": 0,
        "average_score": None,
    }
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_persistence_failure_never_breaks_primary_response(
    client, test_app, monkeypatch
):
    async def fail_to_persist(prompt, primary):
        raise RuntimeError("database down")

    monkeypatch.setattr(
        test_app.state.runtime.repository, "create", fail_to_persist
    )

    response = await client.post(
        "/api/v1/evaluate", json={"prompt": "hello"}
    )

    assert response.status_code == 200
    assert response.json()["response"] == "[primary] hello"
    assert response.json()["sampled"] is True
    assert response.json()["evaluation_id"] is None
