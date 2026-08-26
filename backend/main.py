from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import _split_csv, settings
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
    tables,
)

app = FastAPI(
    title="QBCals",
    description="AI-powered business event matchmaking platform",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_split_csv(settings.ALLOWED_CORS_ORIGINS),
    allow_credentials=True,
    allow_methods=_split_csv(settings.CORS_ALLOW_METHODS),
    allow_headers=_split_csv(settings.CORS_ALLOW_HEADERS),
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


@app.get("/health")
def health_check():
    return {"status": "ok", "model": settings.AI_MODEL}
