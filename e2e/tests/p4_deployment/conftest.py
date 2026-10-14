from pathlib import Path
from typing import Callable

import pytest
from playwright.sync_api import Page

from support.ui import capture_tall, shot_name


@pytest.fixture
def shot(page: Page, request: pytest.FixtureRequest, screenshots_dir: Path, e2e_log) -> Callable[[str], Path]:
    """Screenshots the whole screen (the app scrolls inside its own container, so this grows the viewport to see all of it;
    see support/ui.py) into artifacts/phase_N/screenshots/<test>__<step>.png."""

    def take(step: str) -> Path:
        path = screenshots_dir / shot_name(request.node.name, step)
        capture_tall(page, path)
        e2e_log.write("test", "info", "screenshot", test=request.node.nodeid, file=path.name)
        return path

    return take
