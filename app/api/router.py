from fastapi import APIRouter
from app.api.routes import evaluations, health

api_router = APIRouter()

api_router.include_router(health.router, tags=["health"])
api_router.include_router(evaluations.router, tags=["evaluations"])