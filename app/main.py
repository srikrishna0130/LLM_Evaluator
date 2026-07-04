from contextlib import asynccontextmanager
from fastapi import FastAPI
import logging
from app.core.config import settings
from app.core.logger import setup_logging
from app.api.router import api_router
from app.api.errors import register_exception_handlers
from app.services.candidate_model import CandidateModelClient
from app.services.mock_model import MockModelClient
from app.services.session_store import SessionStore

# Setup logging before anything else
setup_logging()
log = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic
    log.info(f"Starting {settings.PROJECT_NAME} in {settings.ENVIRONMENT} mode")
    app.state.mock_model = MockModelClient()
    app.state.candidate_model = CandidateModelClient()
    app.state.sessions = SessionStore()

    yield

    # Shutdown logic (Graceful Shutdown)
    log.info("Shutting down service, cleaning up resources...")
    await app.state.candidate_model.aclose()
    log.info("Cleanup complete. Goodbye!")

app = FastAPI(
    title=settings.PROJECT_NAME,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc"
)

# Register custom exception handlers
register_exception_handlers(app)

# Include API routes
app.include_router(api_router, prefix="/api/v1")
