"""Shared fixtures for the Playwright suite.

Implements the client and test halves of the log contract and the clean-run rule
(docs/BLUEPRINT.md, sections 6.3 and 6.4). Configuration comes from the environment, so the same
suite runs against the native backend and the compose stack:

    BASE_URL       required, for example http://127.0.0.1:8000
    VERIFY_PHASE   phase being verified; screenshots go to artifacts/phase_N/screenshots (default 0)
    E2E_LOG_FILE   JSONL file for client and test records (default logs/_run/e2e.jsonl)
    ARTIFACTS_DIR  root for screenshots (default <repo>/artifacts)
    E2E_NO_SANDBOX 1 inside the compose test container, where Chromium cannot create its sandbox

Run it through scripts/verify.py, which sets all of these and merges the logs.
"""
import json
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator
from urllib.parse import urlparse

import pytest
from playwright.sync_api import (
    APIRequestContext,
    APIResponse,
    BrowserContext,
    ConsoleMessage,
    Error,
    Frame,
    Page,
    Playwright,
    Request,
    Response,
)

from support.journal import Journal
from support.ui import shot_name

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
_PHASE_DIR = re.compile(r"^p(\d)_")
_CONSOLE_LEVELS = {
    "log": "info",
    "info": "info",
    "debug": "debug",
    "trace": "debug",
    "warning": "warning",
    "error": "error",
    "assert": "error",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class JsonlWriter:
    """Appends log-contract records (one JSON object per line, LF endings, ASCII-only)."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(path, "a", encoding="utf-8", newline="\n")
        self._lock = threading.Lock()

    def write(self, source: str, level: str, msg: str, **fields: Any) -> None:
        record = {"ts": _now(), "source": source, "level": level, "msg": msg, **fields}
        line = json.dumps(record, default=str)
        with self._lock:
            self._file.write(line + "\n")
            self._file.flush()


_writer: JsonlWriter | None = None


def get_writer() -> JsonlWriter:
    global _writer
    if _writer is None:
        _writer = JsonlWriter(Path(os.environ.get("E2E_LOG_FILE") or REPO / "logs" / "_run" / "e2e.jsonl"))
    return _writer


# --- collection and test-lifecycle records -------------------------------------------------------


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Tests under e2e/tests/p<N>_<topic>/ get marker pN, so `-m "p0 or p1"` selects phases."""
    for item in items:
        try:
            parts = item.path.relative_to(HERE).parts
        except ValueError:
            continue
        for part in parts:
            match = _PHASE_DIR.match(part)
            if match:
                item.add_marker(getattr(pytest.mark, f"p{match.group(1)}"))
                break


def pytest_runtest_logstart(nodeid: str, location: Any) -> None:
    get_writer().write("test", "info", "test_start", test=nodeid)


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if report.when != "call" and report.passed:
        return
    fields: dict[str, Any] = {
        "test": report.nodeid,
        "when": report.when,
        "outcome": report.outcome,
        "duration_s": round(report.duration, 3),
    }
    if report.failed:
        lines = [line.strip() for line in report.longreprtext.splitlines() if line.strip()]
        fields["detail"] = " | ".join(lines)[:800]
    get_writer().write("test", "error" if report.failed else "info", "test_report", **fields)


# --- configuration fixtures ----------------------------------------------------------------------


@pytest.fixture(scope="session")
def e2e_log() -> JsonlWriter:
    return get_writer()


@pytest.fixture(scope="session")
def base_url() -> str:
    url = os.environ.get("BASE_URL", "").rstrip("/")
    if not url:
        pytest.exit("BASE_URL is not set. Run through scripts/verify.py or export BASE_URL=http://127.0.0.1:8000", returncode=2)
    return url


@pytest.fixture(scope="session")
def screenshots_dir() -> Path:
    root = Path(os.environ.get("ARTIFACTS_DIR") or REPO / "artifacts")
    directory = root / f"phase_{os.environ.get('VERIFY_PHASE', '0')}" / "screenshots"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args: dict[str, Any]) -> dict[str, Any]:
    """Chromium's own sandbox needs privileges an unprivileged container does not have, so the compose backend sets
    E2E_NO_SANDBOX=1 for the test container, which is itself the isolation (it holds nothing but the suite)."""
    if os.environ.get("E2E_NO_SANDBOX") == "1":
        return {**browser_type_launch_args, "args": [*browser_type_launch_args.get("args", []), "--no-sandbox"]}
    return browser_type_launch_args


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args: dict[str, Any]) -> dict[str, Any]:
    """Fixed viewport, locale, time zone and motion so runs and screenshots are repeatable."""
    return {
        **browser_context_args,
        "viewport": {"width": 1280, "height": 800},
        "device_scale_factor": 1,
        "locale": "en-US",
        "timezone_id": "UTC",
        "reduced_motion": "reduce",
        "color_scheme": "light",
    }


