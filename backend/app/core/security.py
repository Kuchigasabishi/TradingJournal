"""Response headers and a request size limit: the cheap half of hardening a server that holds one person's journal.

Both are plain ASGI middleware, so they cost nothing per request beyond a header list, and they sit inside the request
logger, which therefore records a refused request like any other (docs/BLUEPRINT.md, section 6.3).
"""
import base64
import hashlib
import re

from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# The web app is one HTML page, one script from this origin and a style reset in the page itself (react-native-web writes
# its styles at runtime). Nothing is loaded from elsewhere, nothing may frame it, and a form can only post back here.
APP_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; "
    "connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
)

COMMON_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=(), usb=()"),
    (b"cross-origin-opener-policy", b"same-origin"),
    (b"cross-origin-resource-policy", b"same-origin"),
)

_INLINE_SCRIPT = re.compile(r"<script>(.*?)</script>", re.DOTALL)


def csp_for_page_with_inline_script(html: str) -> str:
    """The policy for a generated page (the API docs) whose one inline script is allowed by its hash, not by 'unsafe-inline'."""
    hashes = [f"'sha256-{base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()}'" for body in _INLINE_SCRIPT.findall(html)]
    return APP_CSP.replace("script-src 'self'", "script-src 'self' " + " ".join(hashes))


class SecurityHeadersMiddleware:
    """Adds the common headers to every response, the content security policy to HTML (unless the route chose its own), and
    `Cache-Control: no-store` to the API's answers: they are one person's trades and notes, and nothing should keep a copy."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope["path"]

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {name.lower() for name, _ in headers}
                headers += [(name, value) for name, value in COMMON_HEADERS if name not in present]
                content_type = next((value for name, value in headers if name.lower() == b"content-type"), b"")
                if content_type.startswith(b"text/html") and b"content-security-policy" not in present:
                    headers.append((b"content-security-policy", APP_CSP.encode("ascii")))
                if path.startswith("/api/") and not path.startswith("/api/docs-assets/") and b"cache-control" not in present:
                    headers.append((b"cache-control", b"no-store"))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)


TOO_LARGE = "The request body is larger than this server accepts."


class BodyLimitMiddleware:
    """Refuses a request body larger than `limit` bytes with 413. A declared Content-Length is refused before a byte is read;
    a body that does not declare one (chunked) is counted as it arrives, and the route that is reading it gets the same 413
    from its own error handling (FastAPI turns any other exception raised while reading a body into a 400). The journal's
    own requests are a few hundred bytes."""

    def __init__(self, app: ASGIApp, limit: int) -> None:
        self.app = app
        self.limit = limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = next((value for name, value in scope["headers"] if name == b"content-length"), None)
        if declared is not None and declared.isdigit() and int(declared) > self.limit:
            body = ('{"detail":"%s"}' % TOO_LARGE).encode()
            await send({"type": "http.response.start", "status": 413, "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()), (b"connection", b"close")]})
            await send({"type": "http.response.body", "body": body})
            return

        received = 0

        async def counting_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.limit:
                    raise HTTPException(status_code=413, detail=TOO_LARGE)
            return message

        await self.app(scope, counting_receive, send)
