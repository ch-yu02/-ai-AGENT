from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import agent, events, sessions, websocket


APP_NAME = "Lecture-Link Agent Backend"
APP_VERSION = "0.1.0"


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

    # Frontend defaults to Vite's dev server. Add production origins here when
    # the touch-screen frontend or phone client has a fixed deployment address.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
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
