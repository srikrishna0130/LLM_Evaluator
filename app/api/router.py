from fastapi import APIRouter
from app.api.routes import health

api_router = APIRouter()

api_router.include_router(health.router, tags=["health"])
# Include other routers here:
# api_router.include_router(users.router, prefix="/users", tags=["users"])