import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import agent, events, sessions, websocket


APP_NAME = "Lecture-Link Agent Backend"
APP_VERSION = "0.1.0"


def _cors_allow_origins() -> list[str]:
    """Return browser origins allowed to call the backend API."""
    origins = {
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    }

    for port_name in ("FRONTEND_PORT", "FRONTEND_PREVIEW_PORT"):
        port = os.getenv(port_name, "").strip()
        if port:
            origins.add(f"http://localhost:{port}")
            origins.add(f"http://127.0.0.1:{port}")

    configured_origins = os.getenv("CORS_ALLOW_ORIGINS", "")
    for origin in configured_origins.split(","):
        normalized = origin.strip().rstrip("/")
        if normalized:
            origins.add(normalized)

    return sorted(origins)


def create_app() -> FastAPI:
    """Build the FastAPI app and register all route modules.

    Keep app creation in a function so tests can create isolated app instances
    later without importing a running server.
    """
    app = FastAPI(
        title=APP_NAME,
        version=APP_VERSION,
        description="Local Agent backend for classroom sessions, events, and realtime updates.",
    )

    # Frontend uses Vite dev on 5173 and app preview on 4173. Extra origins can
    # be supplied through CORS_ALLOW_ORIGINS for device/browser deployments.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_allow_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/", tags=["system"])
    async def root() -> dict[str, str]:
        return {
            "name": APP_NAME,
            "version": APP_VERSION,
            "status": "ok",
        }

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    # Route modules are intentionally thin. Business logic will move into
    # core managers as the MVP grows:
    # - SessionManager: classroom lifecycle
    # - ContextManager: transcript/timeline/visual context
    # - KnowledgeGraphManager: graph updates
    # - LocalStorage: final data persistence
    app.include_router(sessions.router)
    app.include_router(events.router)
    app.include_router(websocket.router)
    app.include_router(agent.router)

    return app


app = create_app()
