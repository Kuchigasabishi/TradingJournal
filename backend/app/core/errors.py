"""Domain errors and their HTTP mapping. 422 bodies reuse FastAPI's {"detail": [{loc, msg, type}]} shape."""
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class DomainError(Exception):
    """Base class for errors the API reports deliberately."""


class NotFoundError(DomainError):
    def __init__(self, entity: str, key: object) -> None:
        super().__init__(f"{entity} {key} not found")


class InvalidStateError(DomainError):
    def __init__(self, errors: list[dict[str, Any]]) -> None:
        super().__init__("invalid state")
        self.errors = errors


def field_error(field: str, message: str, kind: str, where: str = "body") -> dict[str, Any]:
    return {"loc": [where, field], "msg": message, "type": kind}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(NotFoundError)
    async def not_found(_: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(InvalidStateError)
    async def invalid_state(_: Request, exc: InvalidStateError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": exc.errors})
