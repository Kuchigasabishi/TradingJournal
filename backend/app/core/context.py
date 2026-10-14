"""Per-request context shared by the middleware, the logger and the database layer."""
from contextvars import ContextVar

# Set by RequestLogMiddleware. Sync endpoints run in a worker thread, and anyio copies the context
# into it, so every log record written while handling a request can carry the same ID.
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
