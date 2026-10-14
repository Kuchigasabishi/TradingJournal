"""Helpers for the browser tests of the Expo web app (Phase 2 on).

The app is a single-page React Native Web build served by FastAPI, so a test finds things by `data-testid`
(React Native's `testID`) and asserts on exact text. Dates and times come from fixed far-future years, so
no test depends on today's date, and expected UTC instants come from `zoneinfo`, an implementation that is
independent of the one the app uses.
"""
import re
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Iterator
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from playwright.sync_api import Page, Response, expect

# scripts/verify.py starts the server in this zone (VERIFY_TIMEZONE), and /api/ready reports it.
SERVER_TZ = "America/New_York"

_DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def day_label(day: date) -> str:
    """How the app writes a day: "Mon, Apr 6, 2037"."""
    return f"{_DAY_NAMES[day.weekday()]}, {_MONTH_NAMES[day.month - 1]} {day.day}, {day.year}"


def wall_to_utc(text: str, zone: str = SERVER_TZ) -> str:
    """The UTC instant for wall-clock text typed in `zone` ("2039-01-12 09:30" -> "2039-01-12T14:30:00Z")."""
    local = datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo(zone))
    return local.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_to_wall(iso: str, zone: str = SERVER_TZ) -> str:
    """The wall-clock text the app shows for a UTC instant ("2030-05-06T09:00:00Z" -> "2030-05-06 05:00")."""
    instant = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=ZoneInfo("UTC"))
    return instant.astimezone(ZoneInfo(zone)).strftime("%Y-%m-%d %H:%M")


def server_today(zone: str = SERVER_TZ) -> date:
    return datetime.now(ZoneInfo(zone)).date()


def open_app(page: Page, path: str = "/") -> None:
    """Loads a route and waits until the shell is up, which means /api/ready has answered."""
    page.goto(path)
    expect(page.get_by_test_id("app-ready")).to_be_visible()


@contextmanager
def expect_api(page: Page, method: str, path_pattern: str, query: dict[str, str] | None = None) -> Iterator["_Call"]:
    """Waits for one API response. `path_pattern` is a regex against the URL path, for example r"^/api/trades$".
    `query` narrows the match to responses whose query string carries all of these parameters, which tells a
    request the test just caused apart from one the page was already making.

        with expect_api(page, "POST", r"^/api/trades$") as call:
            page.get_by_test_id("form-submit").click()
        assert call.request_json["lot_size"] == "0.10"
    """
    pattern = re.compile(path_pattern)
    wanted = query or {}

    def matches(response: Response) -> bool:
        if response.request.method != method:
            return False
        parsed = urlparse(response.url)
        if not pattern.search(parsed.path):
            return False
        sent = parse_qs(parsed.query)
        return all(sent.get(name) == [value] for name, value in wanted.items())

    holder = _Call()
    with page.expect_response(matches) as info:
        yield holder
    holder.response = info.value


class _Call:
    """The request and response of one API call, filled in when the `with` block ends."""

    response: Response

    @property
    def status(self) -> int:
        return self.response.status

    @property
    def request_json(self):
        return self.response.request.post_data_json

    @property
    def query(self) -> dict[str, list[str]]:
        """The query string the app sent, for example {"sort": ["pnl"], "limit": ["25"]}."""
        return parse_qs(urlparse(self.response.url).query)

    @property
    def request_id(self) -> str:
        return self.response.request.headers.get("x-request-id", "")

    def json(self):
        return self.response.json()


def shot_name(test_name: str, step: str) -> str:
    """"test_x[chromium]" + "01-form" -> "test_x__01-form". Parameters other than the browser stay in the name."""
    cleaned = re.sub(r"-chromium\]$", "]", re.sub(r"\[chromium\]$", "", test_name))
    slug = lambda text: re.sub(r"[^A-Za-z0-9_.-]+", "-", text).strip("-")  # noqa: E731
    return f"{slug(cleaned)}__{slug(step)}.png"


def trade_id_from_url(page: Page) -> int:
    match = re.search(r"/trades/(\d+)", page.url)
    assert match, f"not on a trade page: {page.url}"
    return int(match.group(1))


def capture_tall(page: Page, path: Path) -> None:
    """Screenshots a whole screen. The app scrolls inside its own container, so a plain full-page shot only
    gets the viewport; this grows the viewport by however much content is hidden, captures, and restores it."""
    extra = page.evaluate(
        """() => {
            const scrollers = [...document.querySelectorAll('div')].filter((el) => {
                const overflow = getComputedStyle(el).overflowY;
                return (overflow === 'auto' || overflow === 'scroll') && el.scrollHeight > el.clientHeight + 1;
            });
            if (scrollers.length === 0) return 0;
            const tallest = scrollers.sort((a, b) => b.scrollHeight - a.scrollHeight)[0];
            return tallest.scrollHeight - tallest.clientHeight;
        }"""
    )
    original = page.viewport_size or {"width": 1280, "height": 800}
    if extra:
        page.set_viewport_size({"width": original["width"], "height": min(original["height"] + int(extra), 5000)})
    try:
        page.screenshot(path=str(path), animations="disabled")
    finally:
        if extra:
            page.set_viewport_size(original)
