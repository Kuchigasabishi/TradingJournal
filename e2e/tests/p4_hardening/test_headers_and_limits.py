"""Phase 4: what the server says about itself and what it refuses.

Security headers on every kind of answer, a content security policy that the real app runs under without one violation, and a
request body bigger than the server accepts. The unit tests (backend/tests/test_security.py) cover the middleware in isolation;
this module covers it on the real stack, behind the container when the backend is compose.
"""
import pytest
from playwright.sync_api import Error as PlaywrightError, Page, expect

from support.ui import open_app

COMMON = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
    "cross-origin-opener-policy": "same-origin",
    "cross-origin-resource-policy": "same-origin",
}


@pytest.mark.parametrize("path", ["/", "/calendar", "/day/2044-05-12", "/api/health", "/api/trades", "/api/nothing-here", "/api/docs", "/api/openapi.json"])
def test_every_kind_of_answer_carries_the_common_headers(api, path):
    headers = api.get(path).headers
    for name, value in COMMON.items():
        assert headers.get(name) == value, f"{path} lacks {name}"
    assert "camera=()" in headers["permissions-policy"]


def test_pages_carry_a_policy_that_allows_this_origin_only_and_the_api_is_not_cached(api):
    page = api.get("/calendar").headers["content-security-policy"]
    for directive in ("default-src 'self'", "script-src 'self'", "connect-src 'self'", "object-src 'none'", "frame-ancestors 'none'", "form-action 'self'"):
        assert directive in page
    assert "unsafe-inline" not in page.split("style-src")[0], "scripts never get the blanket allowance"
    assert api.get("/api/trades").headers["cache-control"] == "no-store"
    assert "content-security-policy" not in api.get("/api/health").headers


def test_the_docs_page_pins_its_one_inline_script_by_hash(api):
    policy = api.get("/api/docs").headers["content-security-policy"]
    assert "script-src 'self' 'sha256-" in policy and "'unsafe-inline'" not in policy.split("style-src")[0]


@pytest.mark.parametrize("route", ["/", "/calendar?month=2044-05", "/day/2044-05-12", "/trades", "/trades/new", "/api/docs"])
def test_the_app_runs_under_its_policy_without_one_violation(page: Page, route):
    page.add_init_script(
        "window.__violations = [];"
        "document.addEventListener('securitypolicyviolation', (e) => window.__violations.push(e.violatedDirective + ' ' + e.blockedURI));"
    )
    if route.startswith("/api/docs"):
        page.goto(route)
        expect(page.locator(".swagger-ui .info .title")).to_contain_text("Trading Journal API")
    else:
        open_app(page, route)
        expect(page.get_by_test_id("app-ready")).to_be_visible()
    page.wait_for_load_state("networkidle")
    assert page.evaluate("window.__violations") == []


def test_a_body_over_the_limit_is_refused_and_a_normal_one_is_not(api):
    notes_before = api.get("/api/notes?limit=1").json()["total"]
    # The server answers 413 from the declared length, before reading a byte, and closes the connection. A client that is still
    # uploading then sees the connection drop (Playwright reports "aborted" and keeps the 413 in its call log), so both are the refusal.
    try:
        status = api.post("/api/notes", data={"day": "2044-05-11", "body": "x" * 1_200_000}).status
    except PlaywrightError as error:
        status = 413 if "413 Content Too Large" in str(error) else None
    assert status == 413
    assert api.get("/api/notes?limit=1").json()["total"] == notes_before, "nothing was stored"
    assert api.post("/api/notes", data={"day": "2044-05-11", "body": "x" * 10_001}).status == 422  # past the note's own limit: the field rule, not the size rule
