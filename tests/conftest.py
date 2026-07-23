from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    database_path = (tmp_path / "evaluator.db").as_posix()
    return Settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{database_path}",
        sample_rate=1,
        queue_backend="database",
        worker_poll_seconds=0.01,
    )


@pytest_asyncio.fixture
async def test_app(settings: Settings):
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        yield app


@pytest_asyncio.fixture
async def client(test_app):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(
        transport=transport, base_url="http://test"
    ) as http_client:
        yield http_client

