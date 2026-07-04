import asyncio
import os

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.main import app
from app.services.candidate_model import CandidateModelClient
from app.services.mock_model import MockModelClient
from app.services.session_store import SessionStore

pytestmark = pytest.mark.skipif(
    not settings.MODEL_ACCESS_KEY or os.getenv("RUN_LIVE_INFERENCE") != "1",
    reason=(
        "Live inference test skipped. Set MODEL_ACCESS_KEY in .env and "
        "RUN_LIVE_INFERENCE=1 to run against DO Serverless Inference."
    ),
)


@pytest.mark.asyncio
async def test_live_evaluate_candidate_completes():
    """Optional live test against DigitalOcean Serverless Inference."""
    app.state.mock_model = MockModelClient()
    app.state.candidate_model = CandidateModelClient()
    app.state.sessions = SessionStore()

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", timeout=60.0
    ) as client:
        created = await client.post(
            "/api/v1/evaluate",
            json={"prompt": "Reply with exactly: ok"},
        )
        assert created.status_code == 200
        body = created.json()
        assert body["response"].startswith("[mock] echo:")
        session_id = body["session_id"]

        for _ in range(45):
            fetched = await client.get(f"/api/v1/evaluations/{session_id}")
            assert fetched.status_code == 200
            session = fetched.json()
            status = session["candidate_status"]
            if status == "ok":
                assert session["candidate"]["text"]
                assert session["candidate"]["model"]
                comparison = await client.get(
                    f"/api/v1/evaluations/{session_id}/comparison"
                )
                assert comparison.status_code == 200
                assert comparison.json()["comparison"]["text_diff"] is not None
                return
            if status == "failed":
                pytest.fail(
                    f"Live candidate failed: {session.get('error')}"
                )
            await asyncio.sleep(1)

        pytest.fail("Live candidate did not complete within 45 seconds")
