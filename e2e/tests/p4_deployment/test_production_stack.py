"""Phase 4: the production definition, run as a person would run it.

scripts/verify.py --backend compose starts a second stack from docker-compose.yml alone (no test settings: APP_ENV=prod, the
feeds off, the zone UTC, an empty volume) and runs this module against it from the test container. The first pass writes
a trade through the browser. The harness then removes the container and starts a new one on the same volume, and the
`after_restart` test finds the trade. The module owns its order: browser tests run first, in the order written, so the
first-run test sees the empty journal it needs.
"""
import re

import pytest
from playwright.sync_api import Page, expect

from support.ui import expect_api, open_app, wall_to_utc

pytestmark = pytest.mark.deployment

INSTRUMENT = "DEPLOYSMOKE"
OPENED, CLOSED = "2040-03-04 09:30", "2040-03-04 11:45"  # typed in the server's zone, which is UTC here
FEEDS_OFF = "feeds are off (FEEDS_MODE=off)"


def test_a_new_installation_invites_the_first_trade(page: Page, api, shot):
    assert api.get("/api/trades").json()["total"] == 0, "the stack is not empty: it is not a fresh installation"
    open_app(page, "/")
    expect(page.get_by_test_id("dashboard-empty")).to_contain_text("Your journal is empty")
    shot("01-first-run")


def test_a_trade_is_logged_in_the_browser_and_lands_on_its_day(page: Page, api, shot):
    open_app(page, "/trades/new")
    page.get_by_test_id("field-instrument").fill(INSTRUMENT.lower())
    page.get_by_test_id("field-lot-size").fill("0.10")
    page.get_by_test_id("field-entry-price").fill("1.08543")
    page.get_by_test_id("field-opened-at").fill(OPENED)
    page.get_by_test_id("field-closed").click()
    page.get_by_test_id("field-exit-price").fill("1.08758")
    page.get_by_test_id("field-closed-at").fill(CLOSED)
    page.get_by_test_id("field-pnl").fill("21.50")
    shot("02-form")
    with expect_api(page, "POST", r"^/api/trades$") as call:
        page.get_by_test_id("form-submit").click()
    assert call.status == 201 and call.request_id.startswith("web-")
    # The server runs in UTC: the time typed is the instant stored, and the trade belongs to that UTC day.
    assert call.request_json["opened_at"] == wall_to_utc(OPENED, "UTC") == "2040-03-04T09:30:00Z"
    assert api.get("/api/calendar/month?year=2040&month=3").json()["days"][0]["date"] == "2040-03-04"

    open_app(page, "/calendar?month=2040-03")
    expect(page.get_by_test_id("day-pnl-2040-03-04")).to_have_text("+$21.50")
    shot("03-calendar")
    page.get_by_test_id("day-2040-03-04").click()
    expect(page.get_by_test_id("day-net-value")).to_have_text("+$21.50")


def test_the_feeds_are_off_until_they_are_configured_and_the_screen_says_why(page: Page, shot):
    open_app(page, "/calendar?month=2040-03")
    for name in ("forexfactory", "gcal"):
        expect(page.get_by_test_id(f"source-status-{name}")).to_have_text("Off")
        expect(page.get_by_test_id(f"source-off-{name}")).to_have_text(FEEDS_OFF)
    expect(page.get_by_test_id("sync-now")).to_be_disabled()
    shot("04-feeds-off")


def test_the_api_docs_work_in_production_without_leaving_the_machine(page: Page, api, base_url, shot):
    operations = sum(1 for item in api.get("/api/openapi.json").json()["paths"].values() for method in item if method in ("get", "post", "put", "patch", "delete"))
    outside: list[str] = []
    page.on("request", lambda request: None if request.url.startswith((base_url, "data:")) else outside.append(request.url))
    page.goto("/api/docs")
    expect(page.locator(".swagger-ui .info .title")).to_contain_text("Trading Journal API")
    expect(page.locator(".opblock-summary-path")).to_have_count(operations)
    shot("05-api-docs")
    assert outside == [], f"the docs requested resources from outside: {outside}"


def test_the_server_answers_as_a_production_server_does(api):
    assert api.get("/api/health").json() == {"status": "ok"}
    ready = api.get("/api/ready").json()
    assert (ready["status"], ready["database"], ready["timezone"]) == ("ready", "ok", "UTC")  # the default zone, nothing set it
    assert api.get("/").headers["content-type"].startswith("text/html")
    assert api.get("/calendar").headers["content-type"].startswith("text/html")  # the app owns every path outside /api
    unknown = api.get("/api/nothing-here")
    assert unknown.status == 404 and unknown.headers["content-type"].startswith("application/json")
    echoed = api.get("/api/health", headers={"X-Request-ID": "deploy-smoke-1"})
    assert echoed.headers["x-request-id"] == "deploy-smoke-1"
    # No CORS in production: the app and its API share one origin, so a page from elsewhere is not invited.
    foreign = api.get("/api/health", headers={"Origin": "http://localhost:8081"})
    assert "access-control-allow-origin" not in foreign.headers


def test_the_feeds_report_themselves_off_and_a_refresh_is_refused(api):
    rows = {row["source"]: row for row in api.get("/api/sources/status").json()}
    assert {name: (row["enabled"], row["disabled_reason"]) for name, row in rows.items()} == {"forexfactory": (False, FEEDS_OFF), "gcal": (False, FEEDS_OFF)}
    refused = api.post("/api/sync")
    assert refused.status == 409
    assert {result["outcome"] for result in refused.json()["sources"]} == {"disabled"}


@pytest.mark.after_restart
def test_the_trade_survived_the_container_being_replaced(page: Page, api, shot):
    stored = api.get(f"/api/trades?instrument={INSTRUMENT}").json()
    assert stored["total"] == 1, "the trade written before the container was replaced is gone"
    trade = stored["items"][0]
    assert (trade["opened_at"], trade["closed_at"], trade["pnl"]) == ("2040-03-04T09:30:00Z", "2040-03-04T11:45:00Z", "21.5")
    open_app(page, "/calendar?month=2040-03")
    expect(page.get_by_test_id("day-pnl-2040-03-04")).to_have_text("+$21.50")
    shot("06-after-the-container-was-replaced")
    ready = api.get("/api/ready").json()
    assert ready["status"] == "ready" and ready["migration"] == "0002"
