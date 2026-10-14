"""Application factory: settings, database, routers, and the optional static web build."""
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import Engine
from sqlalchemy.engine import make_url

from app.api import calendar, docs, events, health, notes, sync, tags, trades
from app.connectors.registry import build_sources
from app.core.clock import make_clock
from app.core.config import Settings
from app.core.errors import install_error_handlers
from app.core.logging import register_secret
from app.core.middleware import RequestLogMiddleware
from app.core.security import BodyLimitMiddleware, SecurityHeadersMiddleware
from app.core.spa import SpaStaticFiles
from app.db.migrate import run_migrations
from app.db.session import make_engine, make_session_factory
from app.services.feeds import FeedService
from app.services.scheduler import FeedScheduler

log = logging.getLogger("app")

TAGS_METADATA = [
    {"name": "health", "description": "Liveness and readiness."},
    {"name": "trades", "description": "Journal entries. Prices, lot size and P&L are exact decimal strings."},
    {"name": "notes", "description": "Notes for a calendar day."},
    {"name": "tags", "description": "Tags in use."},
    {"name": "calendar", "description": "Month summaries for the calendar view."},
    {"name": "events", "description": "Economic news and Google Calendar events, kept in step with their feeds."},
    {"name": "sync", "description": "Feed status and manual refresh. A refresh returns at once; the fetch runs on a worker thread."},
]

# The Expo dev server (`expo start --web`) runs on another port than the API, so only dev mode needs CORS.
# Verification and production serve the web build from the API itself: one origin, no CORS.
DEV_ORIGINS = ["http://localhost:8081", "http://127.0.0.1:8081"]


def _describe_database(url: str) -> str:
    parsed = make_url(url)
    name = Path(parsed.database).name if parsed.database else "memory"
    return f"{parsed.get_backend_name()}:{name}"


def create_app(settings: Settings | None = None, engine: Engine | None = None) -> FastAPI:
    settings = settings or Settings()
    owns_engine = engine is None
    engine = engine or make_engine(settings.database_url)
    # The calendar's secret address may come from .env, which never reaches os.environ: tell the log redactor.
    register_secret(settings.gcal_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        logging.getLogger("app").setLevel(settings.log_level)
        if owns_engine and settings.auto_migrate:
            run_migrations(settings.database_url)
        log.info(
            "startup",
            extra={
                "env": settings.app_env,
                "database": _describe_database(settings.database_url),
                "timezone": settings.app_timezone,
                "static_dir": str(settings.static_dir) if settings.static_dir else None,
                "pid": os.getpid(),
            },
        )
        if app.state.scheduler is not None:
            app.state.scheduler.start()
        yield
        if app.state.scheduler is not None:
            app.state.scheduler.stop()  # before the engine goes: a worker may be mid-write
        if owns_engine:
            engine.dispose()  # closes the last connection, which checkpoints the SQLite WAL
        log.info("shutdown")

    # OpenAPI and the docs stay under /api so the web app owns every other path.
    app = FastAPI(
        title="Trading Journal API",
        version="0.1.0",
        description="Single-user trading journal. Money values are exact decimal strings; instants are UTC.",
        openapi_tags=TAGS_METADATA,
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)
    app.state.clock = make_clock(settings.app_now_override)
    app.state.feeds = FeedService(app.state.session_factory, settings, app.state.clock, build_sources(settings))
    app.state.scheduler = FeedScheduler(app.state.feeds) if settings.feeds_mode != "off" else None
    # Added before the request logger, which is therefore outside them and records what they refuse.
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(BodyLimitMiddleware, limit=settings.max_request_bytes)
    app.add_middleware(RequestLogMiddleware)
    if settings.app_env == "dev":
        app.add_middleware(
            CORSMiddleware,
            allow_origins=DEV_ORIGINS,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["X-Request-ID", "Location"],
        )
    install_error_handlers(app)

    for router in (health.router, trades.router, notes.router, tags.router, calendar.router, events.router, sync.router, docs.router):
        app.include_router(router)
    app.mount(docs.ASSETS_URL, StaticFiles(directory=docs.SWAGGER_DIR), name="docs-assets")

    @app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"], include_in_schema=False)
    def unknown_api_path(path: str) -> None:
        # Without this, an unknown /api path would fall through to the web app and answer with HTML.
        raise HTTPException(status_code=404)

    # Mounted last: the routes above win, the web build catches everything else.
    if settings.static_dir:
        if settings.static_dir.is_dir():
            app.mount("/", SpaStaticFiles(directory=settings.static_dir, html=True), name="web")
        else:
            log.warning("static_dir_missing", extra={"static_dir": str(settings.static_dir)})

    return app


app = create_app()
