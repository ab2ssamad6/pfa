"""FastAPI application: read APIs for the dashboard + incident lifecycle actions."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..core.config import Settings, get_settings
from ..core.logging import setup_logging
from ..db.session import make_engine, make_sessionmaker
from .routers import hosts, incidents, model, system


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = make_engine(settings.database_url)
        app.state.engine, app.state.sessions = engine, make_sessionmaker(engine)
        yield
        await engine.dispose()

    app = FastAPI(title="NetAD — Network Anomaly Detection API", version="1.0.0", lifespan=lifespan,
                  description="Suspected anomalies are model predictions, not confirmed attacks.")
    app.state.settings = settings
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["GET", "POST"],
                       allow_headers=["*"])
    for r in (system.router, hosts.router, incidents.router, model.router):
        app.include_router(r)
    return app


app = create_app()
