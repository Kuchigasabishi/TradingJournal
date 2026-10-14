"""The feed fetcher against a real HTTP server on loopback: statuses, conditional requests, limits, and the promise that
no failure message ever carries the address, because the Google Calendar address is a secret."""
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.connectors import http
from app.connectors.base import BadContent, FetchFailed, Throttled

TOKEN = "private-0123456789abcdef0123456789abcdef"
seen: list[dict] = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:  # keep pytest output quiet
        pass

    def reply(self, status: int, body: bytes = b"", headers: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        seen.append({"path": self.path, **{k.lower(): v for k, v in self.headers.items()}})
        name = self.path.split("/")[1]
        if name == "ok":
            self.reply(200, b"hello", {"ETag": 'W/"abc"', "Last-Modified": "Tue, 13 Oct 2026 06:42:18 GMT"})
        elif name == "conditional":
            self.reply(304) if self.headers.get("If-None-Match") == 'W/"abc"' else self.reply(200, b"fresh", {"ETag": 'W/"abc"'})
        elif name == "limited":
            self.reply(429, b"slow down")
        elif name == "denied":
            self.reply(403, b"<html><h1>Request Denied</h1></html>")
        elif name == "forbidden":
            self.reply(403, b"nope")
        elif name == "broken":
            self.reply(500, b"oops")
        elif name == "big":
            self.reply(200, b"x" * 5000)
        elif name == "redirect":
            self.reply(302, headers={"Location": "/ok"})
        elif name == "loop":
            self.reply(302, headers={"Location": "/loop"})
        elif name == "stall":
            time.sleep(1.0)
            try:
                self.reply(200, b"too late")
            except OSError:
                pass  # the client has already given up
        elif name == "drip":
            self.send_response(200)
            self.send_header("Content-Length", "50")
            self.end_headers()
            try:
                for _ in range(50):
                    self.wfile.write(b"x")
                    self.wfile.flush()
                    time.sleep(0.1)
            except OSError:
                pass  # the client gave up, which is what the test is about
        else:
            self.reply(404)


@pytest.fixture(scope="module")
def base():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def get(base, name, **overrides):
    options = dict(user_agent="TradingJournal/test", accept="*/*", timeout=2.0, max_bytes=1000)
    options.update(overrides)
    return http.fetch(f"{base}/{name}/{TOKEN}/basic.ics", **options)


def test_a_good_answer_comes_back_with_its_validators(base):
    result = get(base, "ok")
    assert (result.body, result.http_status, result.not_modified) == (b"hello", 200, False)
    assert (result.etag, result.last_modified) == ('W/"abc"', "Tue, 13 Oct 2026 06:42:18 GMT")


def test_the_request_names_the_app_and_what_it_accepts(base):
    seen.clear()
    get(base, "ok", user_agent="TradingJournal/0.3 (personal, single-user)", accept="text/calendar")
    assert seen[-1]["user-agent"] == "TradingJournal/0.3 (personal, single-user)" and seen[-1]["accept"] == "text/calendar"


def test_validators_are_sent_back_and_a_304_is_not_modified(base):
    seen.clear()
    result = get(base, "conditional", etag='W/"abc"', last_modified="Tue, 13 Oct 2026 06:42:18 GMT")
    assert result.not_modified and result.body == b"" and result.http_status == 304
    assert seen[-1]["if-none-match"] == 'W/"abc"' and seen[-1]["if-modified-since"] == "Tue, 13 Oct 2026 06:42:18 GMT"
    assert get(base, "conditional").body == b"fresh"  # without validators the host sends the body


def test_429_is_throttling(base):
    with pytest.raises(Throttled) as caught:
        get(base, "limited")
    assert caught.value.http_status == 429


def test_a_403_with_the_hosts_denial_page_is_throttling_and_a_plain_403_is_an_error(base):
    with pytest.raises(Throttled):
        get(base, "denied")
    with pytest.raises(FetchFailed) as caught:
        get(base, "forbidden")
    assert caught.value.http_status == 403


def test_a_server_error_is_an_error(base):
    with pytest.raises(FetchFailed) as caught:
        get(base, "broken")
    assert (caught.value.message, caught.value.http_status) == ("HTTP 500", 500)


def test_a_redirect_is_followed_and_a_loop_is_not(base):
    assert get(base, "redirect").body == b"hello"
    with pytest.raises(FetchFailed, match="too many redirects"):
        get(base, "loop")


def test_a_body_over_the_limit_is_refused(base):
    with pytest.raises(BadContent, match="larger than 1000 bytes"):
        get(base, "big")


def test_a_host_that_does_not_answer_in_time_is_an_error(base):
    with pytest.raises(FetchFailed, match="timed out"):
        get(base, "stall", timeout=0.3)


def test_a_host_that_drips_bytes_hits_the_overall_deadline(base):
    # Each read is quick, so httpx's per-read timeout never fires; the overall deadline (twice the timeout) does.
    started = time.monotonic()
    with pytest.raises(FetchFailed, match="too slowly"):
        get(base, "drip", timeout=0.3)
    assert time.monotonic() - started < 3


def test_nothing_listening_is_an_error():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]  # a port that was free a moment ago and has nobody on it now
    # Windows retries a refused loopback connection for about two seconds, so it can surface as a timeout there.
    with pytest.raises(FetchFailed, match="could not connect|timed out"):
        http.fetch(f"http://127.0.0.1:{port}/ical/me/{TOKEN}/basic.ics", user_agent="t", accept="*/*", timeout=2.0, max_bytes=1000)


@pytest.mark.parametrize("name", ["limited", "denied", "forbidden", "broken", "loop", "big", "stall"])
def test_no_failure_message_ever_contains_the_address(base, name):
    """The address holds a secret token. httpx's own exception text includes the URL, so none of it may be reused."""
    with pytest.raises(Exception) as caught:
        get(base, name, timeout=0.3)
    text = f"{caught.value} {caught.value!r} {getattr(caught.value, 'message', '')}"
    assert TOKEN not in text and "127.0.0.1" not in text and "/basic.ics" not in text
