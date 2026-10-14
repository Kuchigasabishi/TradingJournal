#!/usr/bin/env python3
"""A stand-in for ForexFactory and Google Calendar, for verification (docs/BLUEPRINT.md, P8).

    python e2e/support/feed_stub.py --port 8765 --fixtures fixtures --log logs/_run/phase_3/feed-stub.jsonl \\
        --gcal-token private-0123456789abcdef0123456789abcdef

Standard library only. It serves the static files in fixtures/ over real HTTP on loopback (or, with --host 0.0.0.0 inside
the compose network of scripts/verify.py --backend compose, to the app container only), so the app's whole fetch path is
exercised (headers, conditional requests, status codes, timeouts) while nothing leaves the machine.

    GET /ff/thisweek.xml       the weekly export, as XML or JSON depending on the scripted format
    GET /gcal/ical/me/<token>/basic.ics   the calendar (any other token answers 404, like a revoked secret address)
    POST /__control            script the next answers, for example {"ff": {"variant": "b", "mode": "http_429"}}
    POST /__reset              back to the defaults, and forget the request list
    GET  /__state, /__requests

Per feed, `variant` is "a" or "b" (the fixture files), `format` (ForexFactory only) is "xml" or "json", and `mode` is one of
ok, slow, http_429, http_500, http_503, http_404, denied_403, denied_html, html, malformed, empty. A good answer carries
an ETag and honors If-None-Match with a 304, like the real hosts do. Every request is logged as one JSON line
(source=stub), with the secret token in the path masked, so the merged verification log shows exactly what the app asked for.
"""
import argparse
import hashlib
import json
import re
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

DEFAULTS = {
    "ff": {"variant": "a", "format": "xml", "mode": "ok", "delay": 5.0},
    "gcal": {"variant": "a", "mode": "ok", "delay": 5.0},
}
STATUS_MODES = {
    "http_429": (429, b"Too Many Requests"),
    "http_500": (500, b"Internal Server Error"),
    "http_503": (503, b"Service Unavailable"),
    "http_404": (404, b"Not Found"),
}
EMPTY_CALENDAR = b"BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//stub//EN\nEND:VCALENDAR\n"


class Stub:
    def __init__(self, fixtures: Path, log: Path | None, token: str) -> None:
        self.fixtures = fixtures
        self.token = token
        self.lock = threading.Lock()
        self.state = json.loads(json.dumps(DEFAULTS))
        self.requests: list[dict] = []
        self.log_file = open(log, "a", encoding="utf-8", newline="\n") if log else None
        if self.log_file:
            Path(log).parent.mkdir(parents=True, exist_ok=True)

    def read(self, *parts: str) -> bytes:
        return self.fixtures.joinpath(*parts).read_bytes()

    def record(self, **fields) -> None:
        entry = {"ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"), "source": "stub", "level": "info", **fields}
        with self.lock:
            self.requests.append(entry)
            if self.log_file:
                self.log_file.write(json.dumps(entry) + "\n")
                self.log_file.flush()

    # --- what a feed answers ------------------------------------------------------------------------

    def forexfactory(self) -> tuple[int, str, bytes, dict]:
        state = self.state["ff"]
        name = f"week_{state['variant']}.{state['format']}"
        content_type = "text/xml" if state["format"] == "xml" else "application/json"
        return self._answer(state, content_type, lambda: self.read("forexfactory", name), b"[]" if state["format"] == "json" else b"<?xml version=\"1.0\"?><weeklyevents></weeklyevents>", "forexfactory", "truncated.xml")

    def calendar(self) -> tuple[int, str, bytes, dict]:
        state = self.state["gcal"]
        # Google writes CRLF line endings; the files in the repository use LF like everything else.
        read = lambda: self.read("gcal", f"personal_{state['variant']}.ics").replace(b"\n", b"\r\n")  # noqa: E731
        return self._answer(state, "text/calendar; charset=utf-8", read, EMPTY_CALENDAR, "gcal", "malformed.ics")

    def _answer(self, state: dict, content_type: str, read, empty: bytes, feed: str, broken: str) -> tuple[int, str, bytes, dict]:
        mode = state["mode"]
        if mode in STATUS_MODES:
            status, body = STATUS_MODES[mode]
            return status, "text/plain", body, {}
        if mode == "denied_403":
            return 403, "text/html", self.read("forexfactory", "request_denied.html"), {}
        if mode == "denied_html":
            return 200, "text/html", self.read("forexfactory", "request_denied.html"), {}
        if mode == "html":
            page = "maintenance.html" if feed == "forexfactory" else "sign_in_page.html"
            return 200, "text/html", self.read("forexfactory" if feed == "forexfactory" else "gcal", page), {}
        if mode == "malformed":
            return 200, content_type, self.read("forexfactory" if feed == "forexfactory" else "gcal", broken), {}
        if mode == "empty":
            return 200, content_type, empty, {}
        if mode == "slow":
            time.sleep(float(state.get("delay", 5.0)))
        body = read()
        etag = 'W/"%s"' % hashlib.sha1(body).hexdigest()[:16]
        return 200, content_type, body, {"ETag": etag, "Cache-Control": "public, max-age=60"}


class FeedServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address) -> None:
        """A client that hangs up while the stub waits for its next request (the app closes its connection after every fetch, and
        Windows reports that as a reset) is how an HTTP conversation ends, not an error. Anything else is a bug in the stub:
        it is printed as usual, and a line on stderr fails the verification run."""
        if isinstance(sys.exc_info()[1], ConnectionError):
            return
        super().handle_error(request, client_address)


def make_handler(stub: Stub):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args) -> None:
            pass

        def send(self, status: int, content_type: str, body: bytes, headers: dict | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            if body and self.command != "HEAD":
                self.wfile.write(body)

        def json(self, status: int, payload) -> None:
            self.send(status, "application/json", json.dumps(payload).encode())

        def masked_path(self) -> str:
            return re.sub(r"private-[0-9a-fA-F]+", "private-***", urlsplit(self.path).path)

        def do_GET(self) -> None:
            path = urlsplit(self.path).path
            if path == "/__state":
                return self.json(200, stub.state)
            if path == "/__requests":
                with stub.lock:
                    return self.json(200, list(stub.requests))
            if path == "/ff/thisweek.xml" or path == "/ff/thisweek.json":
                feed, answer = "forexfactory", stub.forexfactory
            elif path == f"/gcal/ical/me/{stub.token}/basic.ics":
                feed, answer = "gcal", stub.calendar
            else:
                stub.record(msg="stub_request", feed="unknown", method="GET", path=self.masked_path(), status=404)
                return self.send(404, "text/plain", b"Not Found")

            state = dict(stub.state["ff" if feed == "forexfactory" else "gcal"])
            started = time.monotonic()
            conditional = bool(self.headers.get("If-None-Match"))
            details = dict(
                msg="stub_request", feed=feed, method="GET", path=self.masked_path(), mode=state["mode"], variant=state["variant"],
                format=state.get("format"), conditional=conditional, user_agent=self.headers.get("User-Agent"), accept=self.headers.get("Accept"),
            )
            if state["mode"] == "slow":
                # The client will usually give up before the answer is ready, so the request is logged on receipt.
                stub.record(status=200, delayed=True, **details)
            status, content_type, body, headers = answer()
            if status == 200 and headers.get("ETag") and self.headers.get("If-None-Match") == headers["ETag"]:
                status, body = 304, b""
            if state["mode"] != "slow":
                stub.record(status=status, duration_ms=round((time.monotonic() - started) * 1000, 1), **details)
            try:
                self.send(status, content_type, body, headers)
            except OSError:
                pass  # the client has gone: a slow answer nobody waited for

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            path = urlsplit(self.path).path
            if path == "/__control":
                changes = json.loads(raw or b"{}")
                for feed, values in changes.items():
                    if feed not in stub.state:
                        return self.json(400, {"error": f"unknown feed {feed!r}"})
                    stub.state[feed].update(values)
                stub.record(msg="stub_control", feed="control", method="POST", path=path, status=200, changes=changes)
                return self.json(200, stub.state)
            if path == "/__reset":
                stub.state = json.loads(json.dumps(DEFAULTS))
                with stub.lock:
                    stub.requests.clear()
                stub.record(msg="stub_reset", feed="control", method="POST", path=path, status=200)
                return self.json(200, stub.state)
            self.send(404, "text/plain", b"Not Found")

    return Handler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Feed stub for verification.")
    parser.add_argument("--host", default="127.0.0.1", help="the address to listen on: loopback natively, 0.0.0.0 inside the compose network")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--log", type=Path)
    parser.add_argument("--gcal-token", default="private-0123456789abcdef0123456789abcdef")
    args = parser.parse_args(argv)

    stub = Stub(args.fixtures, args.log, args.gcal_token)
    server = FeedServer((args.host, args.port), make_handler(stub))

    def stop(*_: object) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    for name in ("SIGTERM", "SIGINT", "SIGBREAK"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), stop)
    print(f"LISTENING {server.server_address[1]}", flush=True)
    server.serve_forever()
    server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
