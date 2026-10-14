"""Phase 1: the interactive API docs render from vendored assets, with no request leaving the machine.

Swagger UI is third-party markup, so this test selects by its CSS classes instead of data-testid.
"""
from playwright.sync_api import Page, expect

OPERATION_METHODS = ("get", "post", "put", "patch", "delete")


def test_swagger_ui_lists_every_operation_without_leaving_the_machine(page: Page, api, base_url, shot):
    schema = api.get("/api/openapi.json").json()
    expected = sum(1 for item in schema["paths"].values() for method in item if method in OPERATION_METHODS)
    outside: list[str] = []
    page.on("request", lambda request: None if request.url.startswith((base_url, "data:")) else outside.append(request.url))

    page.goto("/api/docs")
    expect(page.locator(".swagger-ui .info .title")).to_contain_text("Trading Journal API")
    expect(page.locator(".opblock-summary-path")).to_have_count(expected)
    expect(page.locator("h3.opblock-tag")).to_have_count(len(schema["tags"]))
    shot("swagger-ui")
    assert outside == [], f"the docs page requested resources from outside: {outside}"
