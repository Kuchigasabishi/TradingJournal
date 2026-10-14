"""Phase 0: the stub page loads, calls the API from the browser, and is captured as evidence."""
import pytest
from playwright.sync_api import Page, expect


@pytest.mark.stub_page
def test_stub_page_reaches_the_api(page: Page, shot):
    page.goto("/")
    expect(page.get_by_test_id("harness-title")).to_have_text("Trading Journal")
    expect(page.get_by_test_id("harness-ok")).to_have_text("API status: ok")
    shot("api-ok")


@pytest.mark.expo_app
def test_the_served_app_loads_and_reaches_the_api(page: Page, shot):
    """The compose image serves the real Expo app from the start, so its first browser evidence is the app itself: it loads,
    asks /api/ready (the boot gate) and /api/health (the status chip) and is captured."""
    page.goto("/")
    expect(page.get_by_test_id("app-ready")).to_be_visible()
    expect(page.get_by_test_id("api-status-label")).to_have_text("API online")
    shot("app-online")
