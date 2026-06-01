from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


APP_NAME = "Lecture-Link Agent Backend"
APP_VERSION = "0.1.0"


def create_app() -> FastAPI:
    app = FastAPI(
        title=APP_NAME,
        version=APP_VERSION,
        description="Local Agent backend for classroom sessions, events, and realtime updates.",
    )

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

    return app


app = create_app()
