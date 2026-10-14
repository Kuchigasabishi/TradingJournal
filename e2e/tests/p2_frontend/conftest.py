from pathlib import Path
from typing import Callable

import pytest
from playwright.sync_api import Error, Page

from support.ui import capture_tall, shot_name


@pytest.fixture(autouse=True)
def leave_the_app_before_cleanup(page: Page, journal):
    """Fixtures are torn down in the reverse order they were set up, and this one asks for the page and the journal
    first, so it is torn down before either. The browser leaves the app, with the network quiet, before the journal
    deletes what the test created. Without it a page still showing a record can refetch it a moment after the
    cleanup removed it, and the 404 fails an otherwise correct test."""
    yield
    try:
        page.wait_for_load_state("networkidle")
        page.goto("about:blank")
    except Error:
        pass  # the page is already gone, so there is nothing left to refetch


@pytest.fixture
def shot(page: Page, request: pytest.FixtureRequest, screenshots_dir: Path, e2e_log) -> Callable[[str], Path]:
    """Screenshots the whole screen into artifacts/phase_N/screenshots/<test>__<step>.png.

    Overrides the root fixture, which cannot see past the viewport because the app scrolls inside its own
    container. Steps are numbered by the tests ("01-form-empty"), so a folder listing reads as a story.
    """

    def take(step: str) -> Path:
        path = screenshots_dir / shot_name(request.node.name, step)
        capture_tall(page, path)
        e2e_log.write("test", "info", "screenshot", test=request.node.nodeid, file=path.name)
        return path

    return take
