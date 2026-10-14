"""Request logging and request IDs for the server half of the log contract (docs/BLUEPRINT.md, section 6.3)."""
import logging
import re
import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.context import request_id_var

log = logging.getLogger("app.http")

REQUEST_ID_HEADER = b"x-request-id"
_SAFE_ID = re.compile(r"[A-Za-z0-9_.-]{1,64}")


def _request_id(scope: Scope) -> str:
    for name, value in scope["headers"]:
        if name == REQUEST_ID_HEADER:
            candidate = value.decode("latin-1")
            if _SAFE_ID.fullmatch(candidate):
                return candidate
            break
    return uuid.uuid4().hex[:12]


class RequestLogMiddleware:
    """Logs one record per HTTP request and echoes an X-Request-ID response header.

    An inbound ID is reused only when it is short and made of safe characters, so a client cannot
    inject arbitrary text into the logs. The ID is also published through `request_id_var`, so
    every record written while the request is handled (database transactions, domain events,
    tracebacks) carries it. An unhandled exception is logged here as status 500 at error level and
    re-raised; uvicorn logs the traceback.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _request_id(scope)
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status = 500  # stays 500 if the app raises before a response starts

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = [*message.get("headers", []), (REQUEST_ID_HEADER, request_id.encode("ascii"))]
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            level = logging.ERROR if status >= 500 else logging.WARNING if status >= 400 else logging.INFO
            log.log(
                level,
                "request",
                extra={
                    "request_id": request_id,
                    "method": scope["method"],
                    "path": scope["path"],
                    "status": status,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                },
            )
            request_id_var.reset(token)
