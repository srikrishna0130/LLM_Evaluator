from fastapi import APIRouter
import logging

router = APIRouter()
log = logging.getLogger(__name__)

@router.get("/health")
async def health_check():
    """Dummy endpoint to verify the service is running."""
    log.info("Health check endpoint called")
    return {"status": "ok", "message": "Service is healthy"}