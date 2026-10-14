"""HTTP for the feed connectors: one GET, with conditional headers, a size limit and a hard deadline.

Every failure becomes a `FeedError` with a short fixed phrase. The exceptions httpx raises carry the full URL in
their text, and the Google Calendar address is a secret, so nothing from an exception message is ever reused.
"""
import time

import httpx2

from app.connectors.base import BadContent, FeedError, FetchFailed, FetchResult, Throttled

# What an over-limit page says. ForexFactory's host is reported to answer too many downloads with an HTML
# "Request Denied" page instead of the feed (docs/BLUEPRINT.md, section 4.3).
_DENIAL_MARKERS = (b"request denied", b"access denied", b"too many requests", b"rate limit", b"error 1015", b"you are being rate limited")


def looks_like_denial(body: bytes) -> bool:
    head = body[:8192].lower()
    return any(marker in head for marker in _DENIAL_MARKERS)


def fetch(
    url: str,
    *,
    user_agent: str,
    accept: str,
    timeout: float,
    max_bytes: int,
    etag: str | None = None,
    last_modified: str | None = None,
    trust_env: bool = False,
) -> FetchResult:
    """GET `url`. A 304 to a conditional request comes back as `not_modified`. Anything unusable raises FeedError."""
    headers = {"User-Agent": user_agent, "Accept": accept}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    deadline = time.monotonic() + timeout * 2  # httpx's timeout is per read, so a host that drips bytes needs this too
    try:
        with httpx2.Client(timeout=timeout, follow_redirects=True, max_redirects=3, trust_env=trust_env) as client:
            with client.stream("GET", url, headers=headers) as response:
                status = response.status_code
                if status == 304:
                    return FetchResult(not_modified=True, http_status=304, etag=etag, last_modified=last_modified)
                if status == 429:
                    raise Throttled("HTTP 429: the host is rate limiting requests", http_status=429)
                if status >= 400:
                    if status in (403, 503) and looks_like_denial(next(response.iter_bytes(8192), b"")):
                        raise Throttled(f"HTTP {status}: the host refused the request as over its limit", http_status=status)
                    raise FetchFailed(f"HTTP {status}", http_status=status)
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > max_bytes:
                        raise BadContent(f"the response is larger than {max_bytes} bytes", http_status=status)
                    if time.monotonic() > deadline:
                        raise FetchFailed("the host answered too slowly")
                return FetchResult(
                    body=bytes(body),
                    http_status=status,
                    etag=response.headers.get("etag"),
                    last_modified=response.headers.get("last-modified"),
                )
    except FeedError:
        raise
    except httpx2.TimeoutException:
        raise FetchFailed("timed out waiting for the host") from None
    except httpx2.ConnectError:
        raise FetchFailed("could not connect to the host") from None
    except httpx2.HTTPError as exc:
        # Only the class name: the exception's own text would include the URL.
        if "Redirect" in type(exc).__name__:
            raise FetchFailed("too many redirects") from None
        raise FetchFailed(f"the request failed ({type(exc).__name__})") from None
