from fastapi import FastAPI

from pulseops.api import health, incidents, monitors
from pulseops.api.errors import install_error_handlers
from pulseops.config import ApiSettings


def create_app(api_settings: ApiSettings | None = None) -> FastAPI:
    # Loading ApiSettings here validates the API key at startup: without a
    # valid one, the API refuses to start.
    api_settings = api_settings or ApiSettings()
    docs = api_settings.docs_enabled

    app = FastAPI(
        title="PulseOps",
        description="Uptime monitoring for websites and APIs.",
        version="0.1.0",
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
    )
    app.state.api_settings = api_settings
    # No CORS middleware on purpose (ADR-028).
    install_error_handlers(app)
    app.include_router(monitors.router)
    app.include_router(incidents.router)
    app.include_router(health.router)
    return app


app = create_app()
