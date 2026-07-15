from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.routers import events

app = FastAPI(
    title="QBCals",
    description="AI-powered business event matchmaking platform",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(events.router)


@app.get("/health")
def health_check():
    return {"status": "ok", "model": settings.AI_MODEL}
