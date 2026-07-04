import pytest
from httpx import ASGITransport, AsyncClient
from app.main import app

# Mark all tests in this file as async
pytestmark = pytest.mark.asyncio

async def test_health_check():
    """
    Test the dummy health check endpoint.
    This serves as an integration test example.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/v1/health")
    
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "message": "Service is healthy"}