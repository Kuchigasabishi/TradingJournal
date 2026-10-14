from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db.migrate import current_revision, head_revision

router = APIRouter(prefix="/api", tags=["health"])


class Ready(BaseModel):
    status: Literal["ready"]
    database: Literal["ok"]
    migration: str
    # The zone the server buckets calendar days in. Clients format and parse times in it.
    timezone: str


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness: 200 whenever the process is up."""
    return {"status": "ok"}


@router.get("/ready", response_model=Ready, responses={503: {"description": "Database unreachable or migrations not at head"}})
def ready(request: Request) -> Ready | JSONResponse:
    """Readiness: the database answers and the schema is at the migration head the code expects."""
    try:
        with request.app.state.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            current = current_revision(connection)
    except SQLAlchemyError as exc:
        return JSONResponse(status_code=503, content={"status": "not_ready", "problems": {"database": type(exc).__name__}})
    head = head_revision()
    if current != head:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "problems": {"migrations": f"database is at {current}, code expects {head}"}},
        )
    return Ready(status="ready", database="ok", migration=current, timezone=request.app.state.settings.app_timezone)
