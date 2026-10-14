import time
from pathlib import Path
from typing import Callable

import pytest
from playwright.sync_api import Error, Page

from support.feeds import SOURCES, Feeds, stub
from support.ui import capture_tall, shot_name

_started = False


@pytest.fixture(autouse=True)
def feeds_have_started(api):
    """The app fetches both feeds as it starts, and nothing below may run before that has happened."""
    global _started
    if _started:
        return
    deadline = time.monotonic() + 40
    while True:
        rows = {row["source"]: row for row in api.get("/api/sources/status").json()}
        if all(rows[name]["status"] == "ok" and rows[name]["state"] == "idle" for name in SOURCES):
            _started = True
            return
        if time.monotonic() > deadline:
            state = {name: (row["status"], row["state"], row["message"]) for name, row in rows.items()}
            pytest.exit(f"the feeds were not fetched at startup: {state}", returncode=2)
        time.sleep(0.25)


@pytest.fixture
def feeds(api):
    """Syncs and the stub's script. A test that changes what the stub says gets the baseline back afterwards."""
    helper = Feeds(api, stub())
    yield helper
    if helper.dirty:
        helper.restore()


@pytest.fixture
def leave_the_app_before_cleanup(page: Page, feeds, journal):
    """Torn down before the page, `feeds` and the journal are: the browser leaves the app, with the network quiet, before the
    baseline is restored and before records a test created are deleted, so a page does not refetch them in the middle of either."""
    yield
    try:
        page.wait_for_load_state("networkidle")
        page.goto("about:blank")
    except Error:
        pass  # the page is already gone, so there is nothing left to refetch


@pytest.fixture
def shot(page: Page, request: pytest.FixtureRequest, screenshots_dir: Path, e2e_log) -> Callable[[str], Path]:
    """Screenshots the whole screen into artifacts/phase_N/screenshots/<test>__<step>.png (the app scrolls inside its own
    container, so this grows the viewport to see all of it; see support/ui.py)."""

    def take(step: str) -> Path:
        path = screenshots_dir / shot_name(request.node.name, step)
        capture_tall(page, path)
        e2e_log.write("test", "info", "screenshot", test=request.node.nodeid, file=path.name)
        return path

    return take