# --- API tests -----------------------------------------------------------------------------------


class Api:
    """Playwright's APIRequestContext with one log record (source=test) per call.

    Every call carries an X-Request-ID that the server echoes and logs, so a test record can be
    matched to its server record exactly.
    """

    def __init__(self, context: APIRequestContext, log: JsonlWriter, test_id: str) -> None:
        self._context = context
        self._log = log
        self._test = test_id

    def request(self, method: str, url: str, **kwargs: Any) -> APIResponse:
        headers = dict(kwargs.pop("headers", None) or {})
        headers.setdefault("X-Request-ID", f"t{uuid.uuid4().hex[:10]}")
        started = time.perf_counter()
        response = getattr(self._context, method)(url, headers=headers, **kwargs)
        self._log.write(
            "test",
            "warning" if response.status >= 400 else "info",
            "api_request",
            test=self._test,
            method=method.upper(),
            url=url,
            status=response.status,
            request_id=headers["X-Request-ID"],
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
        )
        return response

    def get(self, url: str, **kwargs: Any) -> APIResponse:
        return self.request("get", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> APIResponse:
        return self.request("post", url, **kwargs)

    def patch(self, url: str, **kwargs: Any) -> APIResponse:
        return self.request("patch", url, **kwargs)

    def delete(self, url: str, **kwargs: Any) -> APIResponse:
        return self.request("delete", url, **kwargs)


@pytest.fixture(scope="session")
def _api_context(playwright: Playwright, base_url: str) -> Iterator[APIRequestContext]:
    context = playwright.request.new_context(base_url=base_url)
    yield context
    context.dispose()


@pytest.fixture
def api(_api_context: APIRequestContext, e2e_log: JsonlWriter, request: pytest.FixtureRequest) -> Api:
    return Api(_api_context, e2e_log, request.node.nodeid)


@pytest.fixture
def journal(api: Api) -> Iterator[Journal]:
    """Creates records through the public API and deletes them again when the test ends."""
    journal = Journal(api)
    yield journal
    journal.cleanup()


# --- DOM tests: client-side logging and the clean-run rule ---------------------------------------


def _allowed_patterns(node: pytest.Item) -> list[tuple[re.Pattern[str], str]]:
    allowed: list[tuple[re.Pattern[str], str]] = []
    for mark in node.iter_markers("allow_console_errors"):
        reason = str(mark.kwargs.get("reason", "")).strip()
        if not reason or not mark.args:
            pytest.fail("allow_console_errors needs at least one regex and reason='why this error is expected'", pytrace=False)
        allowed += [(re.compile(pattern), reason) for pattern in mark.args]
    return allowed


class ClientCapture:
    """Turns browser-side events into log records (source=client) and enforces the clean-run rule.

    Console errors, uncaught page errors, failed requests and HTTP 5xx responses are errors. They
    fail the test unless allow-listed with @pytest.mark.allow_console_errors(<regex>, reason=...),
    in which case they are logged as warnings carrying the reason.
    """

    def __init__(self, page: Page, log: JsonlWriter, test_id: str, allowed: list[tuple[re.Pattern[str], str]]) -> None:
        self._page = page
        self._log = log
        self._test = test_id
        self._allowed = allowed
        self.unexpected: list[str] = []
        page.on("console", self._on_console)
        page.on("pageerror", self._on_page_error)
        page.on("requestfailed", self._on_request_failed)
        page.on("response", self._on_response)
        page.on("framenavigated", self._on_navigated)
        log.write("client", "info", "page_open", test=test_id)

    def _emit(self, level: str, msg: str, **fields: Any) -> None:
        if level == "error":
            reason = next((why for pattern, why in self._allowed if pattern.search(msg)), None)
            if reason is None:
                self.unexpected.append(msg)
            else:
                level, fields["allowed"] = "warning", reason
        self._log.write("client", level, msg, test=self._test, **fields)

    def _on_console(self, message: ConsoleMessage) -> None:
        location = message.location
        self._emit(
            _CONSOLE_LEVELS.get(message.type, "info"),
            message.text,
            kind=f"console.{message.type}",
            url=location.get("url"),
            line=location.get("lineNumber"),
        )

    def _on_page_error(self, error: Error) -> None:
        self._emit("error", error.message, kind="pageerror", stack=(error.stack or "")[:1000])

    def _on_request_failed(self, request: Request) -> None:
        self._emit("error", f"request failed: {request.method} {request.url} ({request.failure})", kind="requestfailed")

    def _on_response(self, response: Response) -> None:
        url = urlparse(response.url)
        if url.path.startswith("/api/"):
            # What the browser saw. A response that carries no X-Request-ID did not come from the server
            # (a test mocked it), which verify.py uses to match the rest against the server's own records.
            self._log.write(
                "client",
                "info",
                "api_response",
                test=self._test,
                method=response.request.method,
                path=url.path,
                status=response.status,
                request_id=response.request.headers.get("x-request-id"),
                echoed_id=response.headers.get("x-request-id"),
            )
        if response.status >= 400:
            level = "error" if response.status >= 500 else "warning"
            self._emit(level, f"HTTP {response.status}: {response.request.method} {response.url}", kind="response", status=response.status)

    def _on_navigated(self, frame: Frame) -> None:
        if frame.parent_frame is None:
            self._log.write("client", "info", "navigated", test=self._test, url=frame.url)

    def assert_clean(self) -> None:
        try:
            self._page.evaluate("0")  # round trip, so browser events queued before it are delivered first
        except Error:
            pass
        self._log.write("client", "info", "page_close", test=self._test, unexpected_errors=len(self.unexpected))
        if self.unexpected:
            shown = "\n  ".join(self.unexpected[:10])
            pytest.fail(
                f"{len(self.unexpected)} unexpected browser error(s). Allow-list expected ones with "
                f"@pytest.mark.allow_console_errors(<regex>, reason=...):\n  {shown}",
                pytrace=False,
            )


@pytest.fixture
def page(context: BrowserContext, request: pytest.FixtureRequest, e2e_log: JsonlWriter) -> Iterator[Page]:
    """pytest-playwright's page, plus client-side logging and the clean-run rule."""
    page = context.new_page()
    capture = ClientCapture(page, e2e_log, request.node.nodeid, _allowed_patterns(request.node))
    yield page
    capture.assert_clean()


@pytest.fixture
def shot(page: Page, request: pytest.FixtureRequest, screenshots_dir: Path, e2e_log: JsonlWriter) -> Callable[[str], Path]:
    """Takes a full-page screenshot into artifacts/phase_N/screenshots/<test>__<step>.png."""

    def take(step: str) -> Path:
        path = screenshots_dir / shot_name(request.node.name, step)
        page.screenshot(path=str(path), full_page=True, animations="disabled")
        e2e_log.write("test", "info", "screenshot", test=request.node.nodeid, file=path.name)
        return path

    return take
