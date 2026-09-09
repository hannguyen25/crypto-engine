from fastapi import APIRouter
from app.api.v1.endpoints import intents

api_router = APIRouter()
api_router.include_router(intents.router, prefix="/intents", tags=["Intents"])