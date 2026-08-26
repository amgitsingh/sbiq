from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.routers import (
    account,
    auth,
    dashboard,
    events,
    external,
    lookups,
    profiles,
    registrations,
    smtp,
    studio_events,
    tables,
)

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
app.include_router(auth.router)
app.include_router(registrations.router)
app.include_router(account.router)
app.include_router(dashboard.router)
app.include_router(lookups.router)
app.include_router(profiles.router)
app.include_router(smtp.router)
app.include_router(tables.router)
app.include_router(external.router)
app.include_router(studio_events.router)


@app.get("/health")
def health_check():
    return {"status": "ok", "model": settings.AI_MODEL}
