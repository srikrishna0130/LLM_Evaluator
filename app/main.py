from contextlib import asynccontextmanager
from fastapi import FastAPI
import logging
from app.core.config import settings
from app.core.logger import setup_logging
from app.api.router import api_router
from app.api.errors import register_exception_handlers

# Setup logging before anything else
setup_logging()
log = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic
    log.info(f"Starting {settings.PROJECT_NAME} in {settings.ENVIRONMENT} mode")
    # Initialize DB connections, background task queues, etc.
    
    yield
    
    # Shutdown logic (Graceful Shutdown)
    log.info("Shutting down service, cleaning up resources...")
    # Close DB connections, gracefully stop background tasks, etc.
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