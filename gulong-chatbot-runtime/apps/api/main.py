"""FastAPI entrypoint for the Gulong chatbot runtime service."""

from __future__ import annotations

import os
from typing import Any, Dict

from fastapi import FastAPI

from apps.api.routers import gulong
from runtime.utils.time_utils import now_manila_str


def create_app() -> FastAPI:
    app = FastAPI(title="Gulong Chatbot Runtime")
    app.include_router(gulong.router)

    @app.get("/health", response_model=Dict[str, Any])
    async def health() -> Dict[str, Any]:
        return {
            "status": "ok",
            "ts": now_manila_str(),
            "runtime_generation": os.getenv("RUNTIME_GENERATION", "v7"),
            "release_version": os.getenv("RELEASE_VERSION", ""),
            "git_sha": os.getenv("GIT_SHA", ""),
            "service_environment": os.getenv("SERVICE_ENVIRONMENT", ""),
            "runtime_host": os.getenv("RUNTIME_HOST", os.getenv("K_SERVICE", "")),
            "followup_send_enabled": str(os.getenv("FOLLOWUP_SEND_ENABLED", "false")).strip().lower()
            in {"1", "true", "yes", "on"},
        }

    return app


app = create_app()
